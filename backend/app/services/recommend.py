"""Refresh orchestration: fetch from the provider → dedup → score → insert.

The order of operations preserves two invariants from the plan:

- **Dedup before spend.** Fetched postings are checked against every existing
  job (manual and recommended, dismissed included) by ``source_ref`` and by
  the advisory ``dedup_hash`` BEFORE any Claude call — a posting we already
  track never costs a scoring request.
- **Network outside the transaction, one commit.** All provider and Claude
  I/O finishes with results held in memory; the inserts then land in one
  short transaction. A failure mid-refresh leaves no partial rows, and the
  SQLite write lock is never held across a network call.

The DB's partial unique index on ``source_ref`` is the race backstop: if two
refreshes overlap, the loser's commit raises IntegrityError and the refresh
re-filters against the fresh DB state instead of failing.
"""

import logging

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import get_settings
from app.models import (
    ConfigProfile,
    ExperienceSource,
    ExperienceSourceType,
    Job,
    JobSource,
    RefreshSummary,
    ResumeSection,
    compute_dedup_hash,
)
from app.services import ai, job_source
from app.services.job_source import RawJob

logger = logging.getLogger(__name__)

# Requests spent per refresh press. ~30 postings; one daily refresh stays
# well inside JSearch's 200/month cap (see the plan's quota math).
PER_REFRESH_REQUEST_BUDGET = 3

# The engine reads only these source types for the experience profile;
# case_study/webpage are stored in config but unused by the v1 engine.
_PROFILE_SOURCE_TYPES = [
    ExperienceSourceType.resume,
    ExperienceSourceType.manual,
]


class ProfileEmptyError(Exception):
    """No experience data exists to match jobs against."""


def _build_profile(session: Session) -> str:
    """Assemble the experience profile: resume sections + manual sources."""
    sections = session.exec(
        select(ResumeSection).order_by(ResumeSection.position)
    ).all()
    sources = session.exec(
        select(ExperienceSource).where(
            ExperienceSource.type.in_(_PROFILE_SOURCE_TYPES)
        )
    ).all()
    parts = [f"{section.name}:\n{section.content}" for section in sections]
    parts += [source.content for source in sources if source.content]
    return "\n\n".join(parts)


def refresh(session: Session) -> RefreshSummary:
    """One refresh press: fetch, dedup, score net-new jobs, insert.

    Raises ``ProfileEmptyError`` (no experience data), the provider errors
    from ``job_source``, or ``AIUnavailableError`` when no Anthropic key is
    configured — checked before the fetch so JSearch quota is never spent on
    a refresh that can't score.
    """
    profile = _build_profile(session)
    if not profile:
        raise ProfileEmptyError(
            "The experience profile is empty — import a resume or add a "
            "manual experience source before refreshing recommendations."
        )
    if not get_settings().anthropic_api_key:
        raise ai.AIUnavailableError(
            "No Anthropic API key is configured, so fetched jobs could not "
            "be scored. Add ANTHROPIC_API_KEY to backend/.env before "
            "refreshing recommendations."
        )

    config = session.exec(select(ConfigProfile)).first()
    # Exact query shaping is deferred by the plan; prefer the configured
    # experience keywords, fall back to the profile's opening words.
    query = (config.experience if config else None) or " ".join(
        profile.split()[:12]
    )
    location = config.location if config else None

    # Snapshot the dedup set BEFORE network I/O (reads only — no write lock).
    existing_refs = {
        ref for ref in session.exec(select(Job.source_ref)).all() if ref
    }
    existing_hashes = set(session.exec(select(Job.dedup_hash)).all())

    # --- Network phase 1: fetch --------------------------------------------
    provider = job_source.build_provider()
    raw_jobs = provider.search(query, location, PER_REFRESH_REQUEST_BUDGET)

    skipped = 0
    net_new: list[tuple[RawJob, str]] = []
    for raw in raw_jobs:
        dedup_hash = compute_dedup_hash(
            raw.company, raw.position, raw.url or raw.location
        )
        if raw.source_ref in existing_refs or dedup_hash in existing_hashes:
            skipped += 1
            continue
        # Fold into the sets so duplicates within this batch dedup too.
        existing_refs.add(raw.source_ref)
        existing_hashes.add(dedup_hash)
        net_new.append((raw, dedup_hash))

    # --- Network phase 2: score net-new jobs only --------------------------
    prepared: list[tuple[RawJob, str, float | None, str | None]] = []
    score_failures = 0
    for raw, dedup_hash in net_new:
        score: float | None = None
        rationale: str | None = None
        if raw.description:  # empty description → insert unscored, no spend
            try:
                match = ai.score_job(
                    profile, raw.company, raw.position, raw.description
                )
                score, rationale = match.score, match.rationale
            except (ai.AIUnavailableError, ai.AIParseError) as exc:
                # One failed score shouldn't fail the refresh — insert the
                # job unscored so it stays visible and scoreable later.
                score_failures += 1
                logger.warning(
                    "scoring failed for %s: %s", raw.source_ref, exc
                )
        prepared.append((raw, dedup_hash, score, rationale))

    # --- One transaction: insert everything --------------------------------
    def make_job(
        raw: RawJob, dedup_hash: str, score: float | None, rationale: str | None
    ) -> Job:
        return Job(
            company=raw.company,
            position=raw.position,
            description=raw.description,
            url=raw.url,
            source=JobSource.recommended,
            source_ref=raw.source_ref,
            dedup_hash=dedup_hash,
            match_score=score,
            match_rationale=rationale,
        )

    to_insert = prepared
    session.add_all([make_job(*item) for item in to_insert])
    try:
        session.commit()
    except IntegrityError:
        # Race backstop: a concurrent refresh inserted one of these
        # source_refs after our snapshot. Re-filter against fresh DB state
        # and insert the survivors.
        session.rollback()
        fresh_refs = {
            ref for ref in session.exec(select(Job.source_ref)).all() if ref
        }
        fresh_hashes = set(session.exec(select(Job.dedup_hash)).all())
        to_insert = [
            item
            for item in prepared
            if item[0].source_ref not in fresh_refs
            and item[1] not in fresh_hashes
        ]
        session.add_all([make_job(*item) for item in to_insert])
        session.commit()

    skipped += len(prepared) - len(to_insert)
    return RefreshSummary(
        inserted=len(to_insert),
        skipped_duplicates=skipped,
        # Every inserted job without a score, whatever the reason...
        unscored=sum(1 for _, _, score, _ in to_insert if score is None),
        # ...and how many of the scoring attempts raised (a subset).
        score_failures=score_failures,
        remaining_quota=provider.remaining_quota,
    )

"""Database tables (SQLModel) and the API schemas derived from them.

Table models are internal — the API contract is the ``Read``/``Create``/
``Update`` variants defined next to each table. Internal fields
(``dedup_hash``, ``source_ref``) never appear in ``Read`` shapes.

Conventions:

- Timestamps are naive UTC (SQLite stores datetimes without timezone info).
- Status date columns (``applied_at`` / ``denied_at`` / ``accepted_at``) are
  plain, directly editable columns. Auto-setting them when a status change
  arrives is the jobs router's job (U3), not the model's — same for
  ``updated_at`` maintenance.
- API schemas for every domain (tracker, resume, tailoring, recommendations,
  config) live in this module, grouped under the section banners below.
"""

import hashlib
import re
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated
from urllib.parse import urlparse

from pydantic import PlainSerializer, field_validator
from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    """Naive UTC timestamp — matches how SQLite stores datetimes."""
    return datetime.now(UTC).replace(tzinfo=None)


# Datetimes are stored naive-UTC in SQLite (see module docstring), but the
# JSON wire format should say so explicitly. This annotated type serializes
# to an ISO 8601 string with a "Z" suffix — used on the Read/response
# schemas only, so SQLModel's column inference on table classes stays on
# plain ``datetime``.
UTCDateTime = Annotated[
    datetime,
    PlainSerializer(
        lambda v: v.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        return_type=str,
        when_used="json",
    ),
]


# ---------------------------------------------------------------------------
# Enums
#
# Deliberate v1 choice: enum validity is enforced at the ORM/API layer only.
# The DB stores these as plain VARCHAR (no CHECK constraint) — see the note
# in alembic/versions/0001_initial_schema.py.
# ---------------------------------------------------------------------------


class JobSource(str, Enum):
    manual = "manual"
    recommended = "recommended"


class JobStatus(str, Enum):
    not_started = "not_started"
    applied = "applied"
    denied = "denied"
    accepted = "accepted"


class ExperienceSourceType(str, Enum):
    resume = "resume"
    case_study = "case_study"
    webpage = "webpage"
    manual = "manual"


# ---------------------------------------------------------------------------
# Dedup hash (best-effort heuristic — see plan's Key Technical Decisions)
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = {"inc", "llc", "ltd", "co"}


def _normalize(value: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    value = re.sub(r"[^\w\s]", " ", value.lower())
    return " ".join(value.split())


def _strip_legal_suffixes(company: str) -> str:
    words = company.split()
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def compute_dedup_hash(
    company: str, position: str, url_or_location: str | None = None
) -> str:
    """Advisory duplicate-detection hash for a job posting.

    Normalizes company (minus trailing legal suffixes like "Inc.") and
    position, then folds in the URL's host (or the location text) so two real
    postings sharing a company+title aren't collapsed into one. Best-effort:
    "Sr." vs "Senior" still hash differently, and that's accepted — the hard
    dedup backstop is the unique ``source_ref`` index.
    """
    company_part = _strip_legal_suffixes(_normalize(company))
    position_part = _normalize(position)
    extra = ""
    if url_or_location:
        host = urlparse(url_or_location).netloc
        extra = host.lower() if host else _normalize(url_or_location)
    key = "|".join([company_part, position_part, extra])
    return hashlib.sha256(key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Job + sub-resources (tracker)
# ---------------------------------------------------------------------------


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """Normalize client-supplied datetimes to naive UTC before storage.

    SQLite's bind processing silently drops timezone offsets, so an aware
    input like ``09:30+05:00`` would otherwise be stored as ``09:30`` and
    later served as ``09:30Z`` — an instant that is hours wrong.
    """
    if value is not None and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


class JobBase(SQLModel):
    """Fields shared by the Job table, Create body, and Read response."""

    company: str
    position: str
    description: str | None = None
    url: str | None = None
    status: JobStatus = JobStatus.not_started
    # Editable so pre-app applications can be backdated (plan decision).
    applied_at: datetime | None = None
    denied_at: datetime | None = None
    accepted_at: datetime | None = None

    @field_validator("applied_at", "denied_at", "accepted_at", mode="after")
    @classmethod
    def _normalize_dates(cls, value: datetime | None) -> datetime | None:
        return _to_naive_utc(value)


class Job(JobBase, table=True):
    # The partial unique index is declared by hand (and hand-written in the
    # initial migration) because Alembic autogenerate can't be trusted with
    # partial indexes. It backstops provider dedup: same source_ref can never
    # insert twice, while manual jobs (source_ref NULL) are unconstrained.
    __table_args__ = (
        Index(
            "uq_job_source_ref",
            "source_ref",
            unique=True,
            sqlite_where=text("source_ref IS NOT NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: JobSource = JobSource.manual
    source_ref: str | None = None  # provider's posting id (internal)
    dedup_hash: str = Field(index=True)  # advisory, non-unique (internal)
    dismissed_at: datetime | None = None
    match_score: float | None = None
    match_rationale: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    comments: list["Comment"] = Relationship(
        back_populates="job", cascade_delete=True
    )
    contacts: list["Contact"] = Relationship(
        back_populates="job", cascade_delete=True
    )
    links: list["JobLink"] = Relationship(back_populates="job", cascade_delete=True)
    tailored_resumes: list["TailoredResume"] = Relationship(
        back_populates="job", cascade_delete=True
    )


class JobCreate(JobBase):
    """Manual add — status + dates accepted so past applications can be
    backfilled. ``source``/``dedup_hash`` are set by the server."""


class JobRead(JobBase):
    id: int
    source: JobSource
    # Datetime overrides so JSON responses carry an explicit UTC "Z" marker.
    applied_at: UTCDateTime | None = None
    denied_at: UTCDateTime | None = None
    accepted_at: UTCDateTime | None = None
    dismissed_at: UTCDateTime | None = None
    match_score: float | None = None
    match_rationale: str | None = None
    created_at: UTCDateTime
    updated_at: UTCDateTime


class JobUpdate(SQLModel):
    """PATCH body — everything optional; only provided fields change.

    ``company``/``position``/``status`` are non-nullable columns, so an
    explicit JSON ``null`` for them is rejected as a 422 (not a 500 at
    commit time).
    """

    company: str | None = None
    position: str | None = None
    description: str | None = None
    url: str | None = None
    status: JobStatus | None = None
    applied_at: datetime | None = None
    denied_at: datetime | None = None
    accepted_at: datetime | None = None

    @field_validator("applied_at", "denied_at", "accepted_at", mode="after")
    @classmethod
    def _normalize_dates(cls, value: datetime | None) -> datetime | None:
        return _to_naive_utc(value)

    @field_validator("company", "position", "status")
    @classmethod
    def _reject_explicit_null(cls, value, info):
        # Only runs when the field was provided (defaults skip validation),
        # so this rejects an explicit null without breaking omitted fields.
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value


class CommentBase(SQLModel):
    body: str


class Comment(CommentBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", ondelete="CASCADE")
    created_at: datetime = Field(default_factory=utcnow)

    job: Job = Relationship(back_populates="comments")


class CommentCreate(CommentBase):
    pass


class CommentRead(CommentBase):
    id: int
    job_id: int
    created_at: UTCDateTime


class ContactBase(SQLModel):
    name: str
    role: str | None = None
    email: str | None = None
    notes: str | None = None


class Contact(ContactBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", ondelete="CASCADE")

    job: Job = Relationship(back_populates="contacts")


class ContactCreate(ContactBase):
    pass


class ContactRead(ContactBase):
    id: int
    job_id: int


class JobLinkBase(SQLModel):
    url: str
    label: str | None = None


class JobLink(JobLinkBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", ondelete="CASCADE")

    job: Job = Relationship(back_populates="links")


class JobLinkCreate(JobLinkBase):
    pass


class JobLinkRead(JobLinkBase):
    id: int
    job_id: int


class JobListRow(JobRead):
    """One row of ``GET /jobs`` — everything Nathan's board row needs in a
    single call, with no follow-up requests. The derived fields are computed
    by the jobs router's list query."""

    # Latest of the job's own updated_at and its newest comment.
    last_activity_at: UTCDateTime
    comment_count: int
    contact_count: int
    link_count: int


class JobDetail(JobRead):
    """``GET /jobs/{id}`` — the job plus its nested sub-resources."""

    comments: list[CommentRead] = Field(default_factory=list)
    contacts: list[ContactRead] = Field(default_factory=list)
    links: list[JobLinkRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Master resume
# ---------------------------------------------------------------------------


class ResumeSection(SQLModel, table=True):
    """The current master resume, as ordered named sections."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    content: str
    position: int


class ResumeSectionRead(SQLModel):
    id: int
    name: str
    content: str
    position: int


class ResumeSectionUpdate(SQLModel):
    """PATCH body — everything optional; only provided fields change.

    All three columns are non-nullable, so an explicit JSON ``null`` is a
    422, not a 500 at commit time.
    """

    name: str | None = None
    content: str | None = None
    position: int | None = None

    @field_validator("name", "content", "position")
    @classmethod
    def _reject_explicit_null(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value


class ResumeRead(SQLModel):
    """``GET /resume`` — the whole master; ``sections`` is [] before any
    import (first-run contract for Nathan's screen, never a 404)."""

    sections: list[ResumeSectionRead] = Field(default_factory=list)


class ResumeImportText(SQLModel):
    """Body of ``POST /resume/import/text``; empty text is a 422."""

    text: str = Field(min_length=1)


class MasterSnapshot(SQLModel, table=True):
    """A retained copy of the outgoing master, taken on re-import (U4)."""

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)

    sections: list["MasterSnapshotSection"] = Relationship(
        back_populates="snapshot", cascade_delete=True
    )


class MasterSnapshotSection(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(foreign_key="mastersnapshot.id", ondelete="CASCADE")
    name: str
    content: str
    position: int

    snapshot: MasterSnapshot = Relationship(back_populates="sections")


class MasterSnapshotSectionRead(SQLModel):
    id: int
    name: str
    content: str
    position: int


class MasterSnapshotSummary(SQLModel):
    """One row of ``GET /resume/snapshots``."""

    id: int
    created_at: UTCDateTime
    section_count: int


class MasterSnapshotDetail(SQLModel):
    """``GET /resume/snapshots/{id}`` — full retained content, read-only."""

    id: int
    created_at: UTCDateTime
    sections: list[MasterSnapshotSectionRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tailored resumes
# ---------------------------------------------------------------------------


class TailoredResume(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", ondelete="CASCADE")
    is_submitted: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    job: Job = Relationship(back_populates="tailored_resumes")
    sections: list["TailoredSection"] = Relationship(
        back_populates="tailored_resume", cascade_delete=True
    )


class TailoredSection(SQLModel, table=True):
    """Self-contained snapshot of one section: owns its name, order, and
    content, so it renders even after the master is edited or re-imported.
    ``base_section_id`` is provenance only (SET NULL when the master section
    goes away)."""

    id: int | None = Field(default=None, primary_key=True)
    tailored_resume_id: int = Field(
        foreign_key="tailoredresume.id", ondelete="CASCADE"
    )
    base_section_id: int | None = Field(
        default=None, foreign_key="resumesection.id", ondelete="SET NULL"
    )
    name: str
    position: int
    content: str
    changed: bool = False  # True when Claude rewrote this section

    tailored_resume: TailoredResume = Relationship(back_populates="sections")


class TailorRequest(SQLModel):
    """Body of ``POST /jobs/{id}/tailor``. ``section_ids`` picks which master
    sections Claude rewrites (empty is a 422); ``description_override`` lets
    the user paste a posting when the job has none stored (and wins over the
    stored one when both exist)."""

    section_ids: list[int] = Field(min_length=1)
    description_override: str | None = None


class TailoredSectionRead(SQLModel):
    id: int
    base_section_id: int | None  # provenance only; NULL after re-import
    name: str
    position: int
    content: str
    changed: bool


class TailoredSectionUpdate(SQLModel):
    """PATCH body — everything optional; only provided fields change.

    All three columns are non-nullable, so an explicit JSON ``null`` is a
    422, not a 500 at commit time.
    """

    name: str | None = None
    content: str | None = None
    position: int | None = None

    @field_validator("name", "content", "position")
    @classmethod
    def _reject_explicit_null(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value


class TailoredResumeRead(SQLModel):
    """A full tailored copy — self-contained, renders with no master reads."""

    id: int
    job_id: int
    is_submitted: bool
    created_at: UTCDateTime
    sections: list[TailoredSectionRead] = Field(default_factory=list)


class TailoredResumeUpdate(SQLModel):
    """PATCH body — the submitted flag is the only mutable field."""

    is_submitted: bool


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConfigProfile(SQLModel, table=True):
    """Job-search parameters. A single row, created on first read (U6)."""

    id: int | None = Field(default=None, primary_key=True)
    experience: str | None = None
    location: str | None = None
    pay_min: int | None = None


class ExperienceSource(SQLModel, table=True):
    """One input to the experience-match profile (all four types storable;
    the v1 engine reads only resume + manual)."""

    id: int | None = Field(default=None, primary_key=True)
    type: ExperienceSourceType
    content: str | None = None
    url: str | None = None


class ConfigProfileRead(SQLModel):
    """``GET /settings/profile`` — the singleton row, no internal id."""

    experience: str | None
    location: str | None
    pay_min: int | None


class ConfigProfileUpdate(SQLModel):
    """``PUT /settings/profile`` body — a full replacement (PUT semantics):
    omitted fields become null, they are not preserved."""

    experience: str | None = None
    location: str | None = None
    pay_min: int | None = None


class ExperienceSourceCreate(SQLModel):
    type: ExperienceSourceType
    content: str | None = None
    url: str | None = None


class ExperienceSourceRead(SQLModel):
    id: int
    type: ExperienceSourceType
    content: str | None
    url: str | None


class RefreshSummary(SQLModel):
    """``POST /recommendations/refresh`` response — what one press did.

    ``unscored`` counts every inserted job without a match score, whatever
    the reason (no description to score, or a scoring failure).
    ``score_failures`` counts only the jobs whose AI scoring call raised —
    it is a subset of ``unscored``, exposed so the UI can distinguish "no
    description" from "scoring broke".
    ``remaining_quota`` is the provider's remaining monthly request count
    (from RapidAPI rate-limit headers); None when the provider didn't report
    one.
    """

    inserted: int
    skipped_duplicates: int
    unscored: int
    score_failures: int = 0
    remaining_quota: int | None = None

"""U2 model tests: relationships, cascades, dedup hashing, and the migration.

Note on status dates: auto-setting `applied_at`/`denied_at`/`accepted_at` when
a status change arrives is the jobs router's behavior (U3). Here the columns
are plain data — these tests only prove they exist, round-trip, and accept
explicit values (backdating).
"""

from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db import create_db_engine
from app.models import (
    Comment,
    Contact,
    Job,
    JobLink,
    JobRead,
    JobStatus,
    ResumeSection,
    TailoredResume,
    TailoredSection,
    compute_dedup_hash,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


def make_job(**overrides) -> Job:
    fields = dict(
        company="Genentech",
        position="Senior Scientist",
        dedup_hash=compute_dedup_hash(
            "Genentech", "Senior Scientist", "South San Francisco, CA"
        ),
    )
    fields.update(overrides)
    return Job(**fields)


def add_job_with_children(session: Session) -> int:
    """Insert a job with one comment, contact, and link; return its id."""
    job = make_job()
    job.comments = [Comment(body="Referred by Priya")]
    job.contacts = [Contact(name="Priya Shah", role="Hiring manager")]
    job.links = [JobLink(url="https://example.com/posting", label="Posting")]
    session.add(job)
    session.commit()
    return job.id


# ---------------------------------------------------------------------------
# Relationships and status dates
# ---------------------------------------------------------------------------


def test_job_relationships_round_trip(engine):
    with Session(engine) as session:
        job_id = add_job_with_children(session)

    with Session(engine) as session:  # fresh session: really reading the DB
        job = session.get(Job, job_id)
        assert job.company == "Genentech"
        assert [c.body for c in job.comments] == ["Referred by Priya"]
        assert [c.name for c in job.contacts] == ["Priya Shah"]
        assert [link.label for link in job.links] == ["Posting"]


def test_status_date_columns_round_trip(engine):
    """Columns exist, accept explicit values (backdating), and round-trip.

    Auto-setting them on status change is U3 router behavior, not the model's.
    """
    backdated = datetime(2026, 6, 1, 9, 30)
    with Session(engine) as session:
        job = make_job(status=JobStatus.applied, applied_at=backdated)
        session.add(job)
        session.commit()
        job_id = job.id

    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.applied
        assert job.applied_at == backdated
        assert job.denied_at is None

        job.status = JobStatus.denied
        job.denied_at = datetime(2026, 7, 1, 12, 0)
        session.add(job)
        session.commit()

    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job.denied_at == datetime(2026, 7, 1, 12, 0)
        assert job.applied_at == backdated  # earlier date untouched


# ---------------------------------------------------------------------------
# Cascades and FK behavior
# ---------------------------------------------------------------------------


def test_deleting_job_cascades_children(engine):
    with Session(engine) as session:
        job_id = add_job_with_children(session)

    # Core DELETE bypasses ORM cascade — proves the DDL-level ON DELETE
    # CASCADE fires (which requires the foreign_keys pragma to be active).
    with Session(engine) as session:
        session.execute(delete(Job).where(Job.id == job_id))
        session.commit()

    with Session(engine) as session:
        assert session.exec(select(Comment)).all() == []
        assert session.exec(select(Contact)).all() == []
        assert session.exec(select(JobLink)).all() == []


def test_deleting_resume_section_keeps_tailored_section_renderable(engine):
    with Session(engine) as session:
        job = make_job()
        base = ResumeSection(name="Experience", content="Lee Lab, 2020–", position=1)
        session.add(job)
        session.add(base)
        session.commit()

        tailored = TailoredResume(job_id=job.id)
        session.add(tailored)
        session.commit()
        session.add(
            TailoredSection(
                tailored_resume_id=tailored.id,
                base_section_id=base.id,
                name="Experience",
                position=1,
                content="Lee Lab, 2020– (tailored)",
                changed=True,
            )
        )
        session.commit()

        session.delete(base)
        session.commit()
        tailored_id = tailored.id

    with Session(engine) as session:
        section = session.exec(
            select(TailoredSection).where(
                TailoredSection.tailored_resume_id == tailored_id
            )
        ).one()
        # Provenance nulled, but the snapshot renders completely on its own.
        assert section.base_section_id is None
        assert section.name == "Experience"
        assert section.position == 1
        assert section.content == "Lee Lab, 2020– (tailored)"
        assert section.changed is True


def test_duplicate_source_ref_rejected(engine):
    with Session(engine) as session:
        session.add(make_job(source_ref="jsearch-abc123"))
        session.commit()
        session.add(make_job(source_ref="jsearch-abc123"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_null_source_refs_coexist(engine):
    with Session(engine) as session:
        session.add(make_job())
        session.add(make_job(company="Roche"))
        session.commit()
        assert len(session.exec(select(Job)).all()) == 2


# ---------------------------------------------------------------------------
# Dedup hash normalization (pure function)
# ---------------------------------------------------------------------------


def test_dedup_hash_ignores_punctuation_case_and_legal_suffix():
    assert compute_dedup_hash(
        "Genentech, Inc.", "Sr. Scientist", "South San Francisco, CA"
    ) == compute_dedup_hash("genentech", "sr scientist", "south san francisco ca")


def test_dedup_hash_uses_url_host_not_full_url():
    a = compute_dedup_hash(
        "Genentech, Inc.", "Sr. Scientist", "https://careers.example.com/jobs/1"
    )
    b = compute_dedup_hash(
        "genentech", "Sr. Scientist", "https://careers.example.com/jobs/2"
    )
    assert a == b  # same host — different posting paths don't matter


def test_dedup_hash_differs_across_locations_and_hosts():
    base = compute_dedup_hash("Genentech", "Scientist", "South San Francisco, CA")
    assert base != compute_dedup_hash("Genentech", "Scientist", "Boston, MA")
    assert compute_dedup_hash(
        "Genentech", "Scientist", "https://a.example.com/j/1"
    ) != compute_dedup_hash("Genentech", "Scientist", "https://b.example.com/j/1")


def test_dedup_hash_collapses_whitespace_and_missing_location():
    assert compute_dedup_hash("  Acme   LLC ", "Staff  Engineer") == compute_dedup_hash(
        "Acme", "Staff Engineer"
    )


def test_dedup_hash_strips_only_trailing_legal_suffixes():
    # "Co" inside a name is real; only trailing legal suffixes are dropped.
    assert compute_dedup_hash("Co Star Group", "Analyst") != compute_dedup_hash(
        "Star Group", "Analyst"
    )
    assert compute_dedup_hash("Star Group Co", "Analyst") == compute_dedup_hash(
        "Star Group", "Analyst"
    )


# ---------------------------------------------------------------------------
# API schema shapes
# ---------------------------------------------------------------------------


def test_job_read_shape_excludes_internal_fields():
    assert "dedup_hash" not in JobRead.model_fields
    assert "source_ref" not in JobRead.model_fields
    # And includes what Nathan's board row needs.
    for field in ("id", "source", "status", "match_score", "dismissed_at"):
        assert field in JobRead.model_fields


# ---------------------------------------------------------------------------
# Migration path (real `alembic upgrade head`, not create_all)
# ---------------------------------------------------------------------------


@pytest.fixture
def migrated_engine(tmp_path, monkeypatch):
    """An engine over a DB built by the real migration, then populated."""
    db_path = tmp_path / "migrated.db"
    # env.py reads the path through app settings, same as the server does.
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(config, "head")

    engine = create_db_engine(str(db_path))
    yield engine
    engine.dispose()


def test_migration_creates_all_model_tables(migrated_engine):
    from sqlmodel import SQLModel

    inspector = inspect(migrated_engine)
    db_tables = set(inspector.get_table_names())
    model_tables = {
        name for name in SQLModel.metadata.tables if not name.startswith("_")
    }  # skip throwaway pragma-test tables defined in test_health.py
    assert model_tables <= db_tables


def test_migrated_db_round_trips_and_cascades(migrated_engine):
    with Session(migrated_engine) as session:
        job_id = add_job_with_children(session)

    with Session(migrated_engine) as session:
        job = session.get(Job, job_id)
        assert [c.body for c in job.comments] == ["Referred by Priya"]

    with Session(migrated_engine) as session:
        session.execute(delete(Job).where(Job.id == job_id))
        session.commit()
        assert session.exec(select(Comment)).all() == []


def test_migrated_db_enforces_partial_source_ref_index(migrated_engine):
    with Session(migrated_engine) as session:
        session.add(make_job(source_ref="jsearch-xyz"))
        session.commit()
        session.add(make_job(source_ref="jsearch-xyz"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # NULL source_refs (manual jobs) are outside the partial index.
        session.add(make_job())
        session.add(make_job(company="Roche"))
        session.commit()

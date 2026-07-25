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
- Schemas for the resume/config endpoints arrive with their routers (U4–U6);
  only the tracker shapes (Job + sub-resources) are defined here.
"""

import hashlib
import re
from datetime import UTC, datetime
from enum import Enum
from urllib.parse import urlparse

from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    """Naive UTC timestamp — matches how SQLite stores datetimes."""
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Enums
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
    dismissed_at: datetime | None = None
    match_score: float | None = None
    match_rationale: str | None = None
    created_at: datetime
    updated_at: datetime


class JobUpdate(SQLModel):
    """PATCH body — everything optional; only provided fields change."""

    company: str | None = None
    position: str | None = None
    description: str | None = None
    url: str | None = None
    status: JobStatus | None = None
    applied_at: datetime | None = None
    denied_at: datetime | None = None
    accepted_at: datetime | None = None


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
    created_at: datetime


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


# ---------------------------------------------------------------------------
# Master resume
# ---------------------------------------------------------------------------


class ResumeSection(SQLModel, table=True):
    """The current master resume, as ordered named sections."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    content: str
    position: int


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

"""Tracker endpoints: jobs and their comments/contacts/links (U3).

This router touches only the database — zero AI or provider imports — so the
tracker works with no API keys configured.

Status-date rules (see the plan's Key Technical Decisions):

- A write that *changes* ``status`` auto-sets the matching date column
  (``applied`` → ``applied_at`` etc.) unless the same request provides that
  column explicitly — explicit dates always win, which is how backdating
  works.
- Re-application (denied → applied) simply overwrites ``applied_at`` with
  now: latest wins, and ``denied_at`` is retained.
- A status change also clears ``dismissed_at``: any pipeline transition is a
  "keep", so a dismissed job can never sit invisible on the default board.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.db import get_session
from app.models import (
    Comment,
    CommentCreate,
    CommentRead,
    Contact,
    ContactCreate,
    ContactRead,
    Job,
    JobCreate,
    JobDetail,
    JobLink,
    JobLinkCreate,
    JobLinkRead,
    JobListRow,
    JobRead,
    JobSource,
    JobStatus,
    JobUpdate,
    compute_dedup_hash,
    utcnow,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Which date column records entry into each status (not_started has none).
STATUS_DATE_COLUMNS = {
    JobStatus.applied: "applied_at",
    JobStatus.denied: "denied_at",
    JobStatus.accepted: "accepted_at",
}


def get_job_or_404(job_id: int, session: Session) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@router.get("", response_model=list[JobListRow])
def list_jobs(
    status: JobStatus | None = None,
    include_dismissed: bool = False,
    q: str | None = None,
    session: Session = Depends(get_session),
) -> list[JobListRow]:
    """Every field Nathan's board row needs, in one round trip.

    Counts and the newest-comment time come from grouped subqueries joined
    onto the jobs — one SQL query total, no per-job follow-ups.
    """
    comment_agg = (
        select(
            Comment.job_id,
            func.count(Comment.id).label("count"),
            func.max(Comment.created_at).label("latest_at"),
        )
        .group_by(Comment.job_id)
        .subquery()
    )
    contact_agg = (
        select(Contact.job_id, func.count(Contact.id).label("count"))
        .group_by(Contact.job_id)
        .subquery()
    )
    link_agg = (
        select(JobLink.job_id, func.count(JobLink.id).label("count"))
        .group_by(JobLink.job_id)
        .subquery()
    )

    statement = (
        select(
            Job,
            func.coalesce(comment_agg.c.count, 0),
            comment_agg.c.latest_at,
            func.coalesce(contact_agg.c.count, 0),
            func.coalesce(link_agg.c.count, 0),
        )
        .outerjoin(comment_agg, comment_agg.c.job_id == Job.id)
        .outerjoin(contact_agg, contact_agg.c.job_id == Job.id)
        .outerjoin(link_agg, link_agg.c.job_id == Job.id)
    )
    if not include_dismissed:
        statement = statement.where(Job.dismissed_at.is_(None))
    if status is not None:
        statement = statement.where(Job.status == status)
    if q:
        pattern = f"%{q}%"
        # ilike → case-insensitive LIKE across the text fields.
        statement = statement.where(
            or_(
                Job.company.ilike(pattern),
                Job.position.ilike(pattern),
                Job.description.ilike(pattern),
            )
        )

    rows = []
    for job, comment_count, latest_comment_at, contact_count, link_count in (
        session.exec(statement)
    ):
        candidates = [job.updated_at]
        if latest_comment_at is not None:
            candidates.append(latest_comment_at)
        rows.append(
            JobListRow(
                **JobRead.model_validate(job).model_dump(),
                last_activity_at=max(candidates),
                comment_count=comment_count,
                contact_count=contact_count,
                link_count=link_count,
            )
        )
    rows.sort(key=lambda row: row.last_activity_at, reverse=True)
    return rows


@router.post("", response_model=JobRead, status_code=201)
def create_job(body: JobCreate, session: Session = Depends(get_session)) -> Job:
    """Manual add. An initial status + explicit dates are accepted so past
    applications can be backfilled; when the date is omitted, the matching
    column is stamped with now."""
    job = Job(
        **body.model_dump(),
        source=JobSource.manual,
        dedup_hash=compute_dedup_hash(body.company, body.position, body.url),
    )
    date_column = STATUS_DATE_COLUMNS.get(job.status)
    if date_column and getattr(job, date_column) is None:
        setattr(job, date_column, utcnow())
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobDetail)
def read_job(job_id: int, session: Session = Depends(get_session)) -> Job:
    """The job plus its nested comments/contacts/links."""
    return get_job_or_404(job_id, session)


@router.patch("/{job_id}", response_model=JobRead)
def update_job(
    job_id: int, body: JobUpdate, session: Session = Depends(get_session)
) -> Job:
    job = get_job_or_404(job_id, session)
    updates = body.model_dump(exclude_unset=True)
    status_changed = "status" in updates and updates["status"] != job.status

    for field, value in updates.items():
        setattr(job, field, value)

    if status_changed:
        # Auto-set the new status's date column — unless this same request
        # set it explicitly (explicit always wins). Overwriting an existing
        # value is deliberate: on re-application, latest wins.
        date_column = STATUS_DATE_COLUMNS.get(job.status)
        if date_column and date_column not in updates:
            setattr(job, date_column, utcnow())
        # Any pipeline transition is a "keep" — see module docstring.
        job.dismissed_at = None

    if {"company", "position", "url"} & updates.keys():
        job.dedup_hash = compute_dedup_hash(job.company, job.position, job.url)

    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, session: Session = Depends(get_session)) -> None:
    """Hard delete, cascading sub-resources and unsubmitted tailored copies.

    Refused (409) for recommended jobs — deleting one would punch a hole in
    the dedup set and cause re-fetch/re-score spend — and for jobs whose
    submitted tailored resume records what was actually sent out.
    """
    job = get_job_or_404(job_id, session)
    if job.source == JobSource.recommended:
        raise HTTPException(
            status_code=409,
            detail=(
                "Recommended jobs can't be deleted (that would let the next "
                "refresh re-import them) — dismiss the job instead."
            ),
        )
    if any(tailored.is_submitted for tailored in job.tailored_resumes):
        raise HTTPException(
            status_code=409,
            detail=(
                "This job has a submitted tailored resume, which records what "
                "was actually sent — clear its submitted flag first if you "
                "really want to delete the job."
            ),
        )
    session.delete(job)
    session.commit()


@router.post("/{job_id}/dismiss", response_model=JobRead)
def dismiss_job(job_id: int, session: Session = Depends(get_session)) -> Job:
    """Hide a job from the default list (recommendation-lifecycle action).

    Dismissal is a timestamp, not a status — the pipeline is untouched and
    the row stays in the dedup set, so a future refresh can't re-import the
    posting. Idempotent: dismissing an already-dismissed job keeps the
    original timestamp.
    """
    job = get_job_or_404(job_id, session)
    if job.dismissed_at is None:
        job.dismissed_at = utcnow()
        job.updated_at = utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
    return job


@router.post("/{job_id}/restore", response_model=JobRead)
def restore_job(job_id: int, session: Session = Depends(get_session)) -> Job:
    """Clear a dismissal — the job reappears in the default list."""
    job = get_job_or_404(job_id, session)
    if job.dismissed_at is not None:
        job.dismissed_at = None
        job.updated_at = utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@router.get("/{job_id}/comments", response_model=list[CommentRead])
def list_comments(
    job_id: int, session: Session = Depends(get_session)
) -> list[Comment]:
    return get_job_or_404(job_id, session).comments


@router.post("/{job_id}/comments", response_model=CommentRead, status_code=201)
def create_comment(
    job_id: int, body: CommentCreate, session: Session = Depends(get_session)
) -> Comment:
    get_job_or_404(job_id, session)
    comment = Comment(**body.model_dump(), job_id=job_id)
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


@router.delete("/{job_id}/comments/{comment_id}", status_code=204)
def delete_comment(
    job_id: int, comment_id: int, session: Session = Depends(get_session)
) -> None:
    get_job_or_404(job_id, session)
    comment = session.get(Comment, comment_id)
    if comment is None or comment.job_id != job_id:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found on job {job_id}",
        )
    session.delete(comment)
    session.commit()


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


@router.get("/{job_id}/contacts", response_model=list[ContactRead])
def list_contacts(
    job_id: int, session: Session = Depends(get_session)
) -> list[Contact]:
    return get_job_or_404(job_id, session).contacts


@router.post("/{job_id}/contacts", response_model=ContactRead, status_code=201)
def create_contact(
    job_id: int, body: ContactCreate, session: Session = Depends(get_session)
) -> Contact:
    get_job_or_404(job_id, session)
    contact = Contact(**body.model_dump(), job_id=job_id)
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact


@router.delete("/{job_id}/contacts/{contact_id}", status_code=204)
def delete_contact(
    job_id: int, contact_id: int, session: Session = Depends(get_session)
) -> None:
    get_job_or_404(job_id, session)
    contact = session.get(Contact, contact_id)
    if contact is None or contact.job_id != job_id:
        raise HTTPException(
            status_code=404,
            detail=f"Contact {contact_id} not found on job {job_id}",
        )
    session.delete(contact)
    session.commit()


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


@router.get("/{job_id}/links", response_model=list[JobLinkRead])
def list_links(
    job_id: int, session: Session = Depends(get_session)
) -> list[JobLink]:
    return get_job_or_404(job_id, session).links


@router.post("/{job_id}/links", response_model=JobLinkRead, status_code=201)
def create_link(
    job_id: int, body: JobLinkCreate, session: Session = Depends(get_session)
) -> JobLink:
    get_job_or_404(job_id, session)
    link = JobLink(**body.model_dump(), job_id=job_id)
    session.add(link)
    session.commit()
    session.refresh(link)
    return link


@router.delete("/{job_id}/links/{link_id}", status_code=204)
def delete_link(
    job_id: int, link_id: int, session: Session = Depends(get_session)
) -> None:
    get_job_or_404(job_id, session)
    link = session.get(JobLink, link_id)
    if link is None or link.job_id != job_id:
        raise HTTPException(
            status_code=404, detail=f"Link {link_id} not found on job {job_id}"
        )
    session.delete(link)
    session.commit()

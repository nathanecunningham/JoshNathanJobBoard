"""Tailored-resume endpoints (U5): create via Claude, read, edit, submit,
delete.

Lives in its own router (rather than resume.py) because its URLs span two
prefixes — ``/jobs/{id}/tailor(ed)`` and ``/tailored/{id}`` — and neither the
jobs router's ``/jobs`` prefix nor the resume router's ``/resume`` prefix
fits both. All AI work goes through ``services/ai.py`` (503 no key, 502
failed call — same mapping as resume import).

Invariants from the plan:

- The Claude call happens BEFORE any database write, and the whole copy
  (``TailoredResume`` + one ``TailoredSection`` per master section) lands in
  one commit — an AI failure leaves no partial rows.
- Tailored sections are self-contained snapshots: name, order, and content
  are copied at tailor time, so the copy renders even after the master is
  edited or destructively re-imported. ``base_section_id`` is provenance
  only.
- At most one submitted copy per job: setting ``is_submitted`` on one copy
  clears it on the job's others in the same transaction.
- A submitted copy records what was actually sent out, so deleting it is
  refused (409); unsubmitted copies are disposable work product.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db import get_session
from app.models import (
    Job,
    ResumeSection,
    TailoredResume,
    TailoredResumeRead,
    TailoredResumeUpdate,
    TailoredSection,
    TailoredSectionRead,
    TailoredSectionUpdate,
    TailorRequest,
)
from app.routers._shared import get_or_404
from app.services import ai

router = APIRouter(tags=["tailored"])


def _read_shape(tailored: TailoredResume) -> TailoredResumeRead:
    """The full read shape, sections in display order."""
    sections = sorted(tailored.sections, key=lambda s: s.position)
    return TailoredResumeRead(
        id=tailored.id,
        job_id=tailored.job_id,
        is_submitted=tailored.is_submitted,
        created_at=tailored.created_at,
        sections=[TailoredSectionRead.model_validate(s) for s in sections],
    )


@router.post(
    "/jobs/{job_id}/tailor",
    response_model=TailoredResumeRead,
    status_code=201,
)
def tailor_resume(
    job_id: int, body: TailorRequest, session: Session = Depends(get_session)
) -> TailoredResumeRead:
    """Create a tailored copy of the master for this job.

    Claude rewrites the selected sections against the job's description (or
    the pasted override); every other master section is snapshotted verbatim,
    so the copy is complete and self-contained.
    """
    job = get_or_404(session, Job, job_id, "Job")

    description = body.description_override or job.description
    if not description:
        raise HTTPException(
            status_code=422,
            detail=(
                "This job has no stored description — provide one as "
                "description_override to tailor against."
            ),
        )

    master_sections = session.exec(
        select(ResumeSection).order_by(ResumeSection.position)
    ).all()
    known_ids = {section.id for section in master_sections}
    unknown = sorted(set(body.section_ids) - known_ids)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown master resume section ids: {unknown}",
        )

    selected_ids = set(body.section_ids)
    to_rewrite = [
        ai.SectionToTailor(id=s.id, name=s.name, content=s.content)
        for s in master_sections
        if s.id in selected_ids
    ]

    # Network before transaction: the Claude call finishes (or fails with a
    # clean 503/502) before the first row is written.
    try:
        rewritten = ai.tailor_sections(description, to_rewrite)
    except ai.AIUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ai.AIParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    rewritten_by_id = {item.section_id: item.content for item in rewritten}

    # The master may have changed while the AI call ran (e.g. a concurrent
    # re-import deleted sections). The snapshot content in memory is still
    # complete, so nothing is lost — but a base_section_id pointing at a
    # vanished row would violate the FK. Re-check which ids still exist and
    # record provenance as None for the ones that are gone.
    surviving_ids = set(
        session.exec(select(ResumeSection.id)).all()
    )

    tailored = TailoredResume(job_id=job.id)
    session.add(tailored)
    session.flush()  # assigns tailored.id for the section rows below
    for section in master_sections:
        new_content = rewritten_by_id.get(section.id)
        session.add(
            TailoredSection(
                tailored_resume_id=tailored.id,
                base_section_id=(
                    section.id if section.id in surviving_ids else None
                ),
                name=section.name,
                position=section.position,
                content=new_content if new_content is not None else section.content,
                changed=new_content is not None,
            )
        )
    try:
        session.commit()
    except IntegrityError:
        # Belt-and-braces: the master changed again between the re-check
        # above and the commit. Nothing was written; ask the user to retry.
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="master resume changed during tailoring; retry",
        )
    session.refresh(tailored)
    return _read_shape(tailored)


@router.get("/jobs/{job_id}/tailored", response_model=list[TailoredResumeRead])
def list_tailored(
    job_id: int, session: Session = Depends(get_session)
) -> list[TailoredResumeRead]:
    """All tailored copies for a job, oldest first. 200 [] when none."""
    job = get_or_404(session, Job, job_id, "Job")
    copies = sorted(job.tailored_resumes, key=lambda t: t.id)
    return [_read_shape(tailored) for tailored in copies]


@router.get("/tailored/{tailored_id}", response_model=TailoredResumeRead)
def read_tailored(
    tailored_id: int, session: Session = Depends(get_session)
) -> TailoredResumeRead:
    return _read_shape(get_or_404(session, TailoredResume, tailored_id, "Tailored resume"))


@router.patch("/tailored/{tailored_id}", response_model=TailoredResumeRead)
def update_tailored(
    tailored_id: int,
    body: TailoredResumeUpdate,
    session: Session = Depends(get_session),
) -> TailoredResumeRead:
    """Set or clear the submitted flag.

    Setting it clears the flag on the job's other copies in the same
    transaction — at most one submitted copy per job, enforced here.
    """
    tailored = get_or_404(session, TailoredResume, tailored_id, "Tailored resume")
    if body.is_submitted:
        siblings = session.exec(
            select(TailoredResume)
            .where(TailoredResume.job_id == tailored.job_id)
            .where(TailoredResume.id != tailored.id)
        ).all()
        for sibling in siblings:
            sibling.is_submitted = False
            session.add(sibling)
    tailored.is_submitted = body.is_submitted
    session.add(tailored)
    session.commit()
    session.refresh(tailored)
    return _read_shape(tailored)


@router.patch(
    "/tailored/{tailored_id}/sections/{section_id}",
    response_model=TailoredSectionRead,
)
def update_tailored_section(
    tailored_id: int,
    section_id: int,
    body: TailoredSectionUpdate,
    session: Session = Depends(get_session),
) -> TailoredSection:
    """Manual edit of one tailored section — the visual builder's seam.

    Only ever touches the tailored copy; the master section it came from is
    never written.
    """
    get_or_404(session, TailoredResume, tailored_id, "Tailored resume")
    section = session.get(TailoredSection, section_id)
    if section is None or section.tailored_resume_id != tailored_id:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Section {section_id} not found on tailored resume "
                f"{tailored_id}"
            ),
        )
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(section, field, value)
    session.add(section)
    session.commit()
    session.refresh(section)
    return section


@router.delete("/tailored/{tailored_id}", status_code=204)
def delete_tailored(
    tailored_id: int, session: Session = Depends(get_session)
) -> None:
    """Delete an unsubmitted copy (sections cascade).

    Refused (409) for a submitted copy — it records what was actually sent
    with the application.
    """
    tailored = get_or_404(session, TailoredResume, tailored_id, "Tailored resume")
    if tailored.is_submitted:
        raise HTTPException(
            status_code=409,
            detail=(
                "This tailored resume is marked submitted — it records what "
                "was actually sent with the application. Clear the flag "
                "(PATCH is_submitted=false) first if you really want to "
                "delete it."
            ),
        )
    session.delete(tailored)
    session.commit()

"""Master resume endpoints: import (text or PDF), read, edit (U4).

All AI work goes through ``services/ai.py`` (the single Claude seam); this
router maps its two exceptions to HTTP errors — no key → 503, failed parse →
502 — with the database untouched in both cases.

Two invariants from the plan:

- The Claude call happens BEFORE any database write begins (network never
  runs inside a transaction), and the snapshot + replace of the master lands
  in one commit — a failure leaves no partial state.
- Re-import is destructive to master sections but never to tailored copies:
  the outgoing master is retained as an inspectable ``MasterSnapshot``, and
  ``TailoredSection`` rows are self-contained (their ``base_section_id``
  provenance is set to NULL by the FK when master sections are deleted).
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlmodel import Session, select

from app.db import get_session
from app.models import (
    MasterSnapshot,
    MasterSnapshotDetail,
    MasterSnapshotSection,
    MasterSnapshotSectionRead,
    MasterSnapshotSummary,
    ResumeImportText,
    ResumeRead,
    ResumeSection,
    ResumeSectionRead,
    ResumeSectionUpdate,
)
from app.services import ai

router = APIRouter(prefix="/resume", tags=["resume"])

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
PDF_MAGIC = b"%PDF-"


def _parse_or_http_error(
    text: str | None = None, pdf_bytes: bytes | None = None
) -> list[ai.ParsedSection]:
    """Call the AI seam and translate its failures into HTTP errors.

    Called before any database write, so a 503/502 leaves the DB unchanged.
    """
    try:
        return ai.parse_resume(text=text, pdf_bytes=pdf_bytes)
    except ai.AIUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ai.AIParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


def _replace_master(
    parsed: list[ai.ParsedSection], session: Session
) -> ResumeRead:
    """Snapshot the current master (if any), then replace it — one commit."""
    existing = session.exec(
        select(ResumeSection).order_by(ResumeSection.position)
    ).all()

    if existing:
        snapshot = MasterSnapshot()
        session.add(snapshot)
        session.flush()  # assigns snapshot.id for the section rows below
        for section in existing:
            session.add(
                MasterSnapshotSection(
                    snapshot_id=snapshot.id,
                    name=section.name,
                    content=section.content,
                    position=section.position,
                )
            )
        for section in existing:
            # The DELETE sets TailoredSection.base_section_id to NULL via the
            # FK (ON DELETE SET NULL) — tailored copies keep rendering from
            # their own copied name/content/order.
            session.delete(section)

    new_sections = [
        ResumeSection(name=p.name, content=p.content, position=index)
        for index, p in enumerate(parsed)
    ]
    session.add_all(new_sections)
    session.commit()

    for section in new_sections:
        session.refresh(section)
    return ResumeRead(
        sections=[ResumeSectionRead.model_validate(s) for s in new_sections]
    )


@router.post("/import/text", response_model=ResumeRead)
def import_text(
    body: ResumeImportText, session: Session = Depends(get_session)
) -> ResumeRead:
    """Parse pasted resume text into sections and make them the new master."""
    parsed = _parse_or_http_error(text=body.text)
    return _replace_master(parsed, session)


@router.post("/import/pdf", response_model=ResumeRead)
def import_pdf(
    file: UploadFile, session: Session = Depends(get_session)
) -> ResumeRead:
    """Parse an uploaded PDF into sections and make them the new master.

    The upload is validated before any Claude call — an oversized or non-PDF
    file is rejected with no AI spend.
    """
    # Read one byte past the cap so we can detect oversize without slurping
    # an arbitrarily large upload.
    data = file.file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail="PDF is larger than the 10 MB limit.",
        )
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(
            status_code=415,
            detail="File does not look like a PDF (missing %PDF- header).",
        )
    parsed = _parse_or_http_error(pdf_bytes=data)
    return _replace_master(parsed, session)


@router.get("", response_model=ResumeRead)
def read_resume(session: Session = Depends(get_session)) -> ResumeRead:
    """The current master. 200 with empty sections before any import."""
    sections = session.exec(
        select(ResumeSection).order_by(ResumeSection.position)
    ).all()
    return ResumeRead(
        sections=[ResumeSectionRead.model_validate(s) for s in sections]
    )


@router.get("/snapshots", response_model=list[MasterSnapshotSummary])
def list_snapshots(
    session: Session = Depends(get_session),
) -> list[MasterSnapshotSummary]:
    """Prior masters retained by re-imports (read-only; no restore in v1)."""
    snapshots = session.exec(
        select(MasterSnapshot).order_by(MasterSnapshot.created_at.desc())
    ).all()
    return [
        MasterSnapshotSummary(
            id=snapshot.id,
            created_at=snapshot.created_at,
            section_count=len(snapshot.sections),
        )
        for snapshot in snapshots
    ]


@router.get("/snapshots/{snapshot_id}", response_model=MasterSnapshotDetail)
def read_snapshot(
    snapshot_id: int, session: Session = Depends(get_session)
) -> MasterSnapshotDetail:
    snapshot = session.get(MasterSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404, detail=f"Snapshot {snapshot_id} not found"
        )
    sections = sorted(snapshot.sections, key=lambda s: s.position)
    return MasterSnapshotDetail(
        id=snapshot.id,
        created_at=snapshot.created_at,
        sections=[
            MasterSnapshotSectionRead.model_validate(s) for s in sections
        ],
    )


@router.patch("/sections/{section_id}", response_model=ResumeSectionRead)
def update_section(
    section_id: int,
    body: ResumeSectionUpdate,
    session: Session = Depends(get_session),
) -> ResumeSection:
    """Manual edit of one master section (name, content, or position)."""
    section = session.get(ResumeSection, section_id)
    if section is None:
        raise HTTPException(
            status_code=404, detail=f"Resume section {section_id} not found"
        )
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(section, field, value)
    session.add(section)
    session.commit()
    session.refresh(section)
    return section

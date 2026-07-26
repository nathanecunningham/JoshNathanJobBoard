"""Configuration endpoints (U6): the search profile + experience sources.

The profile is a singleton row created on first read — ``GET`` always
returns 200 with defaults, never 404, so Nathan's settings screen has a
deterministic first-run state. Experience sources accept all four types;
the v1 recommendation engine reads only ``resume`` and ``manual`` (asserted
in tests), the others are stored for later slices.
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.routers._shared import get_or_404
from app.models import (
    ConfigProfile,
    ConfigProfileRead,
    ConfigProfileUpdate,
    ExperienceSource,
    ExperienceSourceCreate,
    ExperienceSourceRead,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_or_create_profile(session: Session) -> ConfigProfile:
    profile = session.exec(select(ConfigProfile)).first()
    if profile is None:
        profile = ConfigProfile()
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


@router.get("/profile", response_model=ConfigProfileRead)
def read_profile(session: Session = Depends(get_session)) -> ConfigProfile:
    """The job-search parameters. Creates the default row on first read."""
    return _get_or_create_profile(session)


@router.put("/profile", response_model=ConfigProfileRead)
def update_profile(
    body: ConfigProfileUpdate, session: Session = Depends(get_session)
) -> ConfigProfile:
    """Full replacement (PUT): omitted fields become null."""
    profile = _get_or_create_profile(session)
    profile.experience = body.experience
    profile.location = body.location
    profile.pay_min = body.pay_min
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.get("/sources", response_model=list[ExperienceSourceRead])
def list_sources(
    session: Session = Depends(get_session),
) -> list[ExperienceSource]:
    return session.exec(select(ExperienceSource)).all()


@router.post("/sources", response_model=ExperienceSourceRead, status_code=201)
def create_source(
    body: ExperienceSourceCreate, session: Session = Depends(get_session)
) -> ExperienceSource:
    source = ExperienceSource(**body.model_dump())
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: int, session: Session = Depends(get_session)
) -> None:
    source = get_or_404(
        session, ExperienceSource, source_id, "Experience source"
    )
    session.delete(source)
    session.commit()

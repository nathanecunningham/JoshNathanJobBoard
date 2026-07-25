"""Recommendation endpoints (U6): the manual refresh.

Maps the service-layer errors to structured HTTP errors with actionable
messages — no key → 503, quota exhausted/low → 429 (distinct from a generic
upstream failure, which is 502), empty profile → 409. A scoring failure for
an individual job is NOT an error here: ``recommend.refresh`` inserts that
job unscored and the refresh succeeds.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.models import RefreshSummary
from app.services import ai, job_source, recommend

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("/refresh", response_model=RefreshSummary)
def refresh_recommendations(
    session: Session = Depends(get_session),
) -> RefreshSummary:
    """Fetch, dedup, score, and insert recommended jobs — one button press."""
    try:
        return recommend.refresh(session)
    except recommend.ProfileEmptyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except job_source.ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except job_source.ProviderQuotaError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except job_source.ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ai.AIUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

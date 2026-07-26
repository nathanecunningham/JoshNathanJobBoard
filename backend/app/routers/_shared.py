"""Small helpers shared by the routers."""

from fastapi import HTTPException
from sqlmodel import Session


def get_or_404(session: Session, model: type, item_id: int, label: str):
    """Fetch a row by primary key, or raise a 404 with a consistent message.

    ``label`` is the human-readable resource name used in the error, e.g.
    ``get_or_404(session, Job, 7, "Job")`` → 404 "Job 7 not found".
    """
    instance = session.get(model, item_id)
    if instance is None:
        raise HTTPException(
            status_code=404, detail=f"{label} {item_id} not found"
        )
    return instance

"""FastAPI application factory.

Run the dev server from backend/ with:

    uv run uvicorn app.main:app --reload
"""

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from app.db import get_session
from app.routers import jobs, recommendations, resume, settings, tailor

logger = logging.getLogger(__name__)


class HealthRead(BaseModel):
    """``GET /health`` response."""

    status: str
    database: str


def create_app() -> FastAPI:
    app = FastAPI(title="Job Board API")
    app.include_router(jobs.router)
    app.include_router(resume.router)
    app.include_router(tailor.router)
    app.include_router(recommendations.router)
    app.include_router(settings.router)

    # Allow the Vite dev server (Nathan's frontend) to call this API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Reshape FastAPI's default list-of-errors payload into the
        app-wide ``{"detail": "<string>"}`` shape, so every error response
        (validation or hand-raised) reads the same way on the frontend."""
        parts = []
        for error in exc.errors()[:3]:  # first errors are enough to act on
            field = ".".join(
                str(piece) for piece in error["loc"] if piece != "body"
            )
            message = error["msg"]
            parts.append(f"{field}: {message}" if field else message)
        return JSONResponse(status_code=422, content={"detail": "; ".join(parts)})

    @app.get("/health", response_model=HealthRead)
    def health(session: Session = Depends(get_session)) -> HealthRead:
        """Report app liveness and whether the database answers a query."""
        try:
            session.execute(text("SELECT 1"))
            database = "ok"
        except Exception:
            logger.warning("health check database probe failed", exc_info=True)
            database = "error"
        return HealthRead(status="ok", database=database)

    return app


app = create_app()

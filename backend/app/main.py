"""FastAPI application factory.

Run the dev server from backend/ with:

    uv run uvicorn app.main:app --reload
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlmodel import Session

from app.db import get_session
from app.routers import jobs


def create_app() -> FastAPI:
    app = FastAPI(title="Job Board API")
    app.include_router(jobs.router)

    # Allow the Vite dev server (Nathan's frontend) to call this API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health(session: Session = Depends(get_session)) -> dict:
        """Report app liveness and whether the database answers a query."""
        try:
            session.execute(text("SELECT 1"))
            database = "ok"
        except Exception:
            database = "error"
        return {"status": "ok", "database": database}

    return app


app = create_app()

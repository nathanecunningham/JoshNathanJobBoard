"""U1 scaffold tests: health endpoint, empty-env boot, and PRAGMA enforcement."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, SQLModel

from app.config import Settings
from app.main import create_app


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_schema_appears_in_openapi(client):
    """/health declares a response model, so the docs show its shape."""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "HealthRead" in schemas
    assert set(schemas["HealthRead"]["properties"]) == {"status", "database"}


def test_validation_errors_use_string_detail(client):
    """Both schema-level and hand-raised 422s return the app-wide
    ``{"detail": "<string>"}`` shape, not FastAPI's default error list."""
    # Schema-level: missing required fields on POST /jobs.
    response = client.post("/jobs", json={"company": "Acme"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "position" in detail  # names the offending field

    # Hand-raised: tailoring a job that has no stored description.
    job_id = client.post(
        "/jobs", json={"company": "Acme", "position": "Analyst"}
    ).json()["id"]
    response = client.post(f"/jobs/{job_id}/tailor", json={"section_ids": [1]})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert "description_override" in response.json()["detail"]


def test_app_boots_with_empty_environment(monkeypatch, tmp_path):
    """The app must start with no API keys configured (tracker-only mode)."""
    for var in ("ANTHROPIC_API_KEY", "JSEARCH_API_KEY", "DATABASE_PATH"):
        monkeypatch.delenv(var, raising=False)
    # Run from an empty directory so no .env file is picked up either.
    monkeypatch.chdir(tmp_path)

    settings = Settings()
    assert settings.anthropic_api_key is None
    assert settings.jsearch_api_key is None
    assert settings.database_path == "backend-local.db"

    app = create_app()
    assert app.title == "Job Board API"


# Two throwaway tables to prove foreign keys are enforced on real connections.
# (No application models exist yet in U1; these live only in the test suite.)
class _PragmaParent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)


class _PragmaChild(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="_pragmaparent.id")


def test_foreign_key_violation_fails(engine):
    """SQLite ignores FKs by default — prove our PRAGMA turns enforcement on."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_PragmaChild(parent_id=999))  # no such parent
        with pytest.raises(IntegrityError):
            session.commit()


def test_pragmas_active_on_connection(engine):
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"

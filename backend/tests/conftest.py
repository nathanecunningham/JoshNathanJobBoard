"""Shared test fixtures: a temp-file SQLite engine and a TestClient.

The test engine goes through the same ``create_db_engine`` as production, so
the PRAGMAs (foreign_keys=ON, journal_mode=WAL) are active in tests too — a
temp file is used rather than ``:memory:`` because WAL mode only applies to
file-backed databases.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import create_db_engine, get_session
from app.main import create_app


@pytest.fixture
def engine(tmp_path):
    engine = create_db_engine(str(tmp_path / "test.db"))
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine):
    """A TestClient whose app uses the temp test database."""
    app = create_app()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client

"""Alembic migration environment.

Configured for SQLModel metadata with ``render_as_batch=True`` — most schema
changes on SQLite require batch (table-rebuild) mode, so it is on from
revision one.

The database path comes from the same app settings the server uses
(``.env`` / ``DATABASE_PATH``), so migrations always target the app's file.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from app import models  # noqa: F401 — registers all tables on SQLModel.metadata
from app.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _database_url() -> str:
    return f"sqlite:///{get_settings().database_path}"


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running against a database."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # A plain engine on purpose — no PRAGMA foreign_keys here. Batch-mode
    # migrations rebuild tables (create new, copy rows, drop old), which FK
    # enforcement would reject mid-rebuild. Runtime connections get their
    # pragmas from app/db.py.
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

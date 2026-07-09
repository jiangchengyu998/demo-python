from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings


Base = declarative_base()
settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Session:
    with session_scope() as session:
        yield session


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def migrate_database(db_engine: Engine = engine) -> None:
    if db_engine.url.get_backend_name().startswith("mysql"):
        _ensure_mysql_database(db_engine)

        migration_sql = Path(__file__).parent.joinpath(
            "migrations", "V1__create_items.sql"
        ).read_text(encoding="utf-8")
        with db_engine.begin() as connection:
            connection.execute(text(migration_sql))
        return

    Base.metadata.create_all(db_engine)


def _ensure_mysql_database(db_engine: Engine) -> None:
    database_name = db_engine.url.database
    if not database_name:
        return

    server_url = _without_database(db_engine.url.render_as_string(hide_password=False))
    server_engine = create_engine(server_url, pool_pre_ping=True, future=True)
    try:
        with server_engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                    "DEFAULT CHARACTER SET utf8mb4 "
                    "COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        server_engine.dispose()


def _without_database(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/", parts.query, parts.fragment))

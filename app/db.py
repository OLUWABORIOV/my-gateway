from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "migrations" / "schema.sql"


def make_engine(database_url, *, pool_size=10, max_overflow=10, echo=False) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=1800,
        echo=echo,
        future=True,
    )


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False, future=True)


def _split_statements(sql):
    without_comments = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--"))
    return [chunk.strip() for chunk in without_comments.split(";") if chunk.strip()]


def init_schema(engine):
    statements = _split_statements(SCHEMA_PATH.read_text(encoding="utf-8"))
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def ping(engine):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
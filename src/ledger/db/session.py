from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str, **kwargs: Any) -> Engine:
    # READ COMMITTED (the PostgreSQL default) is intentional: every statement sees the latest
    # committed data, so a balance read issued right after acquiring the account lock
    # observes everything committed by the previous lock holder.
    return create_engine(url, pool_pre_ping=True, isolation_level="READ COMMITTED", **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)

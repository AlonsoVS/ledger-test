import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text

from ledger.db.models import CreditAccountModel
from ledger.db.session import make_engine, make_session_factory
from ledger.service import LedgerService
from tests.support import assert_invariants

TEST_DATABASE_URL = os.environ.get(
    "LEDGER_TEST_DATABASE_URL",
    "postgresql+psycopg://ledger:ledger@localhost:55432/ledger_test",
)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    # Large pool: concurrency tests hold one connection per thread while waiting on locks.
    engine = make_engine(TEST_DATABASE_URL, pool_size=20, max_overflow=80)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def service(engine: Engine, request: pytest.FixtureRequest) -> Iterator[LedgerService]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE transactions, credit_accounts"))
    ledger = LedgerService(make_session_factory(engine))
    yield ledger

    # Every database-backed test ends by verifying the invariants of every account it touched.
    if request.node.get_closest_marker("allow_invariant_violation"):
        return
    with engine.connect() as conn:
        account_ids = conn.execute(select(CreditAccountModel.id)).scalars().all()
    for account_id in account_ids:
        assert_invariants(ledger, account_id)

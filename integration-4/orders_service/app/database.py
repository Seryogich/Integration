from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import Settings, get_settings


class Base(DeclarativeBase):
    pass


def build_database_url(settings: Settings) -> URL:
    """Build the DSN programmatically so special characters in the password
    (/, +, =, @, ...) are escaped correctly (R1.6)."""
    return URL.create(
        drivername="postgresql+psycopg2",
        username=settings.postgres_user,
        password=settings.db_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )


@lru_cache
def get_engine() -> Engine:
    return create_engine(build_database_url(get_settings()), pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db():
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def migrate_db(engine: Engine | None = None) -> None:
    """Idempotent, additive migration of the `orders` table (Practice 2 -> Practice 3).

    * Practice 2 had a business column `status` (new|confirmed|completed|cancelled). Practice 3
      needs `status` for the forecast state (pending|priced|failed), so the old column is
      renamed to `order_status` and its data is kept.
    * `status` is added; existing rows become `priced` when a price is stored, else `failed`
      (the SQL from the task description).
    * `forecast_version` is added (guards against stale background results).
    Running it on an already migrated database does nothing.
    """
    engine = engine or get_engine()
    with engine.begin() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("orders")}
        if "order_status" not in columns and "status" in columns:
            conn.execute(text("ALTER TABLE orders RENAME COLUMN status TO order_status"))
            columns.discard("status")
            columns.add("order_status")
        if "status" not in columns:
            conn.execute(
                text("ALTER TABLE orders ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'pending'")
            )
            conn.execute(
                text(
                    "UPDATE orders SET status = CASE "
                    "WHEN predicted_price IS NULL THEN 'failed' ELSE 'priced' END"
                )
            )
        if "forecast_version" not in columns:
            conn.execute(
                text("ALTER TABLE orders ADD COLUMN forecast_version INTEGER NOT NULL DEFAULT 0")
            )
        if "model_version" not in columns:
            conn.execute(
                text("ALTER TABLE orders ADD COLUMN model_version VARCHAR(32)")
            )


def init_db() -> None:
    """Create missing tables (incl. `users`, `order_events`) and migrate `orders`."""
    from . import models  # noqa: F401  (registers tables on Base.metadata)

    Base.metadata.create_all(bind=get_engine())
    migrate_db()

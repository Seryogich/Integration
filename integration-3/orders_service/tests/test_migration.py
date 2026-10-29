"""Practice 2 -> Practice 3 schema migration (SQLite stands in for PostgreSQL)."""

from sqlalchemy import create_engine, inspect, text

from app.database import migrate_db

OLD_SCHEMA = """
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_name VARCHAR(128) NOT NULL,
    area_sqm FLOAT NOT NULL,
    bedrooms INTEGER NOT NULL,
    bathrooms INTEGER NOT NULL,
    year_built INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'new',
    predicted_price FLOAT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)
"""


def _old_database():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(OLD_SCHEMA))
        conn.execute(text("INSERT INTO orders (id, customer_name, area_sqm, bedrooms, bathrooms, year_built, status, predicted_price) VALUES (1, 'a', 80, 3, 2, 2010, 'confirmed', 99000.5)"))
        conn.execute(text("INSERT INTO orders (id, customer_name, area_sqm, bedrooms, bathrooms, year_built, status, predicted_price) VALUES (2, 'b', 60, 2, 1, 1999, 'new', NULL)"))
    return engine


def test_migration_keeps_business_status_and_derives_forecast_status():
    engine = _old_database()
    migrate_db(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("orders")}
    assert {"order_status", "status", "forecast_version"} <= columns

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, order_status, status, forecast_version FROM orders ORDER BY id")
        ).all()
    assert [tuple(r) for r in rows] == [(1, "confirmed", "priced", 0), (2, "new", "failed", 0)]


def test_migration_is_idempotent():
    engine = _old_database()
    migrate_db(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE orders SET status = 'pending' WHERE id = 2"))
    migrate_db(engine)  # must not rename/reset anything
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, order_status, status FROM orders ORDER BY id")).all()
    assert [tuple(r) for r in rows] == [(1, "confirmed", "priced"), (2, "new", "pending")]


def test_migration_on_fresh_schema_is_a_noop():
    from app.database import Base
    from app import models  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    migrate_db(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("orders")}
    assert {"order_status", "status", "forecast_version"} <= columns

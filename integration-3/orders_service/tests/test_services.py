"""Background task behaviour (variant A), tested without HTTP."""

import asyncio

from sqlalchemy import func, select, update

from app import services
from app.forecast_client import ForecastTimeout
from app.models import Order, OrderEvent


def _make_order(Session, **overrides):
    data = dict(customer_name="x", area_sqm=80.0, bedrooms=3, bathrooms=2, year_built=2010)
    with Session() as db:
        order = Order(**{**data, **overrides})
        db.add(order)
        db.commit()
        return order.id, order.forecast_version


def _order(Session, order_id):
    with Session() as db:
        return db.get(Order, order_id)


def _events(Session, order_id):
    with Session() as db:
        rows = db.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.id))
        return [(e.result, e.details) for e in rows]


def test_task_prices_the_order_and_logs(session_factory, monkeypatch):
    async def ok(http_client, params):
        return 123.45

    monkeypatch.setattr(services, "fetch_forecast", ok)
    order_id, version = _make_order(session_factory)
    asyncio.run(services.run_forecast_task(order_id, version))
    order = _order(session_factory, order_id)
    assert (order.status, order.predicted_price) == ("priced", 123.45)
    assert _events(session_factory, order_id) == [("priced", None)]


def test_task_failure_marks_failed(session_factory, monkeypatch):
    async def timeout(http_client, params):
        raise ForecastTimeout()

    monkeypatch.setattr(services, "fetch_forecast", timeout)
    order_id, version = _make_order(session_factory)
    asyncio.run(services.run_forecast_task(order_id, version))
    order = _order(session_factory, order_id)
    assert (order.status, order.predicted_price) == ("failed", None)
    assert _events(session_factory, order_id) == [("failed", "ForecastTimeout")]


def test_task_for_deleted_order_finishes_cleanly(session_factory):
    asyncio.run(services.run_forecast_task(999, 0))  # must not raise
    assert _events(session_factory, 999)[0][0] == "skipped"


def test_order_deleted_while_forecast_in_progress(session_factory, monkeypatch):
    order_id, version = _make_order(session_factory)

    async def delete_meanwhile(http_client, params):
        with session_factory() as db:
            db.delete(db.get(Order, order_id))
            db.commit()
        return 1.0

    monkeypatch.setattr(services, "fetch_forecast", delete_meanwhile)
    asyncio.run(services.run_forecast_task(order_id, version))  # must not raise
    assert _order(session_factory, order_id) is None
    assert _events(session_factory, order_id)[0][0] == "skipped"


def test_outdated_task_is_skipped(session_factory):
    order_id, _ = _make_order(session_factory)
    asyncio.run(services.run_forecast_task(order_id, 5))  # order is at version 0
    assert _order(session_factory, order_id).status == "pending"
    assert _events(session_factory, order_id)[0][0] == "skipped"


def test_result_of_stale_computation_is_discarded(session_factory, monkeypatch):
    """The order is modified (version bumped) while the forecast is running."""
    order_id, version = _make_order(session_factory)

    async def modify_meanwhile(http_client, params):
        with session_factory() as db:
            db.execute(update(Order).where(Order.id == order_id).values(forecast_version=version + 1))
            db.commit()
        return 777.0

    monkeypatch.setattr(services, "fetch_forecast", modify_meanwhile)
    asyncio.run(services.run_forecast_task(order_id, version))
    order = _order(session_factory, order_id)
    assert order.status == "pending" and order.predicted_price is None
    assert _events(session_factory, order_id)[0][0] == "skipped"


def test_task_is_idempotent(session_factory, monkeypatch):
    async def ok(http_client, params):
        return 42.0

    monkeypatch.setattr(services, "fetch_forecast", ok)
    order_id, version = _make_order(session_factory)
    for _ in range(3):
        asyncio.run(services.run_forecast_task(order_id, version))
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1  # no duplicates
    order = _order(session_factory, order_id)
    assert (order.status, order.predicted_price) == ("priced", 42.0)

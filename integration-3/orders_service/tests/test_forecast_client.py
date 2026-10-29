"""The real async Forecast client, against httpx.MockTransport (no network)."""

import asyncio

import httpx
import pytest

from app.forecast_client import (
    ForecastBadResponse,
    ForecastError,
    ForecastTimeout,
    fetch_forecast,
)

PARAMS = {"area_sqm": 80, "bedrooms": 3, "bathrooms": 2, "year_built": 2010}


def _call(handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_forecast(client, PARAMS)

    return asyncio.run(run())


def test_success():
    def handler(request):
        assert request.url.path == "/predict"
        return httpx.Response(200, json={"predicted_price": 123456.78, "model_version": "v1"})

    assert _call(handler) == 123456.78


def test_service_down_is_forecast_unavailable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ForecastError) as exc:
        _call(handler)
    assert exc.value.code == "ForecastUnavailable" and type(exc.value) is ForecastError


def test_http_error_status_is_forecast_unavailable():
    with pytest.raises(ForecastError) as exc:
        _call(lambda request: httpx.Response(503))
    assert exc.value.code == "ForecastUnavailable"


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(ForecastTimeout) as exc:
        _call(handler)
    assert exc.value.code == "ForecastTimeout"


def test_hard_deadline_applies_even_if_transport_hangs(monkeypatch):
    from dataclasses import replace

    from app import forecast_client

    settings = replace(forecast_client.get_settings(), forecast_timeout=0.2)
    monkeypatch.setattr(forecast_client, "get_settings", lambda: settings)

    async def handler(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json={"predicted_price": 1})

    with pytest.raises(ForecastTimeout):
        _call(handler)


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, json={"unexpected": 1}), httpx.Response(200, text="not json")],
)
def test_malformed_answer(response):
    with pytest.raises(ForecastBadResponse) as exc:
        _call(lambda request: response)
    assert exc.value.code == "ForecastBadResponse"

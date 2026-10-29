"""Asynchronous client of the internal Forecast API (Practice 3)."""

import asyncio
import logging

import httpx

from .config import get_settings

log = logging.getLogger("uvicorn.error")


class ForecastError(Exception):
    """The forecast could not be obtained. `code` is returned to API clients."""

    code = "ForecastUnavailable"


class ForecastTimeout(ForecastError):
    code = "ForecastTimeout"


class ForecastBadResponse(ForecastError):
    code = "ForecastBadResponse"


async def fetch_forecast(client: httpx.AsyncClient, params: dict) -> float:
    """One request to POST /predict with a hard overall deadline (FORECAST_TIMEOUT).

    Raises a ForecastError subclass instead of returning None, so callers can store
    *why* the forecast failed.
    """
    settings = get_settings()
    try:
        async with asyncio.timeout(settings.forecast_timeout):
            response = await client.post(f"{settings.forecast_url}/predict", json=params)
        response.raise_for_status()
        return float(response.json()["predicted_price"])
    except (TimeoutError, httpx.TimeoutException):
        raise ForecastTimeout() from None
    except httpx.HTTPError:  # connection refused / DNS failure (service down), 4xx, 5xx
        raise ForecastError() from None
    except (KeyError, TypeError, ValueError):
        raise ForecastBadResponse() from None

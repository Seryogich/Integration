"""Asynchronous client of the internal Forecast API (Practice 3/4)."""

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


async def fetch_forecast(client: httpx.AsyncClient, params: dict) -> tuple[float, str]:
    """One request to POST /predict with a hard overall deadline (FORECAST_TIMEOUT).

    Returns (predicted_price, model_version).
    Raises a ForecastError subclass instead of returning None.
    """
    settings = get_settings()
    try:
        async with asyncio.timeout(settings.forecast_timeout):
            response = await client.post(f"{settings.forecast_url}/predict", json=params)
        response.raise_for_status()
        body = response.json()
        return float(body["predicted_price"]), str(body.get("model_version", "unknown"))
    except (TimeoutError, httpx.TimeoutException):
        raise ForecastTimeout() from None
    except httpx.HTTPError:
        raise ForecastError() from None
    except (KeyError, TypeError, ValueError):
        raise ForecastBadResponse() from None

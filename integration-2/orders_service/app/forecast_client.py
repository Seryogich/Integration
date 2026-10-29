import logging

import httpx

from .config import get_settings

log = logging.getLogger("uvicorn.error")


def fetch_forecast(
    area_sqm: float, bedrooms: int, bathrooms: int, year_built: int
) -> float | None:
    """Ask the internal Forecast API for a price.

    Returns None when the service is unavailable, slow or answers badly, so
    order handling degrades gracefully instead of failing (Practice 1, R2.9).
    """
    settings = get_settings()
    try:
        response = httpx.post(
            f"{settings.forecast_url}/predict",
            json={
                "area_sqm": area_sqm,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "year_built": year_built,
            },
            timeout=settings.forecast_timeout,
        )
        response.raise_for_status()
        return float(response.json()["predicted_price"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("Forecast API unavailable (%s: %s); predicted_price=null", type(exc).__name__, exc)
        return None

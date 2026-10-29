"""Synthetic housing dataset matching the feature set expected by the Forecast API."""

from __future__ import annotations

import numpy as np
import pandas as pd

NUMERIC = ["area_sqm", "bedrooms", "bathrooms", "year_built"]
CATEGORICAL = ["district", "condition"]
TARGET = "price"
FEATURE_COLS = NUMERIC + CATEGORICAL


def make_dataset(n_samples: int = 2500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    area = rng.uniform(25, 400, n_samples)
    bedrooms = rng.integers(1, 7, n_samples)
    bathrooms = rng.integers(1, 5, n_samples)
    year = rng.integers(1950, 2025, n_samples)

    districts = np.array(["center", "north", "south", "east", "west"])
    district = rng.choice(districts, n_samples, p=[0.25, 0.2, 0.2, 0.2, 0.15])

    conditions = np.array(["poor", "average", "good", "excellent"])
    condition = rng.choice(conditions, n_samples, p=[0.1, 0.35, 0.4, 0.15])

    # Base price + interactions
    price = (
        1400.0 * area
        + 8500.0 * bedrooms
        + 13000.0 * bathrooms
        + 380.0 * (year - 1950)
        + rng.normal(0.0, 18000.0, n_samples)
    )

    district_bonus = {"center": 45000, "north": 12000, "south": 5000, "east": 8000, "west": -3000}
    condition_bonus = {"poor": -25000, "average": 0, "good": 18000, "excellent": 40000}
    price = price + np.array([district_bonus[d] for d in district])
    price = price + np.array([condition_bonus[c] for c in condition])
    price = np.clip(price, 25000.0, None)

    df = pd.DataFrame(
        {
            "area_sqm": area.round(1),
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "year_built": year,
            "district": district,
            "condition": condition,
            "price": price.round(2),
        }
    )
    return df

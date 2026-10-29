"""House price model: synthetic training data, out-of-sample evaluation, prediction.

The model is trained at service start-up on reproducible synthetic data. It is
evaluated out of sample (hold-out test split + 5-fold cross-validation) and the
metrics are exposed through GET /model/info.
"""

from dataclasses import dataclass, field

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import cross_val_score, train_test_split

FEATURES = ("area_sqm", "bedrooms", "bathrooms", "year_built")


@dataclass
class TrainedModel:
    estimator: GradientBoostingRegressor
    version: str
    metrics: dict = field(default_factory=dict)


def make_dataset(n_samples: int = 2000, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Generate a reproducible synthetic housing dataset."""
    rng = np.random.default_rng(seed)
    area = rng.uniform(25, 400, n_samples)
    bedrooms = rng.integers(1, 7, n_samples)
    bathrooms = rng.integers(1, 5, n_samples)
    year = rng.integers(1950, 2025, n_samples)

    price = (
        1500.0 * area
        + 9000.0 * bedrooms
        + 14000.0 * bathrooms
        + 450.0 * (year - 1950)
        + rng.normal(0.0, 15000.0, n_samples)
    )
    price = np.clip(price, 20000.0, None)

    X = np.column_stack([area, bedrooms, bathrooms, year]).astype(float)
    return X, price


def train_model(version: str = "v1", seed: int = 42, n_samples: int = 2000) -> TrainedModel:
    X, y = make_dataset(n_samples=n_samples, seed=seed)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed
    )

    estimator = GradientBoostingRegressor(random_state=seed)
    estimator.fit(X_train, y_train)

    y_pred = estimator.predict(X_test)
    cv_r2 = cross_val_score(
        GradientBoostingRegressor(random_state=seed), X, y, cv=5, scoring="r2"
    )

    metrics = {
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "test_mae": float(mean_absolute_error(y_test, y_pred)),
        "test_r2": float(r2_score(y_test, y_pred)),
        "cv5_r2_mean": float(cv_r2.mean()),
        "cv5_r2_std": float(cv_r2.std()),
    }
    return TrainedModel(estimator=estimator, version=version, metrics=metrics)


def predict_price(
    model: TrainedModel,
    area_sqm: float,
    bedrooms: int,
    bathrooms: int,
    year_built: int,
) -> float:
    row = np.array([[area_sqm, bedrooms, bathrooms, year_built]], dtype=float)
    return round(float(model.estimator.predict(row)[0]), 2)

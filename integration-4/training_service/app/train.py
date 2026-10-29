"""Practice 4 training pipeline: baseline Ridge + XGBoost Optuna search + MLflow registry."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import mlflow
import mlflow.data
import mlflow.sklearn
import numpy as np
import optuna
import pandas as pd
from mlflow.models import infer_signature
from mlflow.tracking import MlflowClient
from optuna.samplers import TPESampler
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor

from .dataset import CATEGORICAL, FEATURE_COLS, NUMERIC, TARGET, make_dataset

SEED = int(os.environ.get("SEED", "42"))
N_TRIALS = int(os.environ.get("N_TRIALS", "25"))
EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT_NAME", "house-price")
TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")


def evaluate(model, X, y) -> dict[str, float]:
    pred = model.predict(X)
    return {
        "holdout_r2": float(r2_score(y, pred)),
        "holdout_mae": float(mean_absolute_error(y, pred)),
        "holdout_rmse": float(np.sqrt(mean_squared_error(y, pred))),
        "holdout_mape": float(mean_absolute_percentage_error(y, pred)),
    }


def build_ridge_pipeline() -> Pipeline:
    prep = ColumnTransformer(
        [
            ("num", SimpleImputer(strategy="median"), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ]
    )
    return Pipeline(
        [
            ("prep", prep),
            (
                "model",
                TransformedTargetRegressor(
                    regressor=Ridge(alpha=1.0, random_state=SEED),
                    func=np.log1p,
                    inverse_func=np.expm1,
                ),
            ),
        ]
    )


def build_model(params: dict) -> Pipeline:
    prep = ColumnTransformer(
        [
            ("num", SimpleImputer(strategy="median"), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ]
    )
    return Pipeline(
        [
            ("prep", prep),
            (
                "model",
                TransformedTargetRegressor(
                    regressor=XGBRegressor(**params, random_state=SEED, n_jobs=2),
                    func=np.log1p,
                    inverse_func=np.expm1,
                ),
            ),
        ]
    )


def compute_and_log_stats(df: pd.DataFrame, y_train: pd.Series, run_id: str | None = None) -> dict:
    """Descriptive statistics + target distribution figures."""
    stats: dict = {
        "n_rows": int(len(df)),
        "n_features": len(FEATURE_COLS),
        "missing_fractions": {c: float(df[c].isna().mean()) for c in FEATURE_COLS + [TARGET]},
        "numeric_describe": df[NUMERIC + [TARGET]].describe().to_dict(),
        "categorical_counts": {c: df[c].value_counts().to_dict() for c in CATEGORICAL},
    }

    y = df[TARGET]
    skew_before = float(y.skew())
    skew_after = float(np.log1p(y).skew())
    stats["target_skewness_before"] = skew_before
    stats["target_skewness_after_log1p"] = skew_after

    mlflow.log_metric("n_rows", stats["n_rows"])
    mlflow.log_metric("target_skewness_before", skew_before)
    mlflow.log_metric("target_skewness_after_log1p", skew_after)

    # Figure: target before / after log1p
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].hist(y, bins=40, color="steelblue", edgecolor="white")
    axes[0].set_title(f"Target (skew={skew_before:.2f})")
    axes[0].set_xlabel("price")
    axes[1].hist(np.log1p(y), bins=40, color="darkorange", edgecolor="white")
    axes[1].set_title(f"log1p(Target) (skew={skew_after:.2f})")
    axes[1].set_xlabel("log1p(price)")
    fig.tight_layout()
    mlflow.log_figure(fig, "target_distributions.png")
    plt.close(fig)

    mlflow.log_dict(stats, "data_stats.json")
    return stats


def run_baseline(X_train, X_test, y_train, y_test, dataset_info) -> None:
    with mlflow.start_run(run_name="ridge-baseline") as run:
        model = build_ridge_pipeline()
        model.fit(X_train, y_train)
        metrics = evaluate(model, X_test, y_test)
        mlflow.log_params({"model_type": "ridge", "alpha": 1.0})
        mlflow.log_metrics(metrics)
        signature = infer_signature(X_train, model.predict(X_train))
        mlflow.sklearn.log_model(model, name="model", signature=signature)
        mlflow.log_input(dataset_info, context="train")
        print(f"[baseline] run_id={run.info.run_id} metrics={metrics}")


def run_optuna_search(X_train, y_train) -> optuna.Study:
    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 200, 1000),
            "max_depth": trial.suggest_int("max_depth", 2, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.0, 10.0),
        }
        model = build_model(params)
        cv = KFold(n_splits=5, shuffle=True, random_state=SEED)
        scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="r2", n_jobs=1)
        mean_r2 = float(scores.mean())
        # Nested child run
        with mlflow.start_run(run_name=f"trial-{trial.number}", nested=True):
            mlflow.log_params(params)
            mlflow.log_metric("cv_r2", mean_r2)
            mlflow.log_metric("cv_r2_std", float(scores.std()))
        return mean_r2

    sampler = TPESampler(seed=SEED)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    with mlflow.start_run(run_name="xgboost-optuna-parent") as parent:
        mlflow.log_param("n_trials", N_TRIALS)
        mlflow.log_param("sampler", "TPE")
        mlflow.log_param("seed", SEED)
        study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
        mlflow.log_metric("best_cv_r2", float(study.best_value))
        mlflow.log_params({f"best_{k}": v for k, v in study.best_params.items()})
        print(f"[optuna] parent_run={parent.info.run_id} best_cv_r2={study.best_value:.4f}")
        print(f"[optuna] best_params={study.best_params}")
    return study


def run_final(study: optuna.Study, X_train, X_test, y_train, y_test, df_train: pd.DataFrame, dataset_info) -> str:
    """Train final model, log artifacts, register and set @prod alias. Returns version string."""
    with mlflow.start_run(run_name="xgboost-final") as run:
        final_model = build_model(study.best_params)
        final_model.fit(X_train, y_train)

        mlflow.log_params(study.best_params)
        metrics = evaluate(final_model, X_test, y_test)
        mlflow.log_metrics(metrics)
        print(f"[final] hold-out metrics: {metrics}")

        signature = infer_signature(X_train, final_model.predict(X_train))
        mlflow.sklearn.log_model(final_model, name="model", signature=signature)

        # Dataset input with digest
        mlflow.log_input(dataset_info, context="train")

        # Stats + reference sample
        compute_and_log_stats(df_train.assign(**{TARGET: y_train.values}), y_train)
        ref = X_train.copy()
        ref_path = Path("/tmp/reference_data.parquet")
        ref.to_parquet(ref_path, index=False)
        mlflow.log_artifact(str(ref_path), artifact_path="")

        # Register + set alias
        model_uri = f"runs:/{run.info.run_id}/model"
        result = mlflow.register_model(model_uri, "house-price")
        client = MlflowClient()
        client.set_registered_model_alias("house-price", "prod", result.version)
        print(f"[registry] registered house-price v{result.version} and set alias @prod")
        return str(result.version)


def main() -> int:
    print(f"MLflow tracking URI: {TRACKING_URI}")
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT)

    # Data
    df = make_dataset(n_samples=2500, seed=SEED)
    # Persist a copy for transparency
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    csv_path = data_dir / "housing.csv"
    df.to_csv(csv_path, index=False)

    X = df[FEATURE_COLS]
    y = df[TARGET]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=SEED
    )
    df_train = X_train.copy()
    df_train[TARGET] = y_train.values

    # MLflow dataset (digest visible in UI)
    dataset_info = mlflow.data.from_pandas(
        df_train,
        source=str(csv_path),
        targets=TARGET,
        name="housing-train",
    )

    print("--- Baseline Ridge ---")
    run_baseline(X_train, X_test, y_train, y_test, dataset_info)

    print("--- Optuna search ---")
    study = run_optuna_search(X_train, y_train)

    print("--- Final model + register ---")
    version = run_final(study, X_train, X_test, y_train, y_test, df_train, dataset_info)
    print(f"DONE. @prod -> version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

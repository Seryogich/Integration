"""Forecast API – loads the production model from the MLflow Model Registry at startup."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import mlflow
from fastapi import FastAPI, HTTPException, Request
from mlflow.tracking import MlflowClient
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger("uvicorn.error")

MODEL_NAME = os.environ.get("MODEL_NAME", "house-price")
MODEL_ALIAS = os.environ.get("MODEL_ALIAS", "prod")
TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_sqm: float = Field(gt=0, le=5000)
    bedrooms: int = Field(ge=0, le=20)
    bathrooms: int = Field(ge=0, le=20)
    year_built: int = Field(ge=1800, le=2100)
    # Optional categoricals (present in the trained pipeline)
    district: str = Field(default="center", max_length=32)
    condition: str = Field(default="good", max_length=32)


class PredictResponse(BaseModel):
    predicted_price: float
    model_version: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    mlflow.set_tracking_uri(TRACKING_URI)
    client = MlflowClient()

    try:
        mv = client.get_model_version_by_alias(MODEL_NAME, MODEL_ALIAS)
    except Exception as exc:
        msg = (
            f"FATAL: cannot resolve models:/{MODEL_NAME}@{MODEL_ALIAS}. "
            f"Train and register a model first (docker compose --profile train run --rm trainer). "
            f"Underlying error: {exc}"
        )
        log.critical(msg)
        raise SystemExit(msg) from exc

    model_uri = f"models:/{MODEL_NAME}@{MODEL_ALIAS}"
    log.info("Loading model from %s (version %s, run_id=%s)", model_uri, mv.version, mv.run_id)
    app.state.model = mlflow.pyfunc.load_model(model_uri)
    app.state.model_version = str(mv.version)

    # Load descriptive statistics artifact of the same run
    try:
        stats_path = mlflow.artifacts.download_artifacts(
            run_id=mv.run_id, artifact_path="data_stats.json"
        )
        app.state.data_stats = json.loads(Path(stats_path).read_text(encoding="utf-8"))
        log.info("Loaded data_stats.json for run %s", mv.run_id)
    except Exception as exc:
        log.warning("Could not load data_stats.json: %s", exc)
        app.state.data_stats = {}

    app.state.delay = float(os.environ.get("FORECAST_DELAY_SEC", "0"))
    log.info("Model ready: version=%s", app.state.model_version)
    yield


app = FastAPI(title="Forecast API (internal)", version="0.4.0", lifespan=lifespan)


@app.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "model_version": request.app.state.model_version,
        "model_name": MODEL_NAME,
        "model_alias": MODEL_ALIAS,
    }


@app.get("/model/data-stats")
def data_stats(request: Request):
    stats = getattr(request.app.state, "data_stats", None)
    if not stats:
        raise HTTPException(status_code=404, detail="data_stats not available for the current model")
    return stats


@app.get("/model/info")
def model_info(request: Request):
    return {
        "model_version": request.app.state.model_version,
        "model_name": MODEL_NAME,
        "model_alias": MODEL_ALIAS,
        "features": ["area_sqm", "bedrooms", "bathrooms", "year_built", "district", "condition"],
    }


@app.post("/predict", response_model=PredictResponse)
async def predict(payload: PredictRequest, request: Request):
    if request.app.state.delay > 0:
        await asyncio.sleep(request.app.state.delay)

    import pandas as pd

    row = pd.DataFrame(
        [
            {
                "area_sqm": payload.area_sqm,
                "bedrooms": payload.bedrooms,
                "bathrooms": payload.bathrooms,
                "year_built": payload.year_built,
                "district": payload.district,
                "condition": payload.condition,
            }
        ]
    )
    pred = request.app.state.model.predict(row)
    price = float(pred[0]) if hasattr(pred, "__len__") else float(pred)
    return PredictResponse(
        predicted_price=round(price, 2),
        model_version=request.app.state.model_version,
    )

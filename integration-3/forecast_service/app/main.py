import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field

from .model import TrainedModel, predict_price, train_model

log = logging.getLogger("uvicorn.error")


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_sqm: float = Field(gt=0, le=5000)
    bedrooms: int = Field(ge=0, le=20)
    bathrooms: int = Field(ge=0, le=20)
    year_built: int = Field(ge=1800, le=2100)


class PredictResponse(BaseModel):
    predicted_price: float
    model_version: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    version = os.environ.get("MODEL_VERSION", "v1")
    app.state.model = train_model(version=version)
    # Artificial latency (seconds) so that sequential vs concurrent calls are measurable
    # in Practice 3 experiments. 0 = no delay.
    app.state.delay = float(os.environ.get("FORECAST_DELAY_SEC", "0"))
    log.info("Model %s trained: %s", version, app.state.model.metrics)
    yield


app = FastAPI(title="Forecast API (internal)", version="0.3.0", lifespan=lifespan)


def _model(request: Request) -> TrainedModel:
    return request.app.state.model


@app.get("/health")
def health(request: Request):
    return {"status": "ok", "model_version": _model(request).version}


@app.get("/model/info")
def model_info(request: Request):
    model = _model(request)
    return {"model_version": model.version, "features": ["area_sqm", "bedrooms", "bathrooms", "year_built"], "metrics": model.metrics}


@app.post("/predict", response_model=PredictResponse)
async def predict(payload: PredictRequest, request: Request):
    # async def: the delay does not occupy a worker thread, so many requests wait concurrently.
    if request.app.state.delay > 0:
        await asyncio.sleep(request.app.state.delay)
    model = _model(request)
    price = predict_price(
        model,
        payload.area_sqm,
        payload.bedrooms,
        payload.bathrooms,
        payload.year_built,
    )
    return PredictResponse(predicted_price=price, model_version=model.version)

"""Entry point for the forecasting service (forecast-api)."""
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import joblib
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI

from .model import CAT, NUM, train_model
from .schemas import PredictRequest, PredictResponse

# Used for local runs outside Docker. In the container, orchestrator
# environment variables are already present, and load_dotenv() does not
# override existing environment variables.
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("forecast-api")

MODEL_PATH = Path(os.getenv("MODEL_PATH", "/app/artifacts/model.pkl"))
MODEL_VERSION = os.getenv("MODEL_VERSION", "v0.1.0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the model once at startup instead of loading it per request."""
    if MODEL_PATH.exists():
        app.state.model = joblib.load(MODEL_PATH)
        logger.info("Model loaded from %s", MODEL_PATH)
    else:
        # Development fallback for running without a pre-built image.
        # In production, the model artifact is required.
        logger.warning("Artifact not found - training at startup (dev-only)")
        app.state.model = train_model()

    yield

    app.state.model = None


app = FastAPI(
    title="Forecast API",
    version=MODEL_VERSION,
    lifespan=lifespan,
)


@app.get("/health")
def health():
    """Health check endpoint used by the orchestrator."""
    return {
        "status": "ok",
        "model_version": MODEL_VERSION,
    }


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    """Predict a house sale price from the provided Ames Housing features.

    This is a regular synchronous endpoint rather than ``async def``.
    FastAPI executes synchronous endpoints in a thread pool, preventing
    CPU-bound inference from blocking the event loop.
    """
    t0 = time.perf_counter()

    # Wire contract -> exact Ames dataset column names.
    df = pd.DataFrame([{
        "GrLivArea": req.gr_liv_area,
        "TotalBsmtSF": req.total_bsmt_sf,
        "GarageArea": req.garage_area,
        "YearBuilt": req.year_built,
        "OverallQual": req.overall_qual,
        "MSZoning": req.ms_zoning,
    }])

    price = float(app.state.model.predict(df[NUM + CAT])[0])
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    logger.info(
        "predict: %.2f USD (%.2f ms)",
        price,
        latency_ms,
    )

    return PredictResponse(
        predicted_price=price,
        model_version=MODEL_VERSION,
        latency_ms=latency_ms,
    )

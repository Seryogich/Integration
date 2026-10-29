"""Pydantic schemas for the forecasting API."""

from pydantic import BaseModel, Field


class PredictRequest(BaseModel):
    """Input features required to predict a house sale price."""

    gr_liv_area: float = Field(
        gt=0,
        le=10_000,
        description="Above-ground living area in square feet (Ames: Gr Liv Area).",
    )

    total_bsmt_sf: float = Field(
        ge=0,
        le=10_000,
        description="Total basement area in square feet (Ames: Total Bsmt SF).",
    )

    garage_area: float = Field(
        ge=0,
        le=2_000,
        description="Garage area in square feet (Ames: Garage Area).",
    )

    year_built: int = Field(
        ge=1872,
        le=2010,
        description="Original construction year (Ames: Year Built).",
    )

    overall_qual: int = Field(
        ge=1,
        le=10,
        description=(
            "Overall material and finish quality, "
            "rated from 1 to 10 (Ames: Overall Qual)."
        ),
    )

    ms_zoning: str = Field(
        min_length=1,
        max_length=10,
        description="General zoning classification (Ames: MS Zoning).",
    )


class PredictResponse(BaseModel):
    """Response containing the predicted price and model metadata."""

    predicted_price: float
    currency: str = "USD"
    model_version: str
    latency_ms: float

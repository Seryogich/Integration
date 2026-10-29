from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Public liveness probe (R2.7): carries no sensitive information."""
    return {"status": "ok"}

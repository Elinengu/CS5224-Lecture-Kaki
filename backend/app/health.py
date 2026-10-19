"""Process health, independent of authentication and external services."""

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

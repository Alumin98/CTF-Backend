from fastapi import APIRouter

from app.services.container_service import get_container_service

router = APIRouter(prefix="/runner", tags=["Runner"])


@router.get("/health")
async def runner_health() -> dict:
    service = get_container_service()
    return await service.runner_health()

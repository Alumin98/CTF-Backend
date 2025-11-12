from fastapi import APIRouter

from app.services.container_service import runner_health

router = APIRouter(tags=["Health"])


@router.get("/runner/health")
async def runner_health_check():
    return await runner_health()

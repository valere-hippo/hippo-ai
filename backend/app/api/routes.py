from fastapi import APIRouter

from app.api import auth, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)


@api_router.get("/info", tags=["system"])
async def info() -> dict[str, str]:
    return {
        "name": "HIPPO-AI",
        "version": "0.1.0",
        "phase": "1.1-authentication",
    }

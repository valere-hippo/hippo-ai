from fastapi import APIRouter

from app.api import auth, users, admin_users, project_folders, projects, chat, files, permissions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(admin_users.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(project_folders.router)
api_router.include_router(chat.router)
api_router.include_router(files.router)
api_router.include_router(permissions.router)


@api_router.get("/info", tags=["system"])
async def info() -> dict[str, str]:
    return {
        "name": "HIPPO-AI",
        "version": "0.2.0",
        "phase": "2-desktop",
    }

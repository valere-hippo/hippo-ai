from fastapi import APIRouter

from app.api import auth, users, admin_users, project_folders, projects, chat, files, permissions, audio, embeddings, search

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(admin_users.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(project_folders.router)
try:
    from app.api import skills
    api_router.include_router(skills.router)
    api_router.include_router(skills.library_router)
except Exception:
    pass
api_router.include_router(chat.router)
api_router.include_router(files.router)
api_router.include_router(permissions.router)
# Add additional routers
api_router.include_router(audio.router)
try:
    from app.api import admin_overview
    api_router.include_router(admin_overview.router)
except Exception:
    pass
# keep legacy embeddings endpoints and also add library endpoints that store in the backend DB
try:
    from app.api import embeddings_proxy
    api_router.include_router(embeddings_proxy.router)
except Exception:
    pass
api_router.include_router(embeddings.router)
try:
    api_router.include_router(embeddings.library_router)
except Exception:
    pass
api_router.include_router(search.router)
# enhanced chat that consults embeddings first
try:
    from app.api import chat_enhanced
    api_router.include_router(chat_enhanced.router)
except Exception:
    pass


@api_router.get("/info", tags=["system"])
async def info() -> dict[str, str]:
    return {
        "name": "HIPPO-AI",
        "version": "0.2.0",
        "phase": "2-desktop",
    }

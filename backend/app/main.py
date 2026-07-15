from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.domains.auth.router import router as auth_router
from app.domains.competitions.router import router as competitions_router
from app.domains.hierarchy.router import router as team_router
from app.domains.inventory.router import router as inventory_router
from app.domains.notifications.router import router as notifications_router
from app.domains.positions.router import router as positions_router
from app.domains.requests.router import router as requests_router
from app.domains.tasks.router import router as tasks_router
from app.domains.users.router import router as users_router

app = FastAPI(title="Organization Operations Portal", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Future modules (finance) mount here as sibling domain routers sharing auth,
# users and the hierarchy permission layer.
for domain_router in (
    auth_router,
    users_router,
    tasks_router,
    requests_router,
    team_router,
    notifications_router,
    inventory_router,
    competitions_router,
    positions_router,
):
    app.include_router(domain_router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

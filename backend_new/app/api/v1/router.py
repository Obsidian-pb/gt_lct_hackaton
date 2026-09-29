from fastapi import APIRouter

from app.api.v1 import (
    ai,
    auth,
    cards,
    catalog,
    materials,
    reference,
    reports,
    runtime,
    scenarios,
    system,
    tasks,
    trainings,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(reference.scenario_status_router)
api_router.include_router(reference.applicant_status_router)
api_router.include_router(reference.training_role_router)
api_router.include_router(catalog.router, prefix="")
api_router.include_router(tasks.router)
api_router.include_router(ai.router)
api_router.include_router(scenarios.router)
api_router.include_router(trainings.router)
api_router.include_router(runtime.router)
api_router.include_router(cards.router)
api_router.include_router(reports.router)
api_router.include_router(materials.router)
api_router.include_router(system.router)
"""Точка входа ИИ-микросервиса.

Запуск: uvicorn app.main:app --host 127.0.0.1 --port 8890.
Доступ к операциям (/api/v1) — только с Bearer AI_SERVICE_TOKEN.
/health, /api/docs и OpenAPI открыты для диагностики.
"""
from __future__ import annotations

import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Stateless ИИ-микросервис тренажёра «Система-112»: генерация карточек, "
        "превью эталона, реплики заявителя и службы ДДС, валидация полей, "
        "предварительная оценка ИИ. Ключ провайдера хранится только здесь."
    ),
    docs_url="/api/docs",
    openapi_url="/api/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", summary="Живучесть сервиса без вызова ИИ")
async def root_health() -> dict:
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}


# Пути, доступные без токена (диагностика и документация).
PUBLIC_PATHS = {"/health", "/api/docs", "/api/v1/openapi.json", "/openapi.json"}


@app.middleware("http")
async def require_token(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    expected = settings.ai_service_token
    if not expected or expected == "change-me-ai-service-token":
        return JSONResponse(
            status_code=503,
            content={"detail": "AI_SERVICE_TOKEN не настроен: задайте его в .env микросервиса."},
        )
    auth = request.headers.get("Authorization", "")
    if not secrets.compare_digest(auth, f"Bearer {expected}"):
        return JSONResponse(
            status_code=401,
            content={"detail": "Неверный токен доступа ИИ-сервиса."},
        )
    return await call_next(request)


app.include_router(router, prefix="/api/v1")
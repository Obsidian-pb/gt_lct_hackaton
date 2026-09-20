from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, attempts, auth, operator, student, teacher
from app.core.config import get_settings
from app.services.ekp import get_ekp

app = FastAPI(
    title="Тренажёр оператора ДДС",
    description=(
        "Учебное программное обеспечение для подготовки операторов "
        "дежурно-диспетчерских служб города Москвы."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # Сервер разработки Vite. Два написания одного адреса: для браузера
    # это разные источники, и открытый по 127.0.0.1 стенд иначе молчит.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(attempts.router)
app.include_router(teacher.router)
app.include_router(operator.router)
app.include_router(student.router)
app.include_router(admin.router)


@app.get("/api/health", tags=["Служебные"])
def health() -> dict:
    """Состояние компонентов — используется мониторингом учебного комплекса."""
    settings = get_settings()
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "ekp_rules": len(get_ekp()),
        "response_deadline_seconds": settings.default_response_deadline_seconds,
    }

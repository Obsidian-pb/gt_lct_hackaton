import logging
import traceback
from pathlib import Path

import jwt
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api import admin, attempts, auth, materials, operator, student, teacher
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import decode_access_token
from app.models.audit import ErrorEvent
from app.services.ekp import get_ekp

logger = logging.getLogger(__name__)

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
app.include_router(materials.router)


# Пределы на длину сохраняемого текста. Трассировка обычного отказа занимает
# две-три тысячи знаков, и восемь тысяч покрывают её целиком; при этом
# зацикленный вызов даёт трассировку в мегабайты, и без предела десяток таких
# сбоев раздул бы таблицу и страницу состояния. Отрезается начало, а не конец:
# место, где отказ произошёл, и текст исключения стоят в трассировке последними.
MAX_TRACEBACK_CHARS = 8000
MAX_MESSAGE_CHARS = 2000


def _actor_login(request: Request) -> str | None:
    """Логин из предъявленного токена, без обращения к базе.

    База в момент сбоя может быть как раз тем, что отказало, поэтому имя
    берётся из самого токена. Сверять его с учётной записью незачем: подпись
    токена уже проверена, а в отчёте о сбоях нужен не субъект прав, а подсказка,
    у кого именно перестало работать.
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        return str(decode_access_token(header.split(" ", 1)[1]).get("sub") or "")[:150] or None
    except (jwt.PyJWTError, IndexError):
        return None


def _record_error(request: Request, exc: Exception) -> None:
    """Складывает сбой в таблицу сбоев, ничего не требуя от вызывающего кода.

    Сохраняются только путь, метод, тип и текст исключения: ни тела запроса,
    ни строки запроса здесь нет намеренно — в них попадает работа
    обучающегося, а её администратору видеть нельзя (ТЗ ограничивает его
    доступ к персональным данным).
    """
    with SessionLocal() as db:
        db.add(
            ErrorEvent(
                path=request.url.path[:255],
                method=request.method[:10],
                kind=type(exc).__name__[:128],
                message=str(exc)[:MAX_MESSAGE_CHARS],
                # Трассировка собирается из самого исключения, а не из
                # format_exc(): обработчик выполняется в рабочем потоке, где
                # «текущего исключения» уже нет и format_exc() вернул бы пусто.
                traceback="".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )[-MAX_TRACEBACK_CHARS:],
                actor_login=_actor_login(request),
            )
        )
        db.commit()


@app.exception_handler(Exception)
def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Единая обработка необработанных исключений.

    Нужна потому, что администратор учебного комплекса не видит ни журналов
    контейнеров, ни командной строки: без записи в базу сбой для него просто
    не существует, а ТЗ требует от него «формировать отчёты об ошибках
    и сбоях».

    Сама запись обёрнута: отказавшая база — это ровно тот случай, когда
    исключения и полетят, и попытка записать сбой упадёт следом. Ошибка
    обработчика ошибок не должна подменять собой исходный сбой и тем более
    оставлять пользователя без ответа.
    """
    logger.error(
        "Необработанная ошибка на %s %s",
        request.method,
        request.url.path,
        # exc_info передаётся явно по той же причине, что и трассировка
        # в _record_error: в рабочем потоке «текущего исключения» нет.
        exc_info=exc,
    )
    try:
        _record_error(request, exc)
    except Exception as write_failure:  # noqa: BLE001 — запись сбоя не вправе ронять ответ
        logger.warning("Сбой не удалось записать в базу: %s", write_failure)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Внутренняя ошибка комплекса. "
            "Сбой записан, сообщите администратору."
        },
    )


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


def _mount_static(static_dir: Path) -> None:
    """Раздача собранного фронтенда самим приложением.

    Нужна переносному комплекту для Windows: там нет nginx, и один процесс
    обслуживает и API, и страницы. Маршруты интерфейса — `/calls/5`,
    `/report/3` — существуют только в браузере, поэтому любой путь вне
    `/api`, которому не соответствует файл, отдаёт `index.html`: иначе
    обновление страницы на любом экране, кроме первого, давало бы 404.
    Объявляется последним, чтобы не перехватить маршруты API.
    """
    index = static_dir / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        candidate = (static_dir / path).resolve()
        # Путь обязан остаться внутри каталога: `..` в адресе не должен
        # выводить за его пределы.
        if candidate.is_file() and static_dir in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


if get_settings().static_dir:
    _mount_static(get_settings().static_dir.resolve())

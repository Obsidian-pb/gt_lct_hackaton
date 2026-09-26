# backend_new — REST API тренажёра оператора ДДС

Бэкенд учебного тренажёра операторов ДДС «Система-112» по техническому заданию
[`../tz_for_work.qmd`](../tz_for_work.qmd).

Стек: **FastAPI**, **SQLAlchemy 2.0 (async)**, **Alembic**, **PostgreSQL 15+**, JWT + bcrypt.

Проектный документ (архитектура, схема БД, карта API): [`../plans/backend_new_plan.md`](../plans/backend_new_plan.md).

## Структура

```
app/
├── api/          # FastAPI роутеры (v1)
├── core/         # конфигурация, безопасность, логирование
├── db/           # движок, сессии, Base и mixins
├── models/       # SQLAlchemy-модели (auth, catalog, reference, content, training, ...)
├── repositories/ # доступ к данным, маппинг БД -> домен
├── schemas/      # Pydantic DTO — контракт API
└── services/     # бизнес-логика
alembic/          # миграции БД
```

## Быстрый старт

### Вариант 1: Docker Compose

```bash
docker compose up -d db
docker compose exec backend alembic upgrade head
docker compose up -d backend
# документация API: http://localhost:8000/docs
```

### Вариант 2: локально

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env        # Windows
docker compose up -d db       # или использовать свой PostgreSQL
alembic upgrade head
uvicorn app.main:app --reload
```

## Конфигурация

Настройки читаются из переменных окружения (см. `.env.example`):

| Переменная | Описание |
|---|---|
| `DATABASE_URL` | строка подключения asyncpg к PostgreSQL |
| `JWT_SECRET_KEY` | секрет подписи JWT |
| `JWT_ALGORITHM` | алгоритм подписи (HS256) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | срок жизни access-токена |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | срок жизни refresh-токена |
| `CORS_ORIGINS` | JSON-список разрешённых источников |

## Политика миграций

- Применённые миграции **не редактируются**; новые изменения — только новые файлы в `alembic/versions/`.
- Изменения должны быть **аддитивными**: новые nullable-колонки, новые таблицы.
- Деструктивные изменения — только по схеме **expand–contract** (добавить → бэкфилл → NOT NULL → удалить позже).
- Изменение состава полей Карточки/Эталона — правка Pydantic-схемы, без DDL.

```bash
alembic revision --autogenerate -m "описание изменения"
alembic upgrade head
```

## Тесты

```bash
pytest
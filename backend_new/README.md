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

#### Настройка PostgreSQL

```{sql}
CREATE ROLE system112 LOGIN PASSWORD 'system112';
CREATE DATABASE system112_trainer OWNER system112;
```


#### Настройка окружения

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

## Карта API v1 (62 маршрута)

| Группа | Маршруты |
|---|---|
| auth | `POST /api/v1/auth/login`, `POST /auth/refresh`, `GET /auth/me` |
| users | `GET/POST /api/v1/users`, `GET/PATCH/DELETE /users/{id}`, `PUT /users/{id}/roles`, `GET /users/roles` |
| reference | `/scenario-statuses`, `/applicant-statuses`, `/training-roles` (CRUD) |
| catalog | `/services`, `/classifier/event-types`, `/classifier/features-1..3`, `/classifier/versions`, `/event-groups` |
| study-tasks | `GET/POST /study-tasks`, `GET/PATCH/DELETE /study-tasks/{id}`, `POST /study-tasks/{id}/approve`, `POST /study-tasks/{id}/generate` (ИИ-заглушка 501) |
| scenarios | `GET/POST /scenarios`, `GET/PATCH/DELETE /scenarios/{id}`, `POST /scenarios/{id}/approve`, `POST/DELETE /scenarios/{id}/tasks...` |
| trainings | `GET/POST /trainings`, `GET/PATCH/DELETE /trainings/{id}`, `POST /trainings/{id}/activate|finish`, `POST/DELETE /trainings/{id}/participants...`, `GET /trainings/{id}/progress` |
| runtime | `POST /sessions/start`, `POST /sessions/{id}/finish`, `GET /sessions/{id}/next-task`, `POST /sessions/{id}/accept-call`, `PATCH /cards/{id}/content`, `POST /cards/{id}/submit` |
| dispatcher (окно 36) | `GET /dispatcher/cards`, `POST /cards/{id}/accept|route|process` |
| cards | `GET /cards`, `GET /cards/{id}`, `POST /cards/{id}/grade` |
| reports | `GET /reports/summary`, `GET /reports/training/{id}`, `GET /reports/export.csv` |
| materials | `GET/POST /materials`, `GET /materials/{id}/download`, `DELETE /materials/{id}` |
| system | `GET /system/health`, `GET /system/settings`, `PUT /system/settings/{key}`, `GET /audit` |

Все маршруты, кроме `POST /auth/login`, требуют JWT (HTTP Bearer). Доступ по ролям:
`system_admin` — системные настройки и аудит; `admin`/`teacher` — учебный контент;
`student` — чтение и прохождение назначенных тренировок.

## Тесты

```bash
pytest                              # контрактные тесты OpenAPI + целостность моделей
.venv\Scripts\python.exe scripts\smoke_auth.py       # авторизация и пользователи
.venv\Scripts\python.exe scripts\smoke_reference.py  # справочники и классификатор
.venv\Scripts\python.exe scripts\smoke_content.py    # задачи и сценарии
.venv\Scripts\python.exe scripts\smoke_training.py   # полный учебный цикл (сценар. 3-4 ТЗ)
.venv\Scripts\python.exe scripts\smoke_system.py     # отчёты, материалы, настройки, аудит
```

Администратор по умолчанию: `admin` / `admin123` (создаётся при старте в dev-режиме).
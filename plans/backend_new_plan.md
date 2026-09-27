# План: `backend_new` — база данных и REST API тренажёра оператора ДДС

## 1. Зафиксированные решения

- Схема БД перепроектируется **с нуля строго по терминологии ТЗ**: Учебная задача, Учебный сценарий, Тренировка, Карточка происшествия, Обучающийся, Роли обучающихся.
- Из старого [`database/`](../database/README.md) переносятся только две схемы:
  - `auth` — пользователи, роли, права, RBAC;
  - `catalog` — классификатор происшествий (Группы, Признаки 1–3, классы событий, номера), службы, версии классификатора.
- Новый проект размещается в **`backend_new/`**. Существующие `database/` и прочие наработки **не изменяются**.
- Стек: Python 3.11+, **FastAPI** (async), **SQLAlchemy 2.0** (async, asyncpg), **Alembic**, **Pydantic v2**, PostgreSQL 15+, аутентификация **JWT + bcrypt**, тесты **pytest + httpx**, оркестрация локального окружения **Docker Compose**.
- Обмен с фронтендом — **REST JSON**, все маршруты под префиксом `/api/v1`, интерактивная документация OpenAPI на `/docs`.

## 2. Ключевой принцип: схема БД не является контрактом API

Чтобы изменения базы не ломали бэкенд и фронтенд, вводится жёсткое расслоение:

```{mermaid}
flowchart LR
    FE[Фронтенд] -->|REST JSON /api/v1| API[FastAPI роутеры и Pydantic-схемы контракта]
    API --> SVC[Сервисный слой бизнес-логики]
    SVC --> REP[Репозитории и мапперы]
    REP --> ORM[SQLAlchemy-модели]
    ORM --> PG[(PostgreSQL)]
```

Механизмы защиты:

1. **Контракт = Pydantic-схемы** в `app/schemas/`. Они независимы от ORM-моделей. Репозитории транслируют форму БД в доменные объекты. Переименование колонки затрагивает только модель и репозиторий; эндпоинт и фронтенд не меняются.
2. **JSONB для изменчивого содержимого.** Содержимое Карточки происшествия и Эталона, дополнительные поля групп происшествий, служебные снимки — в `JSONB` с валидацией на уровне Pydantic. Добавление поля в карточку = правка Pydantic-схемы (и при необходимости миграция данных в JSONB), **без ALTER TABLE**.
3. **Alembic: только аддитивные миграции.** Применённые миграции не редактируются, новые — только добавляются. Деструктивные изменения — по схеме **expand–contract**: добавить nullable-колонку → бэкфилл → `NOT NULL` → удалить старую колонку позже.
4. **Версионирование API.** Ломающие изменения — в новую версию (`/api/v2`), старая живёт, пока фронтенд не мигрирует.
5. **Контрактные тесты.** pytest проверяет точную форму ответа каждого эндпоинта; рефакторинг БД, «протёкший» в API, падает на CI.

## 3. Структура проекта `backend_new/`

```
backend_new/
├── pyproject.toml            # зависимости и метаданные пакета
├── alembic.ini
├── alembic/
│   ├── env.py                # async-движок, автоопределение схем
│   └── versions/             # 0001_auth_catalog ... 000N_...
├── docker-compose.yml        # postgres + backend (локальная разработка)
├── .env.example              # DATABASE_URL, SECRET_KEY и пр.
├── README.md
├── app/
│   ├── main.py               # фабрика FastAPI, CORS, /health
│   ├── core/
│   │   ├── config.py         # pydantic-settings
│   │   ├── security.py       # JWT, bcrypt, пароли
│   │   └── logging.py
│   ├── db/
│   │   ├── session.py        # async engine + sessionmaker
│   │   └── base.py           # Base, naming convention, mixins
│   ├── models/               # SQLAlchemy: auth, catalog, reference,
│   │                         #          content, training, audit, system
│   ├── schemas/              # Pydantic DTO — КОНТРАКТ API
│   ├── repositories/         # доступ к данным, маппинг БД -> домен
│   ├── services/             # бизнес-логика
│   └── api/
│       ├── deps.py           # get_db, get_current_user, require_role
│       └── v1/               # роутеры по доменам ТЗ
└── tests/                    # контрактные и регрессионные тесты
```

## 4. Целевая схема БД (терминология ТЗ)

PostgreSQL-схемы: `auth`, `catalog`, `reference`, `content`, `training`, `audit`, `system`.

### `auth` — пользователи и доступ (перенос из старой БД)

- `users` — `username`, `email`, `password_hash`, **`last_name`, `first_name`, `middle_name`, `phone`** (по карточке пользователя ТЗ 13), `is_active`, мягкое удаление (`deleted_at`, `purge_after`);
- `roles` — код, наименование; системные роли: `system_admin`, `admin`, `teacher`, `student`;
- `permissions`, `user_roles`, `role_permissions` — RBAC.

### `catalog` — классификатор и службы (перенос из старой БД)

- `event_types` (код Г), `event_features_1`, `event_features_2`, `event_features_3` (Признаки 1–3);
- `event_classes` — допустимые комбинации, автоматический `event_number`, главная служба;
- **`event_class_extra_fields`** — дополнительные поля группы происшествий (ТЗ 29): имя, тип, обязательность, список значений;
- `services` — справочник служб (ТЗ 34);
- `classifier_versions`, `classifier_version_events` — версии классификатора для фиксации на сессии.

### `reference` — справочники (новое)

- `scenario_statuses` — статусы сценариев (ТЗ 31);
- `applicant_statuses` — статусы заявителей (ТЗ 32);
- `training_roles` — роли обучающихся (ТЗ 35): `operator_112`, `dispatcher_dds`, `service_dispatcher` (для последней роль действует со ссылкой на службу в назначении).

### `content` — учебный контент (новое)

- `study_tasks` — **Учебная задача** (ТЗ 8):
  - сложность `smallint` 1..5;
  - диспозиция: сообщение заявителя, три телефона (АОН/предоставленный/на место), ФИО заявителя, `applicant_status_id`, описание со слов заявителя, булевы флаги (пострадавшие, нет на месте/отказ скорой, нет доступа, нет контакта, срыв звонка);
  - адрес: страна, субъект, населённый пункт, объект, округ, район, улица, дом, корпус, строение, квартира, подъезд, этаж, код, описательный адрес, широта/долгота;
  - классификация: `event_class_id`, дополнительные поля группы — `JSONB`;
  - `main_service_id`, привлекаемые службы — связь `study_task_services`;
  - автор/утвердивший (`created_by`, `approved_by`, `approved_at`), статус утверждения;
- `task_etalons` — **Эталон** (1:1 с задачей): образец заполненной карточки, `content JSONB` + `field_schema JSONB`;
- `scenarios` — **Учебный сценарий** (ТЗ 6): тема, описание, `scenario_status_id`, автор/утвердивший, даты;
- `scenario_tasks` — связь сценарий ↔ учебная задача (с порядком);
- `study_materials` — методические материалы (ТЗ 18): заголовок, описание, файл, тип.

### `training` — учебный процесс (новое)

- `trainings` — **Тренировка** (ТЗ 11): название, описание, даты начала/окончания, сложность (`low|medium|high|adaptive`), режим (`training|testing`), состояние (`prepared|active|finished`), лимит времени на карточку (норматив, по умолчанию 30 с), автор;
- `training_scenarios` — сценарии тренировки;
- `training_participants` — назначенные обучающиеся с ролями: `user_id`, `training_role_id`, `service_id` (для «Диспетчер службы»);
- `training_sessions` — фактическое прохождение обучающимся тренировки: начало/конец, статус;
- `incident_cards` — **Карточка происшествия** (ТЗ 14):
  - ссылки: `session_id`, `study_task_id`, `sequence_number`;
  - `content JSONB` — заполненные поля (структура как у карточки);
  - типизированные метаданные для фильтров/отчётов: `event_class_id`, `main_service_id`, привлекаемые службы (`card_services`);
  - статус жизненного цикла: `draft → submitted → accepted → routed → processed`;
  - оценки: `machine_score`, `ai_score`, `final_score` (0–100), `evaluated_by`, `evaluated_at`, детали машинного сравнения `machine_eval_details JSONB`;
  - тайминги: `created_at`, `submitted_at`, `accepted_at`, `routed_at`, `processed_at`, `duration_ms`;
- `card_services` — привлекаемые службы карточки.

### `audit` и `system`

- `audit_log` — действия пользователей, срок хранения 6 месяцев;
- `system_settings` — key-value (JSONB): параметры ИИ (ТЗ 30), настройки БД/резервирования (ТЗ 20), журналирования (ТЗ 23) — для админ-окон.

### Диаграмма связей

```{mermaid}
erDiagram
    users ||--o{ user_roles : ""
    roles ||--o{ user_roles : ""
    roles ||--o{ role_permissions : ""
    permissions ||--o{ role_permissions : ""

    event_types ||--o{ event_features_1 : ""
    event_features_1 ||--o{ event_features_2 : ""
    event_features_2 ||--o{ event_features_3 : ""
    event_types ||--o{ event_classes : ""
    event_features_1 ||--o{ event_classes : ""
    event_features_2 ||--o{ event_classes : ""
    event_features_3 ||--o{ event_classes : ""
    event_classes ||--o{ event_class_extra_fields : ""
    event_classes ||--o{ event_class_services : ""
    services ||--o{ event_class_services : ""
    classifier_versions ||--o{ classifier_version_events : ""
    event_classes ||--o{ classifier_version_events : ""

    applicant_statuses ||--o{ study_tasks : ""
    event_classes ||--o{ study_tasks : ""
    users ||--o{ study_tasks : "создаёт"
    study_tasks ||--o| task_etalons : "эталон"
    study_tasks ||--o{ study_task_services : ""
    services ||--o{ study_task_services : ""

    scenario_statuses ||--o{ scenarios : ""
    users ||--o{ scenarios : "создаёт"
    scenarios ||--o{ scenario_tasks : ""
    study_tasks ||--o{ scenario_tasks : ""

    trainings ||--o{ training_scenarios : ""
    scenarios ||--o{ training_scenarios : ""
    trainings ||--o{ training_participants : ""
    users ||--o{ training_participants : ""
    training_roles ||--o{ training_participants : ""
    services ||--o{ training_participants : "для диспетчера службы"

    trainings ||--o{ training_sessions : ""
    users ||--o{ training_sessions : ""
    training_sessions ||--o{ incident_cards : ""
    study_tasks ||--o{ incident_cards : ""
    event_classes ||--o{ incident_cards : ""
    incident_cards ||--o{ card_services : ""
    services ||--o{ card_services : ""
    users ||--o{ audit_log : "действия"
```

## 5. Политика миграций и эволюция схемы

- Каждое изменение — новая миграция `alembic revision --autogenerate`; применённые не редактируются.
- Аддитивные изменения (новые nullable-колонки, новые таблицы) — стандарт.
- Деструктивные — только expand–contract (см. раздел 2).
- Изменение состава полей карточки/эталона: правка Pydantic-схемы, при необходимости — миграция данных в JSONB без изменения DDL.
- Откат: `alembic downgrade` для последней миграции; история версий — в git.

## 6. Карта API v1 (по окнам ТЗ)

| Окно ТЗ | Маршруты |
|---|---|
| 1 Вход | `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `GET /api/v1/auth/me` |
| 12–13 Пользователи | `GET/POST /users`, `GET/PATCH/DELETE /users/{id}`, `POST /users/{id}/roles` |
| 28–29 Группы происшествий | `GET /classifier/event-types`, `GET /classifier/features`, `GET/POST /event-groups`, `GET/PATCH /event-groups/{id}` (+доп. поля) |
| 34 Службы | `GET/POST/PATCH/DELETE /services` |
| 31–32 Статусы | `GET/POST/PATCH/DELETE /scenario-statuses`, `/applicant-statuses` |
| 35 Роли обучающихся | `GET/POST/PATCH/DELETE /training-roles` |
| 7–8 Учебные задачи | `GET/POST /study-tasks`, `GET/PATCH/DELETE /study-tasks/{id}`, `POST /study-tasks/{id}/approve`, `POST /study-tasks/{id}/generate` (ИИ-заглушка) |
| 5–6 Сценарии | `GET/POST /scenarios`, `GET/PATCH/DELETE /scenarios/{id}`, `POST /scenarios/{id}/tasks`, `DELETE /scenarios/{id}/tasks/{task_id}`, `POST /scenarios/{id}/approve` |
| 10–11 Тренировки | `GET/POST /trainings`, `GET/PATCH/DELETE /trainings/{id}`, `POST /trainings/{id}/scenarios`, `POST /trainings/{id}/participants`, `POST /trainings/{id}/activate`, `POST /trainings/{id}/finish`, `GET /trainings/{id}/progress` |
| 17 Эмулятор | `POST /trainings/{id}/session/start`, `GET /sessions/current-task`, `POST /cards/{id}/accept-call`, `POST /cards/{id}/save`, `POST /cards/{id}/submit` |
| 36 Карточки в работе | `GET /dispatcher/cards`, `POST /cards/{id}/accept`, `POST /cards/{id}/route`, `POST /cards/{id}/process` |
| 15 Список карточек | `GET /cards`, `GET /cards/{id}`, `POST /cards/{id}/grade` |
| 16 Отчёты | `GET /reports/summary`, `GET /reports/student/{id}`, `GET /reports/training/{id}`, `GET /reports/export.csv` |
| 18 Материалы | `GET/POST/PATCH/DELETE /materials`, загрузка/скачивание файлов |
| 19–27 Система | `GET /system/health`, `GET /system/logs`, `GET/PUT /system/settings`, `GET /audit`, `POST /system/backup` |

Все маршруты, кроме `auth/login`, требуют JWT; доступ контролируется ролями (RBAC) через зависимость `require_role`.

## 7. Этапы реализации

Полный пошаговый список задач ведётся в todo-листе задачи (архитектурный режим) — от каркаса проекта и миграций до контрактных тестов и документации. Порядок:

1. Каркас `backend_new/` + Docker Compose + Alembic.
2. Модели и миграции: `auth` → `catalog` → `reference` → `content` → `training` → `audit/system`.
3. Аутентификация и RBAC.
4. API v1 по доменам: справочники → задачи → сценарии → тренировки → эмулятор → карточки → отчёты → материалы → система.
5. Контрактные тесты, документация, запуск.

## 8. Открытые вопросы и риски

- **Типизация содержимого карточки**: рекомендуется хранить содержимое карточек/эталонов в `JSONB` + Pydantic-валидация (максимальная устойчивость к изменениям). Альтернатива — типизированные колонки по каждому полю ТЗ. Требуется согласование.
- **Оценка ИИ** (`ai_score`) и генерация задач — интеграция с готовым модулем из папки «ИИ для проекта (2)/»; на первом этапе — заглушки и ручной ввод.
- **Адрес (ТЗ 33)** — отдельный справочник не делаем; адрес входит в состав задачи и карточки, данные поступают из встроенной карты.
- **Эмуляция звонков (SIP/VoIP)** — Пока реализуем только вывод текстового сообщения. Конкретная реализация будет добавлена только после того, как API эмулятора будет опубликована и протестирована.
- **Прогресс в реальном времени** (окно 11) — вычисляемые агрегаты по `incident_cards`, отдельная таблица не нужна; при необходимости — WebSocket/SSE позже.
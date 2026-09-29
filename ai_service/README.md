# ИИ-микросервис тренажёра «Система-112»

Stateless REST-сервис ИИ-операций, вынесенный из backend_new по решению
[`plans/plan3_ai_microservice.md`](../plans/plan3_ai_microservice.md).
Логика соответствует standalone-проекту «ИИ для проекта (2)»: ключ провайдера
хранится только на сервере, доступ к операциям — по Bearer-токену, состояние
диалогов и карточек хранит вызывающий сервис (backend_new).

## Запуск

```bash
cd ai_service
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e ".[dev]"
copy .env.example .env            # задайте AI_SERVICE_TOKEN и ключ провайдера
uvicorn app.main:app --host 127.0.0.1 --port 8890
```

Документация: http://127.0.0.1:8890/api/docs (открыта без токена).

## Контракт (базовый адрес http://127.0.0.1:8890/api/v1)

Все операции stateless; входные данные — в теле JSON. Заголовок
`Authorization: Bearer <AI_SERVICE_TOKEN>` обязателен (кроме `/health`,
`/api/docs`, OpenAPI).

| Метод | Путь | Функция ядра | Назначение |
|---|---|---|---|
| GET | `/health` | — | Живучесть сервиса, без вызова ИИ |
| GET | `/metadata` | `card_factory.metadata()` | Группы, каталог, поля карточки |
| POST | `/ai/checks` | `get_provider().status()` | Проверка доступности ИИ без генерации |
| POST | `/cards/generations` | `card_factory.generate()` | Генерация содержимого карточки |
| POST | `/cards/reference-previews` | `card_reference.generate()` | Превью эталона |
| POST | `/cards/caller-replies` | `card_caller.ask()` | Реплика заявителя |
| POST | `/cards/service-replies` | `dds.service_reply()` | Реплика службы ДДС с помехами канала |
| POST | `/cards/validations` | `card_factory.validate_content()` | Локальная валидация content |
| POST | `/assessments` | `ai_core.assess_card()` | Предварительная оценка ИИ |

Ошибки: `401` — нет/неверный токен; `413/422` — невалидный запрос;
`502` — ошибка внешнего ИИ-провайдера; `503` — не настроен ключ/токен.

## Структура

```
app/
├── main.py            # FastAPI: Bearer-токен, CORS, документация
├── core/config.py     # настройки: AI_SERVICE_TOKEN + настройки провайдера
├── api/routes.py      # stateless REST-операции
├── schemas/ai.py      # Pydantic-контракт
└── services/ai/       # ядро: provider, ai_core, card_factory, card_caller,
                       # card_reference, dds, schemas + catalog/ и certs/
```

## Проверка работоспособности

### 1. Unit-тесты (без сети и ключа)

```bash
.venv\Scripts\python.exe -m pytest -v
```

Ожидается `28 passed`.

### 2. Запуск и контракт API

```bash
copy .env.example .env        # задайте AI_SERVICE_TOKEN и ключ провайдера
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8890
```

Генерация AI_SERVICE_TOKEN:
```bash
[guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
```

В другом окне:

```bash
python scripts/smoke_api.py http://127.0.0.1:8890 <AI_SERVICE_TOKEN>
```

Скрипт проверяет `/health`, 401 без токена, `/metadata`, валидацию (422)
и `/ai/checks` (200 при настроенном ключе; 502/503 — если ключ не задан
или провайдер недоступен).

### 3. Реальная генерация ИИ (нужны ключ и квота)

```bash
python scripts/smoke_api.py http://127.0.0.1:8890 <AI_SERVICE_TOKEN> --live
```

Выполнит генерацию карточки и диалог заявителя; результаты не сохраняются.

### 4. Документация (Swagger UI)

http://127.0.0.1:8890/api/docs — доступна без токена, все операции можно
выполнять прямо из браузера, указав токен в кнопке Authorize.

### 5. Сквозная проверка с backend_new

Запустите `ai_service` и backend_new, затем из `backend_new/`:

```bash
.venv\Scripts\python.exe scripts\smoke_ai_endpoints.py
```

и при работающем ключе — полный учебный цикл с ИИ:
```bash
.venv\Scripts\python.exe scripts\smoke_ai_classified.py
```

## Интеграция с backend_new

- backend_new: `AI_SERVICE_URL=http://127.0.0.1:8890`, `AI_SERVICE_TOKEN=<тот же>`.
- Порядок запуска: сначала `ai_service`, затем backend_new.
- Docker: сервис `ai_service` добавлен в `backend_new/docker-compose.yml`.



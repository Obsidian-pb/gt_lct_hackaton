# План Этапа 5. Переключение репозитория: JSON-файлы → PostgreSQL

**Дата:** 2026-09-29
**Модель:** Roo Code (режим architect)
**Источник:** [`plans/database_structure.qmd`](database_structure.qmd:247), раздел 5 «Этап 5»
**Предыдущие шаги:** [`workflow/step_1.md`](../workflow/step_1.md) (подключение), [`workflow/step_2.md`](../workflow/step_2.md) (Этап 2.1, JWT), [`workflow/step_3.md`](../workflow/step_3.md) (Этап 2.2, схема 2.2.0 и справочники), [`workflow/step_4.md`](../workflow/step_4.md) (Этап 3, импорт учебных данных, схема 2.3.0), [`workflow/step_5.md`](../workflow/step_5.md) (Этап 4, мастерская — минимально)
**Отчёт по завершении:** `workflow/step_6.md`

---

## 1. Постановка задачи (из документа)

> ### Этап 5. Переключение репозитория
> - Ввести адаптер хранилища с тем же интерфейсом, что у `Engine.save/load/list_items`
>   ([`ai_core.py`](../ai_core.py:56)): режим работы «файлы → БД», затем «только БД».
> - Поэтапно переводить операции REST ([`api_contract.py`](../api_contract.py:67)) на новый
>   репозиторий **без изменения контрактов API**.
> - Оставить `config.local.json` (ключ ИИ) вне БД — это секрет, не доменные данные.

Дополнительно, по итогам Этапов 3–4 (см. [`workflow/step_5.md`](../workflow/step_5.md:108)):
- перевод мастерской карточек на чтение/запись из БД (таблицы `workshop_*` созданы в 2.2.0 и пусты);
- при необходимости — перенос накопленных карточек из `localStorage` **upsert-ом по `number`**
  (проектное решение №7, [`plans/database_structure.qmd`](database_structure.qmd:154));
- полноценная ролевая авторизация (обсуждается, см. раздел 10).

### Что переключается на БД (полная карта файлового хранилища)

| Область | Сейчас | Файлы/механизм | Таблицы БД |
|---|---|---|---|
| Задания (t-*) | [`ai_core.Engine.save/load/list_items`](../ai_core.py:56) | `data/t-*.json` | `task`, `task_dds`, `task_incident_source` |
| Сессии (s-*) | тот же Engine | `data/s-*.json` | `session` + 9 дочерних таблиц |
| Сценарии | [`curriculum.py`](../curriculum.py:23) | `data/curriculum/scenario-*.json` | `scenario`, `scenario_task` |
| Тренировки | [`curriculum.py`](../curriculum.py:23) | `data/curriculum/training-*.json` | `training`, `training_scenario`, `training_participant`, `training_card`, `training_service_action` |
| Материалы | [`materials.py`](../materials.py:9) | `data/curriculum/materials.json` | `material` |
| Дубликаты публикации | [`incident_training.publish`](../incident_training.py:38) | проверка файла `t-*.json` | уникальный `task.identity_hash` |
| Мастерская | [`frontend/src/workshop-store.js`](../frontend/src/workshop-store.js:6) | `localStorage giik.card-workshop.v1` | `workshop_card`, `workshop_card_reference`, `workshop_card_version`, `workshop_card_event`, `workshop_card_dialogue` |
| Аутентификация и справочники | уже БД (2.1.0 / 2.2.0) | — | — |

---

## 2. Ключевые проектные решения

### 2.1. Режимы хранилища (конфигурация)

Секция `"storage"` в `config.local.json` (+ переопределение env `STORAGE_MODE`):

```json
{ "storage": { "mode": "files" } }
```

| Режим | Чтение | Запись | Назначение |
|---|---|---|---|
| `files` (по умолчанию) | файлы | файлы | Легаси. Все существующие тесты и стенды без БД не меняются. |
| `files-to-db` | БД → если нет, файл (с зеркалированием в БД) | файл **и** БД (dual-write) | Переходный: БД наполняется, файлы остаются источником отката. |
| `db-only` | БД | БД | Целевой: БД — единственный источник истины, файлы игнорируются. |

Перед включением `files-to-db`/`db-only` выполняется первичная синхронизация
`init_storage.py --mirror` (по сути повторное использование `init_training_data.py --init`
+ `init_workshop.py` для мастерской), чтобы БД уже содержала актуальные данные.
В режимах с БД сервер не стартует без доступной БД (проверка при инициализации адаптера,
как в `data_layer.py`).

### 2.2. Адаптер хранилища с интерфейсом Engine

Новый модуль `storage_adapter.py` реализует **тот же интерфейс**, что и файловые операции
[`Engine.save/load/list_items`](../ai_core.py:56), плюс необходимые расширения:

```python
class StorageAdapter:
    def save(self, item): ...            # id вида t-/s- → upsert в БД (+ файл в files-to-db)
    def load(self, identifier): ...      # сборка полного документа из строк
    def list_items(self, kind): ...      # t/s, сортировка updated_at/created_at desc
    def exists(self, identifier): ...    # замена проверки файла (incident_training.publish)
    # ресурсы curriculum/materials (для рефакторинга curriculum.py / materials.py)
    def resource_save(self, item): ...
    def resource_get(self, identifier): ...
    def resource_list(self, kind): ...
    def materials_items(self): ...
    def materials_add(self, entry): ...
```

В [`ai_core.Engine.__init__`](../ai_core.py:51) добавляется параметр `storage=None`:
`save/load/list_items/exists` делегируют адаптеру при его наличии, иначе работают
с файлами как сейчас. Это сохраняет поведение по умолчанию и все существующие тесты.

### 2.3. Конвертеры «документ ↔ строки»

Документы в файлах — это **полные словари** (сессия содержит `history`, `hints`,
`card_edits`, `assessment`, `teacher_decision`, `machine_assessment`, `task` и т.д.),
а схема БД нормализована. Необходимы двусторонние конвертеры:

- `task` ↔ (`task` + `task_dds` + `task_incident_source`);
- `session` ↔ (`session` + `session_turn` + `session_hint` + `session_card_edit` +
  `session_reveal` + `machine_assessment` + `ai_assessment`/`ai_assessment_field` +
  `teacher_decision`/`teacher_decision_field`);
- `scenario` ↔ (`scenario` + `scenario_task`);
- `training` ↔ (`training` + `training_scenario` + `training_participant` +
  `training_card` + `training_service_action`);
- `material` ↔ `material`.

Логика конвертации **извлекается из импортёра** ([`training_data_importer.py`](../training_data_importer.py),
[`training_data_service.build_rowsets`](../training_data_service.py:207)) в общий модуль
`storage_documents.py`, чтобы и импортёр (Этап 3), и адаптер использовали один код.
Ключевые правила (сохраняются как в импортёре):

- `session.task_snapshot` (JSONB) хранит **полный документ задачи** на момент старта —
  при `load()` возвращается как `session['task']` без обращения к `task`;
- `reference_hash`, правило `delivered` для реплик ДДС, нормализация времени UTC;
- `identity_hash` — только для `incident-v1` (unique-индекс `task.identity_hash`).

### 2.4. Идентификация вместо строковых имён

При сохранении строки `student`/`teacher`/`approved_by` резолвятся в `user_id`:
1. поиск по `legacy_name_map.name`; 2. по `user.display_name`/`full_name`;
3. создание нового пользователя (роль по kind: teacher > student, случайный пароль,
   `display_name = исходная строка`) — ровно как в [`training_data_service`](../training_data_service.py:175).
При загрузке `user.display_name` возвращается в документ, поэтому строки в контрактах
REST остаются неизменными. Таблица `legacy_name_map` остаётся для переходного периода
и аудита (может быть удалена отдельным решением после Этапа 5).

### 2.5. Стратегия записи: upsert по натуральному ключу

- `task.id`/`session.id`/`scenario.id`/`training.id`/`material.id` — натуральные ключи
  (`INSERT ... ON CONFLICT (id) DO UPDATE`), идемпотентно;
- дочерние коллекции сессии/сценария/тренировки — `DELETE` по родителю + `INSERT`
  в одной транзакции (`db_connection.transaction()`), как в импортёре;
- при сохранении сессии задача может отсутствовать (сиротская ссылка) — автоматический
  upsert `task` из `task_snapshot`, иначе нарушится FK `session.task_id`;
- каждая операция `save` — одна транзакция; HTTP-обработчик уже сериализует
  storage-маршруты общим `lock` ([`rest_api.py`](../rest_api.py:164)).

### 2.6. Мастерская карточек на БД

- Новые REST-маршруты `/workshop/*` (см. раздел 5, Фаза 4) с `auth='teacher'`/`auth='admin'`;
- репозиторий `workshop_*`: карточка + эталон (версии) + журнал событий + диалог;
- **round-trip карточки**: браузерный `content` (поля, `class_ids`, `services`,
  `main_service`, `flags`, заголовок, `report` и пр.) маппится в колонки `workshop_card`
  (`fields` JSONB, `class_ids` JSONB, `services` JSONB, ...). Для гарантии точного
  round-trip предлагается версия схемы **2.4.0**: добавить колонку
  `workshop_card.content jsonb` (полный исходный `content` как есть). Альтернатива без
  DDL — собирать `content` из существующих колонок (менее надёжно при появлении новых
  ключей) — фиксируется решением команды;
- перенос накопленных карточек из `localStorage` — **только upsert по уникальному
  `number` (`К-XXXXXXXX`)**, без перезаписи таблиц (проектное решение №7);
  инструмент `init_workshop.py --import <файл-json>` (принимает экспорт из
  `workshop-store.download`) и/или эндпоинт `/workshop/import`.

### 2.7. Что остаётся вне БД

`config.local.json` (ключ ИИ, `authorization_key`/`base_url`/`model`), статические
`catalog/classifier.json` (исходник для импорта справочников), `ui/geo/*.json`
(гео-поиск продолжает работать из файлов; импорт в БД — по флагу, логика не меняется,
см. Этап 2.2), баннеры, голосовые ресурсы. `data/*.json` после перехода на `db-only`
— только архив/аудит.

---

## 3. Целевая архитектура

```{mermaid}
flowchart LR
    UI[Браузер React] --> API[REST /api/v1 без изменения контрактов]
    API --> APPDISPATCH[application.dispatch]
    APPDISPATCH --> ENGINE[Engine ai_core]
    ENGINE --> ADAPTER[StorageAdapter]
    ADAPTER --> REPO[StorageRepository]
    REPO --> DB[(PostgreSQL 14)]
    ADAPTER --> FILES[(data JSON-файлы)]
    APPDISPATCH --> CUR[Cirriculum и Materials через adapter]
    WORKSHOP[Мастерская Cards.jsx] --> WSAPI[Новые /workshop REST]
    WSAPI --> WREPO[workshop-репозиторий]
    WREPO --> DB
    AUTH[auth-service и catalog-service] --> DB
```

Слои:
1. `storage_documents.py` — чистые конвертеры документ↔строки (без БД, unit-тестируемые);
2. `storage_repository.py` — row-level CRUD (Simple Query + `quote_literal`, транзакции);
3. `storage_adapter.py` — режимы, dual-write, fallback;
4. `ai_core.py`/`curriculum.py`/`materials.py`/`incident_training.py` — потребление адаптера;
5. `application.py`/`rest_api.py`/`api_contract.py` — новые маршруты мастерской.

---

## 4. Фазы реализации

### Фаза 0. Подготовка и фикстуры

- Зафиксировать текущее состояние: `init_catalog.py --check` (схема 2.2.0, 61/24/1283/22489),
  `init_training_data.py --check` (схема 2.3.0; на стенде `data/` пуст — ожидаемо);
- проверить права БД (`CREATE TABLE` — уже подтверждено в Этапе 2.1);
- решить по п. 2.6: версия схемы 2.4.0 с колонкой `workshop_card.content` или маппинг без DDL;
- фикстуры-документы для unit-тестов конвертеров (legacy/caller, dds, incident-v1,
  полная сессия, сценарий, тренировка, материал) — образцы из `tests/test_training_data_importer.py`.

### Фаза 1. Конвертеры и репозиторий (задания и сессии)

1. `storage_documents.py`:
   - `task_to_rows(task)` / `rows_to_task(...)` — включая `task_dds` и `task_incident_source`;
   - `session_to_rows(session)` / `rows_to_session(...)` — включая все дочерние таблицы,
     сборку `task` из `task_snapshot`, восстановление `history/hints/card_edits/assessment/
     teacher_decision/machine_assessment/training/training_reveals/...`;
   - рефакторинг [`training_data_importer.py`](../training_data_importer.py) и
     [`training_data_service.build_rowsets`](../training_data_service.py:207) на использование
     общих функций (без изменения поведения Этапа 3).
2. `storage_repository.py`:
   - `upsert_task`, `upsert_session` (транзакционно, `ON CONFLICT`), `load_task`, `load_session`,
     `list_tasks`, `list_sessions` (пагинация не нужна — объёмы пробной версии малы),
     `exists_task`;
   - резолв имён: `resolve_name_to_user(connection, name, kind)` (reuse
     [`training_data_repository`](../training_data_repository.py:196) — `find_user_by_display_name`,
     `create_user`, `promote_user_to_teacher`, `legacy_name_map`), `user_display_name(id)`;
   - метод `ensure_task_from_snapshot` для FK `session.task_id`.
3. Unit-тесты round-trip: `doc → rows → doc` идентичен (с точностью до порядка ключей),
   для всех типов документов.

### Фаза 2. Адаптер, режимы и переключение REST (задания/сессии)

1. `storage_config.py` — чтение секции `storage` из `config.local.json` + env `STORAGE_MODE`,
   по приоритету как `db_config` (дефолт → config.local.json → env).
2. `storage_adapter.py` — `save/load/list_items/exists` по режимам 2.1;
   `init_storage.py` — CLI `--check/--self-test/--mirror/--pause`, exit 0/2 (по образцу
   [`init_training_data.py`](../init_training_data.py)).
3. Инъекция в [`web_ui.py`](../web_ui.py:273): `storage = make_storage(config)`,
   `engine = Engine(AIProvider(), args.data_dir, storage=storage)`.
4. Переключение REST-операций **без изменения контрактов**:
   - `tasks/create/save_task/approve`, `sessions/*`, `students/*`, `teacher/*`, `works/review/
     finalize`, `home`, `assess`, `card_publish` — уже идут через `engine.*`, ничего менять
     не нужно, кроме `incident_training.publish` (проверка дублей через `engine.exists`);
   - проверить `check_state` в [`rest_api.py`](../rest_api.py:145) (работает через `engine.load`).
5. Интеграционные тесты на живую БД: dual-write, fallback-чтение из файла с зеркалированием,
   `db-only` без файлов, идемпотентность повторных `save`.

### Фаза 3. Сценарии, тренировки и материалы

1. `storage_documents.py`/`storage_repository.py`: конвертеры и CRUD для
   `scenario`+`scenario_task`, `training`+`training_scenario`+`training_participant`+
   `training_card`+`training_service_action`, `material`.
2. Рефакторинг [`curriculum.py`](../curriculum.py:23): замена прямых обращений
   `Path(engine.directory)/'curriculum'` на `engine.resource_save/resource_get/resource_list`
   (интерфейсные методы Engine → адаптер). Поведение и статусы (`prepared/active/completed`,
   CHECK-ограничения) не меняются.
3. Рефакторинг [`materials.py`](../materials.py:9) на `engine.materials_items/materials_add`.
4. Проверка потоков тренировки (`training_desk`, `training_route`, `training_service_action`,
   `training_progress.advance`, `curriculum.accept_call`) на БД.

### Фаза 4. Мастерская карточек на БД

1. **Схема (по решению п. 2.6)**: `init_storage.py --init` добавляет версию 2.4.0
   (колонка `workshop_card.content jsonb` при выбранном варианте).
2. **Репозиторий** `workshop_repository` (в `storage_repository.py`):
   - `create_card(content, provenance, author_id)`, `update_card`, `get_card`, `list_cards`,
     `delete_card`;
   - эталон: `save_reference(card_id, reference, model, prompt_version)` → новая строка
     `workshop_card_reference` (версионирование); 
   - журнал: `add_event(card_id, action, text, payload)` → `workshop_card_event`;
   - утверждение: `approve_card(...)` → `workshop_card_version` (snapshot=content+reference+review,
     review=teacher/at/note) + status='approved';
   - диалог: `get/set_dialogue(card_id, turns, callback_disclosed)` → `workshop_card_dialogue`;
   - импорт: `import_cards(records)` — upsert по `number`.
3. **REST-маршруты** в [`api_contract.py`](../api_contract.py) (контракт **расширяется** —
   новых операций раньше не было; существующие не меняются), все `auth='teacher'`:

   | Метод | Путь | Назначение |
   |---|---|---|
   | GET | `/workshop/cards` | Список (краткие поля) |
   | POST | `/workshop/cards` | Создать карточку (content, provenance) → 201 |
   | GET | `/workshop/cards/{card_id}` | Полная карточка (content, reference, dialogue, events, review) |
   | PUT | `/workshop/cards/{card_id}` | Сохранить правки (content, reference_checked, ...) |
   | POST | `/workshop/cards/{card_id}/events` | Добавить событие в журнал |
   | POST | `/workshop/cards/{card_id}/references` | Создать версию эталона |
   | POST | `/workshop/cards/{card_id}/approvals` | Утвердить (review) → version snapshot |
   | POST | `/workshop/cards/{card_id}/reopening` | Вернуть на доработку |
   | DELETE | `/workshop/cards/{card_id}` | Удалить черновик |
   | POST | `/workshop/imports` | Импорт JSON (upsert по number) |

   `web_ui.py` освобождает `/workshop/*` от X-UI-Token (как `/auth/*`, `/catalog/*`).
   Перегенерировать `openapi.json` и `ui/api-routes.js` (`python build_api_contract.py`).
4. **Фронтенд** ([`workshop-store.js`](../frontend/src/workshop-store.js), `Cards.jsx`):
   - `init()` читает карточки через `GET /workshop/cards` (localStorage — только кэш/импорт);
   - `add/edit/review/generateReference/askCaller/publishTraining` выполняют API-вызовы
     с `authHeaders()`; журнал и версии — на сервере;
   - обработка ошибок/офлайна: при недоступности API — предупреждение, как сейчас
     при сбое `localStorage`.
5. **Вход преподавателя**: `/auth/login` уже поддерживает роль `teacher` (Этап 2.1);
   UI входа переиспользуется (страница `/admin-login` → общий логин) — при выбранном
   варианте RBAC (раздел 10).
6. **Перенос накопленных карточек**: кнопка «Импортировать из этого браузера» в
   мастерской (читает `localStorage`, шлёт `/workshop/imports`) и/или CLI
   `init_workshop.py --import cards.json`; повторный импорт идемпотентен (upsert по `number`).

### Фаза 5. Режим «только БД», интеграция и завершение

1. Проверка полного цикла в режиме `db-only`: генерация/публикация карточки → задание
   → сценарий → тренировка → сессия студента → проверка преподавателем → отчёт.
2. `START_ALL.ps1`: некритичный шаг `init_storage.py --check` (лог `.runtime\storage-init.log`);
   `TEST_STORAGE.cmd` — ручной запуск `--init --check --self-test --pause`.
3. Регрессия: полный прогон `python -X utf8 -m unittest discover -s tests -p "test_*.py"`
   (режим по умолчанию `files` — старые тесты не затрагиваются; известные 30 ошибок
   `test_multi_provider` — вне scope, задокументированы).
4. Документация: статус Этапа 5 в [`plans/database_structure.qmd`](database_structure.qmd:247),
   отчёт [`workflow/step_6.md`](../workflow/step_6.md) (по правилам [`workflow/README.md`](../workflow/README.md)).

---

## 5. Новые и изменяемые файлы

### Новые
| Файл | Роль |
|---|---|
| `storage_config.py` | Настройки режима хранилища (дефолт → config.local.json → env) |
| `storage_documents.py` | Чистые конвертеры документ↔строки (общие с импортёром) |
| `storage_repository.py` | Row-level CRUD: task/session/scenario/training/material/workshop, резолв имён |
| `storage_adapter.py` | Адаптер интерфейса Engine: save/load/list_items/exists/resource_*, режимы |
| `init_storage.py` | CLI `--init [--mirror] --check --self-test --pause`, exit 0/2 |
| `init_workshop.py` | Импорт карточек из JSON (upsert по number), самопроверка |
| `TEST_STORAGE.cmd` | Ручной запуск init_storage |
| `tests/test_storage_documents.py` | Unit: round-trip конвертеров |
| `tests/test_storage_adapter.py` | Unit: режимы, fallback, dual-write (файлы через tmpdir) |
| `tests/test_storage_integration.py` | Живая БД: upsert, FK, имена, workshop CRUD, импорт |

### Изменяемые
| Файл | Изменение |
|---|---|
| `ai_core.py` | `Engine.__init__(storage=None)`, делегирование `save/load/list_items/exists` |
| `web_ui.py` | Создание адаптера из конфига; освобождение `/workshop/*` от X-UI-Token |
| `api_contract.py` | Маршруты `/workshop/*` (auth='teacher'/'admin'); `build_api_contract.py` |
| `application.py` | Диспетчеризация `workshop_*`; (опционально RBAC legacy-маршрутов) |
| `rest_api.py` | Поддержка новых маршрутов (автоматически через контракт) |
| `curriculum.py`, `materials.py` | Переход на методы адаптера вместо путей к файлам |
| `incident_training.py` | `publish`: проверка дублей через `engine.exists` |
| `training_data_importer.py`, `training_data_service.py` | Рефакторинг на общие конвертеры |
| `frontend/src/workshop-store.js`, `Cards.jsx`, `api.js` | Мастерская из БД + вход преподавателя |
| `START_ALL.ps1` | Некритичный шаг `init_storage.py --check` |
| `plans/database_structure.qmd` | Статус Этапа 5 |
| `workflow/step_6.md` | Новый отчёт |

---

## 6. Тесты и проверки

| Уровень | Что проверяется |
|---|---|
| Unit (`storage_documents`) | Round-trip всех типов документов: `doc → rows → doc` идентичен; dds-реплики (`delivered`/`event`/`source`); `incident-v1`; время UTC; порядок колонок |
| Unit (`storage_adapter`) | Выбор режима; в `files-to-db` — dual-write; в `db-only` — нет обращений к файлам; fallback при пустой БД; `exists` |
| Integration (живая БД) | Upsert идемпотентен; `session.task_snapshot` → сборка `task`; авто-upsert задачи из снимка; резолв/создание пользователей и обратный `display_name`; scenario/training/material; workshop CRUD + версии + журнал + диалог + импорт по `number`; версия схемы |
| Регрессия | `python -X utf8 -m unittest discover -s tests -p "test_*.py"` — режим `files` по умолчанию, старые тесты не меняются |
| Ручной сценарий | `TEST_STORAGE.cmd`; полный цикл в `db-only` (п. Фаза 5.1); мастерская: создать → эталон → утвердить → опубликовать → тренировка |

---

## 7. Порядок включения на стенде

```
1. python init_storage.py --check        # состояние схемы/данных
2. python init_storage.py --mirror       # первичная синхронизация (или TEST_DATA.cmd)
3. config.local.json: { "storage": { "mode": "files-to-db" } }
4. START.cmd → проверить .runtime\storage-init.log и работу UI
5. Накопительная проверка → переключить mode: "db-only"
6. python init_storage.py --self-test    # round-trip и целостность
```

---

## 8. Риски и ограничения

1. **Round-trip документов** — главный риск: бизнес-логика ([`dds.py`](../dds.py),
   [`curriculum.py`](../curriculum.py), [`training_progress.py`](../training_progress.py))
   оперирует полными словарями сессии. Снимается: `task_snapshot` уже содержит полный
   документ задачи; детальные unit-тесты на идентичность round-trip; режим `files-to-db`
   позволяет откатиться без потери данных.
2. **Два процесса без общего lock**: `web_ui` (8878) и выделенный REST (8890) могут
   работать одновременно — гонки на уровне БД не исключены. Для стенда достаточно
   одного процесса; при необходимости — `SELECT ... FOR UPDATE` в `storage_repository`.
3. **Частичная доставка реплики ДДС** (`delivery='partial'`) — в БД хранится только
   boolean `delivered` (ограничение схемы, задокументировано в Этапе 3).
4. **Пароли импортированных пользователей случайны** — выдаются админом; мастерская
   требует JWT-входа преподавателя (см. раздел 10).
5. **Импорт карточек** — только upsert по `number` (проектное решение №7), чтобы
   карточки с разных машин не затирали друг друга.
6. **`data/` на стенде пуст** — интеграционные сценарии на живую БД используют
   фикстуры; реальный импорт — на стенде с данными.
7. **Объём Фазы 4 (фронтенд)** — заметная часть этапа; при необходимости фронтенд
   можно переключить отдельной под-фазой после бэкенда.

---

## 9. Открытые вопросы (нужно решение команды)

1. **RBAC**: распространять ли JWT-авторизацию (student/teacher) на legacy-маршруты
   (`/tasks`, `/sessions`, `/students/*`, `/teacher/*`, `/scenarios`, `/trainings`, `/works/*`)
   в рамках Этапа 5, или ограничиться новыми `/workshop/*` (рекомендуется)?
2. **Мастерская**: полный перевод фронтенда на БД в этом этапе или сначала только
   бэкенд + REST + импорт, а фронт — следующей итерацией?
3. **Схема 2.4.0**: добавлять колонку `workshop_card.content` для точного round-trip
   или обходиться маппингом в существующие колонки?
4. **Режим по умолчанию**: подтвердить `files` (безопасно для тестов) с явным
   переключением на `files-to-db`/`db-only` через конфиг.
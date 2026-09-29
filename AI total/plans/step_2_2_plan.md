# План работ — Этап 2.2. Инициализация схемы данных и справочников

**Дата:** 2026-09-28
**Источник:** [`plans/database_structure.qmd`](plans/database_structure.qmd) (раздел 5, «Этап 2. Инициализация схемы» → «Этап 2.2»)
**Предыдущие шаги:** [`workflow/step_1.md`](workflow/step_1.md) (подключение к PostgreSQL), [`workflow/step_2.md`](workflow/step_2.md) (Этап 2.1, пользователи и аутентификация)

---

## 1. Постановка задачи

Из [`plans/database_structure.qmd`](plans/database_structure.qmd:183) (Этап 2.2) требуется:

1. **Создать таблицы по разделу 2** документа, индексы и внешние ключи.
   Раздел 2 описывает сущности: справочники/каталоги (`service`, `classifier_category`,
   `classifier_entry`, `classifier_entry_service`), мастерскую карточек
   (`workshop_card` и связанные), учебный каталог (`task`, `task_dds`, `task_incident_source`),
   сценарии и тренировки (`scenario`, `training` и связанные), сессии и оценивание
   (`session`, `session_turn`, `session_hint`, `session_card_edit`, `session_reveal`,
   `machine_assessment`, `ai_assessment`, `ai_assessment_field`, `teacher_decision`,
   `teacher_decision_field`), служебные (`ai_generation_log`, `insight_report`).
2. **Импортировать статические справочники**:
   - `classifier_category`, `classifier_entry`, `classifier_entry_service`, `service` — из
     [`catalog/classifier.json`](catalog/classifier.json);
   <!-- - при необходимости `geo_address` / `geo_building` — из [`ui/geo/*.json`](ui/geo/README.md). -->
3. **Добавить в админку вкладку** в левой части окна admin. При переходе открывается список всех
   перечисленных списков; списки можно изменять (логика редактирования как у остальных элементов
   админки); изменения сохраняются в БД.

### ВАЖНО!

Geo-данные сейчас в проекте хранятся как файлы geojson. Логику работы с ними не менять! Ни фронт нни бэкенд!

---

## 2. Текущее состояние и переиспользуемые заделы

| Что уже есть | Где | Как используем |
|---|---|---|
| Wire-клиент PostgreSQL (stdlib), `execute`/`fetchone`/`quote_literal`/`transaction` | [`db_connection.py`](db_connection.py), [`db_config.py`](db_config.py) | Без изменений; возможно хардненинг Extended Query при массовом импорте |
| Паттерн инициализации схемы: `SCHEMA_STATEMENTS` + `ensure_schema()` + версия в `schema_migration` | [`auth_repository.py`](auth_repository.py:22) | Копируем для нового слоя; версия схемы **2.2.0** |
| Паттерн скрипта инициализации `--init/--check/--self-test/--pause`, exit-коды 0/2, `TEST_*.cmd`, некритичный шаг в лаунчере | [`init_auth.py`](init_auth.py), [`TEST_AUTH.cmd`](TEST_AUTH.cmd), [`START_ALL.ps1`](START_ALL.ps1) | Копируем: `init_catalog.py` + `TEST_CATALOG.cmd` + шаг «Initializing the catalog layer» в `START_ALL.ps1` (лог `.runtime\catalog-init.log`) |
| Контракт REST: `Route(..., auth='admin')`, поле `auth` в маршрутах; JWT-middleware в `rest_api.py`; диспетчеризация действий в `application.py`; генерация OpenAPI | [`api_contract.py`](api_contract.py:153), [`application.py`](application.py:422), [`build_api_contract.py`](build_api_contract.py) | Добавляем маршруты `/catalog/*` с `auth='admin'` (уровень защиты уже реализован) |
| Админка: левое меню `menu`, Drawer-панели, `Tabs`, `Toolbar`, CRUD-формы, `authHeaders()` | [`frontend/src/Admin.jsx`](frontend/src/Admin.jsx:6), [`ui/admin.css`](ui/admin.css) | Добавляем пункт меню «Справочники» и `CatalogDrawer` по образцу `UsersDrawer`/`GroupPanel` |
| Тестовые каркасы: unit без БД, integration со скипом при недоступности БД | [`tests/test_auth_integration.py`](tests/test_auth_integration.py), [`tests/test_auth_crypto.py`](tests/test_auth_crypto.py) | Аналогичные `test_catalog_*.py` |

### Уже созданные таблицы (Этап 2.1) — не трогаем
`user`, `student_group`, `group_member`, `auth_session`, `schema_migration`.

---

## 3. Ключевые проектные решения

1. **Версия схемы 2.2.0.** Новая порция `SCHEMA_STATEMENTS` размещается в отдельном модуле
   репозитория справочников (например, `catalog_repository.py`); `ensure_schema()` идемпотентен
   (`CREATE TABLE IF NOT EXISTS`), в `schema_migration` фиксируется версия `2.2.0`.

2. **Строковые натуральные ключи там, где их диктуют существующие форматы файлов.**
   `task.id` (`t-…`), `session.id` (`s-…`), `scenario.id` (`scenario-…`), `training.id`
   (`training-…`), `training_card.id` (`card-…`) — текст, совпадает с pattern из
   [`api_contract.py`](api_contract.py:13) (`^[ts]-[0-9a-f]{12}$` и т.п.). Новые сущности
   (`workshop_card`, справочники, оценки, реплики) получают `bigint GENERATED ALWAYS AS IDENTITY`
   как в [`auth_repository.py`](auth_repository.py:25).

3. **Гибкие поля — JSONB.** `workshop_card.fields/class_ids/services/flags/provenance/caller_scenario/
   geocoding/service_selection`, `task.fields/field_labels`, `task_dds.incoming_card/actions`,
   `task_incident_source.content/reference/caller_scenario`, `session.task_snapshot/card/training_meta/
   forced_finish`, `ai_assessment_field.evidence`, `workshop_card_reference.source_content/answer`,
   `workshop_card_version.snapshot/review`, `workshop_card_event.payload` и т.п. — JSONB/JSON
   (проектное решение №1 в [`plans/database_structure.qmd`](plans/database_structure.qmd:142)).
   Значения на фронт отдаются как есть (словари), как в текущем REST.

4. **CHECK-ограничения статусов и ролей.** Статусы `session`, `training_card`, `training`,
   `scenario`, `task`, `workshop_card`, `ai_assessment.status`, вердикты `ai_assessment_field.verdict`,
   решения `teacher_decision_field.decision`, учебные роли `training_participant.role`, оценки
   `teacher_decision.grade IN (2..5)` — через CHECK (проектное решение №4).

5. **Справочники классификатора пересоздаются из файла транзакционно.** Так как на справочники
   (`service`, `classifier_*`) пока ничто не ссылается внешними ключами, стратегия импорта —
   «полная перезапись» внутри одной транзакции (`DELETE`/`TRUNCATE` + `INSERT`) с подсчётом строк.
   Повторный запуск идемпотентен. Geo-импорт — по флагу `--geo`.

6. **Маппинг `classifier.json`** (структура файла описана в [`tools/import_classifier.py`](tools/import_classifier.py:10)):
   - `services` (объект code → name) → `service(code PK, name)` — ожидается 61 запись;
   - `categories` (объект номер → имя) → `classifier_category(id smallint PK, name)` — 24 записи;
   - `entries[]` → `classifier_entry`:
     `id = entry.code` (text PK), `category_id → classifier_category.id`,
     `group_name = entry.group`, `statistical_group`, `sign1..sign3`, `extra_signs`, `title`,
     `ekp_type`, `main_service_code = entry.main_service` (или первый из `services`);
   - `entries[].rules[]` → `classifier_entry_service`:
     `entry_id`, `service_code`, `condition_type` (константа, напр. `'column'`), `condition_text`
     (объединённые заголовки условий из `rule.condition`), `value` (значение ячейки),
     `is_main` (code входит в `entry.services`).
   > Детали семантики условных столбцов (N–AG, AM, AU, CI) уточняются при реализации; схема
   > готова хранить и произвольный `condition_text`, и `value`.

<!-- 7. **Geo-данные** ([`ui/geo/addresses.json`](ui/geo/addresses.json:1)): массив `addresses[]` с
   `id`, `kind` (`building`/…), `street`, `house`, `point [lon, lat]`. Маппинг:
   - `geo_address(id text PK = source id, street, house, lat numeric, lon numeric, kind, point JSONB)`;
   - `geo_building` — подмножество с `kind='building'` (по документу раздел 2.1).
   `map.json` (дороги/граница) — при необходимости отдельной таблицей либо пропускается;
   вопрос решается по факту анализа структуры файла на этапе реализации. -->


8. **REST `/catalog/*` — только админ.** Список и CRUD по каждой таблице справочников:
   `GET /catalog/services|categories|entries|entry-services|geo-addresses`,
   `POST/PUT/DELETE` по ресурсу. Маршруты `storage=False`, `auth='admin'` — защита уже
   обеспечивается JWT-middleware из Этапа 2.1. Все значения — через `quote_literal()`.

9. **Фронтенд.** В `menu` [`Admin.jsx`](frontend/src/Admin.jsx:6) добавляется пункт
   `['catalog','▦','Справочники']`; новый `CatalogDrawer` с `Tabs` по спискам и панелями по образцу
   существующих (таблица + Toolbar-поиск + форма добавления + inline-редактирование + удаление с
   `confirm`). Все запросы — с `authHeaders()`.

10. **Индексы** — раздел 6 [`plans/database_structure.qmd`](plans/database_structure.qmd:206) +
    индексы по всем FK и часто фильтруемым колонкам (см. п. 7 ниже).

---

## 4. Структура таблиц (соответствие разделу 2)

> Полный DDL собирается в `SCHEMA_STATEMENTS` модуля `catalog_repository.py`; здесь — только
> ключевые поля и ограничения.

### 4.1 Справочники и каталоги (раздел 2.1)
| Таблица | Ключевые поля и ограничения |
|---|---|
| `service` | `code text PK`, `name text NOT NULL` |
| `classifier_category` | `id smallint PK` (1..24), `name text NOT NULL` |
| `classifier_entry` | `id text PK` (код из файла), `category_id smallint FK → classifier_category`, `group_name`, `statistical_group`, `sign1..sign3`, `extra_signs`, `title`, `ekp_type`, `main_service_code text FK → service`; индекс по `category_id` |
| `classifier_entry_service` | `id bigint identity PK`, `entry_id text FK → classifier_entry ON DELETE CASCADE`, `service_code text FK → service ON DELETE RESTRICT`, `condition_type text`, `condition_text text`, `value text`, `is_main boolean`; unique `(entry_id, service_code, condition_text, value)`; индекс по `service_code` |
| `geo_address` | `id text PK`, `street text`, `house text`, `lat numeric`, `lon numeric`, `kind text`, `point JSONB`; индекс по `(street, house)` |
| `geo_building` | `id text PK`, `street text`, `house text`, `lat numeric`, `lon numeric`, `point JSONB` |

### 4.2 Мастерская карточек (раздел 2.2)
| Таблица | Ключевые поля и ограничения |
|---|---|
| `workshop_card` | `id bigint identity PK`, `number text UNIQUE`, `status text CHECK (draft/approved)`, `title`, `report`, `fields JSONB`, `class_ids JSONB`, `services JSONB`, `main_service text`, `flags JSONB`, `provenance JSONB`, `revision int default 0`, `created_by_id bigint FK → user ON DELETE SET NULL`, `created_at/updated_at timestamptz`; `caller_scenario JSONB`, `opening text`, `geocoding JSONB`, `service_selection JSONB`; GIN по `fields`, `class_ids`; индекс `(status, updated_at desc)` |
| `workshop_card_reference` | `id identity PK`, `card_id FK → workshop_card ON DELETE CASCADE`, `version int`, `source_content JSONB`, `answer JSONB`, `model text`, `prompt_version text`, `created_at`, `edited_at`, `checked_at`; unique `(card_id, version)` |
| `workshop_card_version` | `id identity PK`, `card_id FK CASCADE`, `snapshot JSONB`, `review JSONB`, `action text`, `created_at`, `author_id FK → user SET NULL`; индекс по `(card_id, created_at)` |
| `workshop_card_event` | `id identity PK`, `card_id FK CASCADE`, `at timestamptz`, `action text`, `text text`, `payload JSONB`; индекс по `(card_id, at)` |
| `workshop_card_dialogue` | `card_id FK CASCADE PRIMARY KEY`, `turns JSONB`, `callback_disclosed boolean` |

### 4.3 Учебный каталог заданий (раздел 2.3)
| Таблица | Ключевые поля и ограничения |
|---|---|
| `task` | `id text PK` (`t-…`), `title`, `status text CHECK (draft/approved)`, `workflow text CHECK (caller/dds)`, `level`, `format text CHECK (legacy/incident-v1)`, `opening text`, `persona text`, `fields JSONB`, `field_labels JSONB`, `source text`, `identity_hash text UNIQUE`, `approved_by_id FK → user SET NULL`, `approved_at`, `created_at`, `updated_at` |
| `task_dds` | `task_id text FK → task ON DELETE CASCADE PRIMARY KEY`, `incoming_card JSONB`, `verification_notes text`, `faults text`, `service_name`, `service_role`, `service_knowledge`, `actions JSONB` |
| `task_incident_source` | `task_id FK → task CASCADE PRIMARY KEY`, `content JSONB`, `reference JSONB`, `caller_scenario JSONB`, `opening text` |

### 4.4 Сценарии и тренировки (раздел 2.4)
| Таблица | Ключевые поля и ограничения |
|---|---|
| `scenario` | `id text PK` (`scenario-…`), `title`, `description`, `status text CHECK (draft/approved)`, `created_by_id`, `approved_by_id FK → user SET NULL`, `approved_at`, `created_at`, `updated_at` |
| `scenario_task` | `scenario_id FK → scenario CASCADE`, `task_id FK → task CASCADE`, `difficulty smallint CHECK (1..5)`; PK `(scenario_id, task_id)` |
| `training` | `id text PK` (`training-…`), `title`, `description`, `status text CHECK (prepared/active/completed)`, `mode text CHECK (training/testing)`, `seconds int`, `difficulty text CHECK (easy/medium/hard/adaptive)`, `teacher_id FK → user SET NULL`, `group_name text`, `created_at`, `started_at`, `completed_at`, `updated_at` |
| `training_scenario` | `training_id FK → training CASCADE`, `scenario_id FK → scenario CASCADE`; PK `(training_id, scenario_id)` |
| `training_participant` | `training_id FK CASCADE`, `user_id FK → user CASCADE`, `role text CHECK (operator/dds/service)`, `service_code text`; PK `(training_id, user_id)`; индекс по `user_id` |
| `training_card` | `id text PK` (`card-…`), `training_id FK CASCADE`, `task_id FK → task RESTRICT`, `operator_session_id text`, `status text CHECK (awaiting_call/operator_work/dds_review/service_review/done/stopped)`, `card_snapshot JSONB`, `services JSONB`, `submitted_at`, `dds_by_id FK → user SET NULL`, `routed_at`; индексы `(training_id, status)`, `(operator_session_id)` |
| `training_service_action` | `id identity PK`, `training_card_id FK → training_card CASCADE`, `service_code`, `text`, `at`; индекс по `training_card_id` |
| `material` | `id text PK` (`material-…`), `title`, `url`, `description`, `teacher_id FK → user SET NULL`, `created_at` |

### 4.5 Сессии и оценивание (раздел 2.5)
| Таблица | Ключевые поля и ограничения |
|---|---|
| `session` | `id text PK` (`s-…`), `task_id FK → task RESTRICT`, `task_snapshot JSONB`, `reference_hash text`, `student_id FK → user CASCADE`, `status text CHECK (queued/awaiting_call/active/submitted/pending_teacher/reviewed)`, `effective_level`, `card JSONB`, `training_meta JSONB`, `callback_disclosed boolean`, `connection text`, `call_attempts int default 0`, `next_channel text`, `timed_out boolean`, `forced_finish JSONB`, `teacher_note text`, `teacher_note_by_id FK → user SET NULL`, `teacher_note_at`, `created_at`, `activated_at`, `submitted_at`, `updated_at`; индексы `(student_id, status)`, `(task_id)`, `(created_at desc)` |
| `session_turn` | `id identity PK`, `session_id FK → session CASCADE`, `turn_no int`, `role text CHECK (caller/dispatcher/system/service)`, `text`, `source text CHECK (text/voice)`, `event text`, `delivered boolean`, `at timestamptz`; unique `(session_id, turn_no)` |
| `session_hint` | `id identity PK`, `session_id FK CASCADE`, `text`, `at` |
| `session_card_edit` | `id identity PK`, `session_id FK CASCADE`, `field text`, `before text`, `after text`, `at` |
| `session_reveal` | `id identity PK`, `session_id FK CASCADE`, `field`, `label`, `value text`, `number int`, `at` |
| `machine_assessment` | `id identity PK`, `session_id FK → session CASCADE`, `percent int`, `compared JSONB`, `method text`, `fields JSONB`, `at` |
| `ai_assessment` | `id identity PK`, `session_id FK CASCADE`, `summary text`, `percent int`, `reference_hash text`, `status text`, `created_at`; индекс по `session_id` |
| `ai_assessment_field` | `id identity PK`, `assessment_id FK → ai_assessment CASCADE`, `field text`, `verdict text CHECK (correct/partial/incorrect/missing/unavailable)`, `comment text`, `clarification text`, `citation_warning text`, `evidence JSONB`; индекс по `assessment_id` |
| `teacher_decision` | `id identity PK`, `session_id FK → session CASCADE`, `teacher_id FK → user SET NULL`, `grade smallint CHECK (grade BETWEEN 2 AND 5)`, `percent int`, `conclusion text`, `created_at`; индексы `(session_id)`, `(teacher_id)` |
| `teacher_decision_field` | `id identity PK`, `decision_id FK → teacher_decision CASCADE`, `field text`, `decision text CHECK (agree/reject/edit)`, `comment text`; индекс по `decision_id` |

### 4.6 Служебные (раздел 2.6)
| Таблица | Ключевые поля |
|---|---|
| `ai_generation_log` | `id identity PK`, `model text`, `prompt_version text`, `operation text`, `request JSONB`, `response JSONB`, `duration_ms int`, `error text`, `at timestamptz` |
| `insight_report` | `id identity PK`, `group_name text`, `period text`, `report JSONB`, `created_at` |
| `schema_migration` | уже есть; добавляется строка `2.2.0` |

---

## 5. Состав работ по шагам

### Шаг 1. Модуль схемы и репозитория справочников — `catalog_repository.py`
- Перенести DDL всех таблиц п. 4 в `SCHEMA_STATEMENTS` (порядок с учётом FK: справочники →
  мастерская → задания → сценарии/тренировки → сессии → служебные), `SCHEMA_VERSION = '2.2.0'`.
- `ensure_schema()` — по образцу [`auth_repository.ensure_schema`](auth_repository.py:98).
- CRUD-методы для каждой справочной таблицы (список/получить/создать/обновить/удалить) с
  `quote_literal()`, подсчётом `count(*)` для самопроверки.
- Опционально: метод `replace_classifier(services, categories, entries, entry_services)` —
  транзакционная перезапись справочников.

### Шаг 2. Импортёр справочников — `catalog_importer.py` + `init_catalog.py`
- Парсинг [`catalog/classifier.json`](catalog/classifier.json): services/categories/entries/rules →
  кортежи для `replace_classifier(...)`.
- Парсинг [`ui/geo/addresses.json`](ui/geo/addresses.json): `addresses[]` → `geo_address` (+
  `geo_building` для `kind='building'`); выяснить структуру `ui/geo/map.json` и решить о таблице
  дорог (по умолчанию — пропустить, отметить в отчёте).
- `init_catalog.py --init [--geo] --check --self-test --pause` (exit 0/2), по образцу
  [`init_auth.py`](init_auth.py:66):
  - `--init`: создать схему 2.2.0 + импортировать классификатор (обязательно) + geo (по флагу);
  - `--check`: версия схемы + количества (службы=61, категории=24, записи=1283, связи>0);
  - `--self-test`: чтение выборки из каждой таблицы через CRUD-методы.
- `TEST_CATALOG.cmd` по образцу [`TEST_AUTH.cmd`](TEST_AUTH.cmd).
- Интеграция в [`START_ALL.ps1`](START_ALL.ps1): некритичный шаг «Initializing the catalog
  layer…», лог `.runtime\catalog-init.log`, как в Этапах 1–2.1.

### Шаг 3. REST-маршруты `/catalog/*`
- [`api_contract.py`](api_contract.py): добавить типы (`service_code`, `category_id`, `entry_id`,
  `classifier_*`-поля) и маршруты с `auth='admin'`, `storage=False`:
  - `GET /catalog/services` (список), `POST /catalog/services`, `PUT /catalog/services/{code}`,
    `DELETE /catalog/services/{code}`;
  - `GET /catalog/categories` (+ CRUD) — `classifier_category`;
  - `GET /catalog/entries` (+ CRUD, фильтр по `category_id`) — `classifier_entry`;
  - `GET /catalog/entry-services` (+ CRUD) — `classifier_entry_service`;
  - `GET /catalog/geo-addresses` (+ CRUD при необходимости) — `geo_address`/`geo_building`.
- [`application.py`](application.py:422): диспетчеризация новых действий через `catalog_service`.
- `python build_api_contract.py` → перегенерация `openapi.json`, `ui/api-routes.js`.
- Валидация входных данных (естественные ключи, FK: `service_code` существует и т.п.), ошибки —
  через существующий механизм `APIError` (404/409/422).
- `web_ui.py` не требует изменений (пути `/api/v1/auth/*` уже освобождены от legacy-токенов;
  проверить, что `/catalog/*` попадает под JWT-проверку — при необходимости добавить в список).

### Шаг 4. Фронтенд — вкладка «Справочники»
- [`frontend/src/Admin.jsx`](frontend/src/Admin.jsx:6): добавить пункт в `menu`
  (`['catalog','▦','Справочники']`) и отрисовку `CatalogDrawer`.
- `CatalogDrawer`: `Tabs` по спискам («Службы», «Категории», «Записи классификатора»,
  «Связи записей», «Гео-адреса»); внутри каждой вкладки — панель по образцу `GroupPanel`:
  `Toolbar` с поиском, таблица, форма добавления, inline-редактирование (blur/кнопка «Сохранить»),
  удаление с `confirm`. Все вызовы через `api(..., {headers: authHeaders()})`.
- [`ui/admin.css`](ui/admin.css): при необходимости стили для длинных таблиц справочника
  (фиксированная высота, скролл).
- Сборка бандла — штатно `BUILD_UI.cmd` на машине деплоя (локально node_modules нет —
  замечание из [`workflow/step_2.md`](workflow/step_2.md:146)).

### Шаг 5. Тесты и проверки
- Unit (без БД): парсинг классификатора (фикстура-срез на несколько записей), парсинг
  geo-файла, маппинг правил в `classifier_entry_service`.
- Integration (живая БД, скип при недоступности — как
  [`tests/test_auth_integration.py`](tests/test_auth_integration.py:28)): инициализация схемы 2.2.0
  идемпотентна; импорт даёт 61/24/1283; повторный импорт не дублирует; CRUD `/catalog/*`;
  RBAC: студент получает 403; удаление службы, на которую ссылается запись, отклоняется.
- Ручные проверки: `TEST_CATALOG.cmd`; вход админом → вкладка «Справочники» → правка → перезагрузка
  → данные сохранились.
- Регрессия: `python -m unittest discover -s tests -p "test_*.py"` (ожидаем те же известные
  падения `test_multi_provider` по окружению — см. [`workflow/step_2.md`](workflow/step_2.md:135));
  `py_compile` всех изменённых модулей; парсер PowerShell для `START_ALL.ps1`.

### Шаг 6. Документация
- Отчёт `workflow/step_3.md` по образцу [`workflow/step_2.md`](workflow/step_2.md) (дата, модель,
  статус, решения, таблицы, проверки, «как запустить», ограничения, что дальше).
- Обновить статус Этапа 2.2 в [`plans/database_structure.qmd`](plans/database_structure.qmd:183).

---

## 6. Порядок выполнения и зависимости

```
Шаг 1 (DDL) → Шаг 2 (импорт) → Шаг 3 (REST) → Шаг 4 (UI) → Шаг 5 (тесты) → Шаг 6 (docs)
```

- Шаги 1–2 можно проверять до UI (консольные проверки/самопроверка).
- Шаг 3 зависит от Шага 1 (CRUD) и Шага 2 (данные).
- Шаг 4 зависит от Шага 3 (маршруты) и перегенерации контракта.
- Шаг 5 идёт параллельно/после каждого шага; финальный прогон — после Шага 4.

---

## 7. Риски и открытые вопросы

| № | Риск/вопрос | Митигация/решение |
|---|---|---|
| 1 | Семантика условных столбцов классификатора (N–AG, AM, AU, CI) неоднозначна | Храним `condition_text` + `value` как есть (проектное решение №6); отображение на фронте — «условие → значение» |
| 2 | Объём импорта (1283 записи + связи, единая транзакция) | Simple Query порциями; при необходимости — Extended Query (задел из [`workflow/step_2.md`](workflow/step_2.md:187)); измерения на живом стенде |
| 3 | `ui/geo/map.json` (дороги/граница) может иметь другую структуру | Анализ на этапе реализации; по умолчанию импортируем только `addresses.json` |
| 4 | Удаление справочных значений, на которые ссылаются записи | FK `ON DELETE RESTRICT` + понятное сообщение 409 в API |
| 5 | Изменение справочника не должно ломать учебные данные | Справочники ссылочно независимы от `task/session` (снимки JSONB); целостность — на уровне импорта и FK |
| 6 | Бэкенд-валидация правок (дубли, пустые значения) | Unique-индексы + проверки в `catalog_service` перед записью |

---

## 8. Критерии готовности (Definition of Done)

- [ ] Все таблицы раздела 2 созданы с индексами и внешними ключами; в `schema_migration`
      зафиксирована версия `2.2.0`; повторный запуск `ensure_schema()` безопасен.
- [ ] Импорт классификатора: `service`=61, `classifier_category`=24, `classifier_entry`=1283,
      `classifier_entry_service`>0; повторный запуск не создаёт дублей.
- [ ] Geo-импорт (`--geo`) заполняет `geo_address`/`geo_building` из
      [`ui/geo/addresses.json`](ui/geo/addresses.json).
- [ ] Маршруты `/catalog/*` работают под админом (200), недоступны студенту (403), валидируют
      вход (400/404/409).
- [ ] В админке есть вкладка «Справочники» в левом меню; изменение списков сохраняется в БД
      (проверено перезагрузкой страницы).
- [ ] Юнит- и интеграционные тесты зелёные; регрессия не хуже состояния до этапа; отчёт
      `workflow/step_3.md` написан.
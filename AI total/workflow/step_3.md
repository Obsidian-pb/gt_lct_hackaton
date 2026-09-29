# Шаг 3. Этап 2.2. Инициализация схемы данных и справочников

**Дата:** 2026-09-29 (09:00–10:35 UTC+7)
**Модель:** Roo Code (режим code)
**Статус:** реализовано, проверено на живом сервере БД PostgreSQL 14.2
**Источник плана:** [`plans/step_2_2_plan.md`](../plans/step_2_2_plan.md)
**Предыдущие шаги:** [`workflow/step_1.md`](step_1.md) (подключение), [`workflow/step_2.md`](step_2.md) (Этап 2.1, пользователи/JWT)

---

## 1. Постановка задачи (из `plans/database_structure.qmd`, этап 2.2)

1. Создать таблицы по разделу 2 документа (справочники, мастерская карточек, учебный
   каталог, сценарии/тренировки, сессии/оценивание, служебные), индексы и внешние ключи.
2. Импортировать статические справочники из `catalog/classifier.json` (`service`,
   `classifier_category`, `classifier_entry`, `classifier_entry_service`); при необходимости
   `geo_address`/`geo_building` из `ui/geo/*.json`.
3. Добавить в админку вкладку «Справочники» в левом меню со списками и редактированием
   (сохранение в БД).

### ВАЖНО
Логика работы с geo-данными (geojson-файлы) не менялась: ни фронт, ни бэкенд.
Гео-импорт в БД выполняется только по флагу `--geo` и не влияет на существующие
`/geo/addresses` и `/geo/map` (они по-прежнему читают `ui/geo/*.json`).

---

## 2. Ключевые проектные решения

1. **Версия схемы `2.2.0`.** Весь DDL раздела 2 размещён в `SCHEMA_STATEMENTS` модуля
   [`catalog_repository.py`](../catalog_repository.py) (порядок с учётом FK: справочники →
   мастерская → задания → сценарии/тренировки → сессии → служебные). `ensure_schema()`
   идемпотентен (`CREATE TABLE IF NOT EXISTS`), версия фиксируется в `schema_migration`.
2. **Натуральные строковые ключи** для сущностей с устоявшимися форматами файлов:
   `task.id` (`t-…`), `session.id` (`s-…`), `scenario.id`, `training.id`, `training_card.id`
   (`card-…`), `material.id`, а также коды классификатора (`service.code`, `classifier_entry.id`,
   `geo_address.id`). Новые сущности (мастерская, оценки, реплики, связи) — `bigint GENERATED
   ALWAYS AS IDENTITY` как в `auth_repository`.
3. **Гибкие поля — JSONB**: `workshop_card.fields/class_ids/services/flags/provenance/...`,
   `task.fields/field_labels`, `task_dds.incoming_card/actions`,
   `task_incident_source.content/reference/caller_scenario`,
   `session.task_snapshot/card/training_meta/forced_finish`, `ai_assessment_field.evidence`,
   `workshop_card_reference.source_content/answer`, `workshop_card_version.snapshot/review`,
   `workshop_card_event.payload`, `geo_address.point` и т.п.
4. **CHECK-ограничения** статусов (`session`, `training_card`, `training`, `scenario`, `task`,
   `workshop_card`), ролей (`training_participant.role`), вердиктов
   (`ai_assessment_field.verdict`), решений (`teacher_decision_field.decision`),
   `teacher_decision.grade BETWEEN 2 AND 5`, сложностей и форматов.
5. **Справочники пересоздаются транзакционно** (`TRUNCATE ... RESTART IDENTITY` + вставка
   порциями по 500 строк одной транзакцией) — стратегия «полная перезапись», повторный
   запуск идемпотентен. Гео-импорт — только по флагу `--geo`.
6. **Маппинг `classifier.json`** ([`tools/import_classifier.py`](../tools/import_classifier.py)):
   `services` (61) → `service(code,name)`; `categories` (24) → `classifier_category(id,name)`;
   `entries[]` (1283) → `classifier_entry` (`main_service_code` = `main_service` либо первый из
   `services`, `NULL` при отсутствии); `entries[].rules[]` → `classifier_entry_service`
   (`condition_type='column'`, `condition_text` — заголовок условия, `value` — значение ячейки,
   `is_main` — код входит в `entry.services`). Итог: **22 489 связей**.
7. **REST `/catalog/*` — только админ**: `storage=False`, `auth='admin'`; JWT-middleware и
   RBAC переиспользованы из Этапа 2.1. Пути `/api/v1/catalog/*` освобождены от legacy-токенов
   в [`web_ui.py`](../web_ui.py) (как `/auth/*`).
8. **Фронтенд**: пункт меню `['catalog','▦','Справочники']` и `CatalogDrawer` с вкладками
   «Службы», «Категории», «Записи классификатора», «Связи записей», «Гео-адреса»;
   панели по образцу `GroupPanel`/`UsersDrawer`: поиск, форма добавления, inline-правка,
   удаление с `confirm`; все запросы с `authHeaders()`.
9. **Индексы** — раздел 6 документа плюс индексы по всем FK и частым фильтрам.
10. **Исправлен латентный баг `db_connection.__enter__`**: `connect_from_config()` уже
    устанавливает соединение, а `with connection:` вызывал `connect()` повторно — второй сокет
    не закрывался (утечка по одному соединению на каждый вызов репозитория). Добавлена защита
    `if self._sock is None: self.connect()`; ResourceWarning-ы исчезли, интеграционные тесты
    auth (7 шт.) подтвердили отсутствие регрессии.

---

## 3. Таблицы БД (DDL в `catalog_repository.SCHEMA_STATEMENTS`, версия 2.2.0)

| Группа | Таблицы |
|---|---|
| Справочники (2.1) | `service`, `classifier_category`, `classifier_entry`, `classifier_entry_service`, `geo_address`, `geo_building` |
| Мастерская (2.2) | `workshop_card`, `workshop_card_reference`, `workshop_card_version`, `workshop_card_event`, `workshop_card_dialogue` |
| Учебный каталог (2.3) | `task`, `task_dds`, `task_incident_source` |
| Сценарии/тренировки (2.4) | `scenario`, `scenario_task`, `training`, `training_scenario`, `training_participant`, `training_card`, `training_service_action`, `material` |
| Сессии/оценивание (2.5) | `session`, `session_turn`, `session_hint`, `session_card_edit`, `session_reveal`, `machine_assessment`, `ai_assessment`, `ai_assessment_field`, `teacher_decision`, `teacher_decision_field` |
| Служебные (2.6) | `ai_generation_log`, `insight_report` |

Таблицы Этапа 2.1 (`user`, `student_group`, `group_member`, `auth_session`, `schema_migration`)
не изменялись.

---

## 4. Созданные/изменённые файлы

Новые модули бэкенда:

| Файл | Роль |
|---|---|
| [`catalog_repository.py`](../catalog_repository.py) | DDL версии 2.2.0 + CRUD справочников + `replace_classifier`/`replace_geo` (транзакционная перезапись) |
| [`catalog_importer.py`](../catalog_importer.py) | Чистый парсинг `classifier.json` и `ui/geo/addresses.json` (без БД) |
| [`catalog_service.py`](../catalog_service.py) | Бизнес-логика REST `/catalog/*`: валидация, 404/409/422, `CatalogError` |
| [`init_catalog.py`](../init_catalog.py) | `--init [--geo] --check --self-test --pause`, exit 0/2 |
| [`TEST_CATALOG.cmd`](../TEST_CATALOG.cmd) | Ручной запуск `--init --self-test --pause` |

Изменённые файлы: [`db_connection.py`](../db_connection.py) (фикс двойного connect),
[`api_contract.py`](../api_contract.py) (типы и 20 маршрутов `/catalog/*` с `auth='admin'`),
[`application.py`](../application.py) (диспетчеризация `catalog_*`),
[`rest_api.py`](../rest_api.py) (`CatalogError` → `APIError`; поддержка типа `number` в валидации),
[`web_ui.py`](../web_ui.py) (освобождение `/catalog/*` от legacy-токенов),
[`START_ALL.ps1`](../START_ALL.ps1) (некритичный шаг «Initializing the catalog layer…»,
лог `.runtime\catalog-init.log`), [`frontend/src/Admin.jsx`](../frontend/src/Admin.jsx)
(пункт меню + `CatalogDrawer`), [`ui/admin.css`](../ui/admin.css) (стили длинных таблиц).
Перегенерированы: `openapi.json`, `ui/api-routes.js` (`python build_api_contract.py`).

Новые тесты: [`tests/test_catalog_importer.py`](../tests/test_catalog_importer.py) (unit, 4),
[`tests/test_catalog_integration.py`](../tests/test_catalog_integration.py) (живая БД, 9, скип при
недоступности).

API-маршруты этапа (все `auth='admin'`): `GET|POST /catalog/services`,
`PUT|DELETE /catalog/services/{service_code}`, `GET|POST /catalog/categories`,
`PUT|DELETE /catalog/categories/{category_id}`, `GET|POST /catalog/entries`,
`PUT|DELETE /catalog/entries/{entry_id}`, `GET|POST /catalog/entry-services`,
`PUT|DELETE /catalog/entry-services/{entry_service_id}`, `GET|POST /catalog/geo-addresses`,
`PUT|DELETE /catalog/geo-addresses/{address_id}`. Дополнительные фильтры GET:
`entries?category_id=`, `entry-services?entry_id=&service_code=`, `geo-addresses?kind=&limit=`.

---

## 5. Проверки и их результаты

### 5.1 Инициализация и импорт (init_catalog.py)
```
[CATALOG] Проверка: Слой справочников готов: схема 2.2.0; services=61, categories=24, entries=1283, entry_services=22489.
[CATALOG] Инициализация: Схема 2.2.0 создана; классификатор: службы=61, категории=24, записи=1283, связи=22489. Geo: адреса=2549, здания=2129.
[CATALOG] Самопроверка: Чтение выборки из всех таблиц справочников через CRUD-методы прошло.
```
Повторный `--init` не дублирует данные (стратегия полной перезаписи).

### 5.2 Интеграционные тесты (живая БД)
`python -m unittest tests.test_catalog_importer tests.test_catalog_integration tests.test_auth_integration`

- Unit: маппинг классификатора (службы/категории/записи/правила, `is_main`, fallback главной
  службы) и гео-файла (lat/lon, разделение зданий) — **4/4 OK**.
- Integration catalog (9): идемпотентность `ensure_schema()` и импорта (61/24/1283),
  гео-импорт, RBAC студента 403, отсутствие токена 401, CRUD служб/категорий/записей/связей/
  гео-адресов, каскадное удаление связей при удалении записи, блокировка удаления службы 101
  (409 `reference_in_use`), валидация FK категории (404).
- Integration auth (7): повторный прогон после правки `db_connection` — **все OK**.

### 5.3 Регрессия
`python -m unittest discover -s tests -p "test_*.py"` — **149 тестов**: проходят все, кроме
известных `test_multi_provider` (30 ошибок по окружению: `patch.dict(os.environ, clear=True)`
ломает `Path.home()` на Windows — файлы `provider.py`/`test_multi_provider.py` не менялись).
Единственный дополнительный прогонный артефакт — `test_rest_api.openapi_matches...` при запуске
без `PYTHONUTF8=1` читает UTF-8 `openapi.json` локальной кодировкой cp1251; под `PYTHONUTF8=1`
(как в `TEST_*.cmd`) тест проходит, документ корректен.

Статические проверки: `py_compile` всех изменённых модулей — OK; парсер PowerShell для
`START_ALL.ps1` — `POWERSHELL_SYNTAX_OK`; `openapi.json` содержит 10 путей `/catalog/*`,
`ui/api-routes.js` — 20 операций.

### 5.4 Фронтенд
Локальная сборка бандла не выполнялась (нет `frontend/node_modules`/esbuild — замечание из
`workflow/step_2.md`); сборка штатно выполняется `BUILD_UI.cmd` на машине деплоя. Исходники
`Admin.jsx` и контракт маршрутов обновлены, JSX проверен линтером без ошибок.

---

## 6. Как запустить

| Сценарий | Действие |
|---|---|
| Ручная инициализация + самопроверка | двойной клик `TEST_CATALOG.cmd` |
| Инициализация/проверка из консоли | `python init_catalog.py --init --check --self-test` |
| С гео-адресами | `python init_catalog.py --init --geo` |
| Автоматически при старте | `START.cmd` → шаг «Initializing the catalog layer…» + `.runtime\catalog-init.log` |
| Правка справочников | браузер → `/admin-login` (admin/admin123) → «Справочники» → вкладка → правка → перезагрузка страницы |

После правки `api_contract.py` обязательна перегенерация: `python build_api_contract.py`.

---

## 7. Замечания и ограничения

1. **Geo-данные.** Логика работы приложения с geojson (`ui/geo/*.json`) не менялась.
   В БД адреса импортируются только по `--geo` в `geo_address`/`geo_building`
   (2549 адресов / 2129 зданий) для будущего этапа; `ui/geo/map.json` (дороги/граница)
   в отдельную таблицу не импортировался (по умолчанию плана — пропустить).
2. **CRUD гео-адресов** через админку работает только с таблицей `geo_address`;
   `geo_building` заполняется импортом (снимок `kind='building'`). Точка `point` правится
   повторным импортом.
3. **Подключение на каждый вызов** осталось по паттерну `data_layer`; пул соединений — следующая
   оптимизация. Утечка сокетов из-за двойного `connect()` в `__enter__` устранена.
4. **Simple Query без параметров** — значения через `quote_literal()`; Extended Query при
   массовых операциях — кандидат на хардненинг (объём импорта 22 489 связей уже влезает
   в единую транзакцию порциями по 500 строк).
5. **UI-бандл не пересобран локально** — на сервере выполнить `BUILD_UI.cmd` (или `START.cmd`,
   который собирает сам) и обновить страницу админки (Ctrl+F5).
6. **Справочники ссылочно независимы** от учебных данных (`task/session` хранят снимки JSONB);
   удаление служб/категорий, на которые ссылаются записи, блокируется FK (409).
7. Тест `test_rest_api` чувствителен к кодировке при запуске без `PYTHONUTF8=1` — рекомендация
   запускать регрессию как `TEST_*.cmd`/с `set PYTHONUTF8=1`.

---

## 8. Что дальше (Этап 3)

- Перенос учебных данных: `t-*.json` → `task` (+ `task_dds`, `task_incident_source`);
  `s-*.json` → `session` и связанные; `curriculum/*` → `scenario`/`training`; `materials.json` → `material`.
- При необходимости — Extended Query и пул соединений.
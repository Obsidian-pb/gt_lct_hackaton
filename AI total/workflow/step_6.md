# Шаг 6. Этап 5. Переключение репозитория: JSON-файлы → PostgreSQL

**Дата:** 2026-09-29
**Модель:** Roo Code (режимы architect → code)
**Статус:** реализовано, проверено на живом сервере БД PostgreSQL 14.2
**Источник плана:** [`plans/step_5_plan.md`](../plans/step_5_plan.md)
**Предыдущие шаги:** [`workflow/step_1.md`](step_1.md) (подключение), [`workflow/step_2.md`](step_2.md) (Этап 2.1, JWT), [`workflow/step_3.md`](step_3.md) (Этап 2.2, схема 2.2.0 и справочники), [`workflow/step_4.md`](step_4.md) (Этап 3, учебные данные, схема 2.3.0), [`workflow/step_5.md`](step_5.md) (Этап 4, мастерская — минимально)

---

## 1. Постановка задачи (из `plans/database_structure.qmd`, этап 5)

1. Ввести адаптер хранилища с тем же интерфейсом, что у
   `Engine.save/load/list_items` ([`ai_core.py`](../ai_core.py:56)): режимы
   «файлы → БД», затем «только БД».
2. Поэтапно переводить операции REST ([`api_contract.py`](../api_contract.py))
   на новый репозиторий **без изменения контрактов API**.
3. `config.local.json` (ключ ИИ) остаётся вне БД — это секрет.

Решение команды (2026-09-29): **самый большой скоуп** — адаптер + перевод на
БД заданий/сессий/сценариев/тренировок/материалов + мастерская карточек из БД +
**ролевая JWT-авторизация всех маршрутов** (student/teacher/admin).

---

## 2. Ключевые проектные решения

1. **Режимы хранилища** (`storage_config.py`): `files` (по умолчанию, легаси) →
   `files-to-db` (dual-write: файл + БД; чтение БД→fallback файл с зеркалированием) →
   `db-only` (БД — единственный источник истины). Настройка —
   `"storage": {"mode": …}` в `config.local.json` или env `STORAGE_MODE`.
   Дефолт `files` сохраняет все существующие тесты и стенды без БД.
2. **Конвертеры документ↔строки** ([`storage_documents.py`](../storage_documents.py)):
   чистые функции `task_to_rows/task_from_row`, `session_to_rows/session_from_row`
   (все 9 дочерних таблиц, `task_snapshot` — полный документ задачи),
   `scenario/training/material` в обе стороны. Переиспользуют парсер Этапа 3
   ([`training_data_importer.py`](../training_data_importer.py)).
3. **Репозиторий** ([`storage_repository.py`](../storage_repository.py)): upsert по
   натуральному ключу (`ON CONFLICT`), транзакции на каждый `save`, авто-upsert
   задачи из `task_snapshot` (FK `session.task_id`), резолв строковых имён через
   `legacy_name_map`/`display_name` с созданием пользователей (как Этап 3).
4. **Схема 2.4.0**: `ALTER workshop_card ADD COLUMN content jsonb, uid text`
   (+ unique по `number` и `uid`) — точный round-trip браузерного документа.
5. **Мастерская** ([`workshop_service.py`](../workshop_service.py) + `/workshop/*`):
   CRUD карточек, эталоны (версии), журнал событий, диалог заявителя, утверждение
   (снимок в `workshop_card_version`), повторное открытие, импорт **upsert-ом по
   `number`** (проектное решение №7).
6. **RBAC** (Этап 2.1 + расширение): каждому маршруту назначен `auth`
   (`student`/`teacher`/`admin`/`user`); enforcement — флаг
   `"auth": {"require_roles": true}` (или env `REQUIRE_ROLES`), маршруты
   `/auth/*`, `/catalog/*`, `/workshop/*` защищены всегда.
7. **Фронтенд**: гейт входа `RequireRole` (страницы студента/преподавателя/
   мастерской), токен через `/auth/login`; мастерская читает/пишет БД через
   `/workshop/*` (localStorage — кэш + однократный перенос по `number`).

---

## 3. Созданные/изменённые файлы

### Новые
| Файл | Роль |
|---|---|
| [`storage_config.py`](../storage_config.py) | Режим хранилища (дефолт → config.local.json → env) |
| [`storage_documents.py`](../storage_documents.py) | Чистые конвертеры документ↔строки |
| [`storage_repository.py`](../storage_repository.py) | Row-level CRUD (task/session/scenario/training/material/workshop), схема 2.4.0, резолв имён |
| [`storage_adapter.py`](../storage_adapter.py) | Адаптер интерфейса Engine + ресурсы curriculum/materials, режимы |
| [`workshop_service.py`](../workshop_service.py) | Бизнес-логика `/workshop/*` |
| [`init_storage.py`](../init_storage.py) | CLI `--init --check --self-test --mirror --pause`, exit 0/2 |
| [`TEST_STORAGE.cmd`](../TEST_STORAGE.cmd) | Ручной запуск `--init --self-test --check` |
| [`frontend/src/auth-gate.jsx`](../frontend/src/auth-gate.jsx) | Гейт входа по роли (JWT) |
| `tests/test_storage_documents.py` | Unit: round-trip конвертеров (9) |
| `tests/test_storage_integration.py` | Живая БД: task/session/curriculum/workshop (4) |

### Изменённые
[`ai_core.py`](../ai_core.py) (`Engine(storage=None)`, делегирование
save/load/list_items/exists + ресурсы), [`web_ui.py`](../web_ui.py) (адаптер из
конфига, `/workshop/*` и RBAC-пути вне X-UI-Token), [`api_contract.py`](../api_contract.py)
(маршруты `/workshop/*`, `auth` на всех маршрутах; перегенерированы `openapi.json`
и `ui/api-routes.js`), [`application.py`](../application.py) (диспетчеризация
`workshop_*`), [`rest_api.py`](../rest_api.py) (JWT-гейт по `require_roles`,
`WorkshopError`), [`curriculum.py`](../curriculum.py)/[`materials.py`](../materials.py)
(хранение через адаптер), [`incident_training.py`](../incident_training.py)
(`engine.exists` вместо проверки файла), [`auth_crypto.py`](../auth_crypto.py)/
[`auth_service.py`](../auth_service.py) (`require_roles`),
[`START_ALL.ps1`](../START_ALL.ps1) (некритичный шаг storage-check,
`.runtime\storage-init.log`), фронтенд: [`api.js`](../frontend/src/api.js)
(`attachToken`), [`workshop-store.js`](../frontend/src/workshop-store.js)
(синхронизация с БД + импорт localStorage), [`Cards.jsx`](../frontend/src/Cards.jsx),
[`Student.jsx`](../frontend/src/Student.jsx), [`Teacher.jsx`](../frontend/src/Teacher.jsx)
(ролевой гейт), [`plans/database_structure.qmd`](../plans/database_structure.qmd)
(статус Этапа 5).

---

## 4. Проверки и их результаты

### 4.1 Схема и живая самопроверка
```
python init_storage.py --init            → Схема 2.4.0 установлена
set STORAGE_MODE=db-only & python init_storage.py --self-test
→ [STORAGE] Самопроверка: round-trip task и session прошёл на живой БД.
```

### 4.2 Интеграционные тесты (живая БД)
`python -X utf8 -m unittest tests.test_storage_integration -v` — **4/4 OK**:
- task+session: upsert (идемпотентно), load, list, `exists_task`;
- curriculum: scenario (+scenario_task), training (+связи/карточки), material;
- мастерская: create → get → update → approve (версия) → reopen → delete;
- импорт карточек: **upsert по `number`** без задвоения.

### 4.3 Unit-тесты конвертеров
`python -X utf8 -m unittest tests.test_storage_documents` — **9/9 OK**: legacy/
dds/incident-v1 задачи, полная сессия (реплики/hints/edits/reveals/machine/ai/
решение), dds-флаги `delivered`, сценарий, тренировка, материал, `load_ts`
(формат PostgreSQL → ISO UTC).

### 4.4 Регрессия
`set PYTHONUTF8=1 && python -X utf8 -m unittest discover -s tests -p "test_*.py"`
— **184 теста**: проходят все, кроме известных 30 ошибок `test_multi_provider`
по причине окружения (`patch.dict(os.environ, clear=True)` ломает `Path.home()`
на Windows — файлы не менялись, задокументировано в [`workflow/step_2.md`](step_2.md)).
`test_rest_api` (в т.ч. сверка OpenAPI) — проходит.

### 4.5 Статические проверки
`python -m py_compile` всех новых/изменённых модулей — OK; `build_api_contract.py`
— openapi.json: **85 путей** (в т.ч. 5 `/workshop/*`), `ui/api-routes.js`
перегенерирован; синтаксис `START_ALL.ps1` не изменялся в опасных местах.

---

## 5. Как запустить / включить на стенде

```
1. python init_storage.py --check          # состояние
2. python init_storage.py --mirror         # (однократно) файлы → БД, если есть data/
3. config.local.json: { "storage": { "mode": "files-to-db" } }   # гибрид
4. START.cmd → проверить .runtime\storage-init.log
5. После накопления: mode: "db-only"
6. python init_storage.py --self-test      # round-trip
```
Мастерская: войти преподавателем (`/auth/login` под ролью teacher/admin,
создать пользователя в админке) → `/cards` работает из БД; при первом входе
карточки из `localStorage` переносятся в БД (upsert по `number`).
Ролевая авторизация: `"auth": { "require_roles": true }` в `config.local.json`
(или env `REQUIRE_ROLES=1`) + пересборка UI (`BUILD_UI.cmd`).

---

## 6. Замечания и ограничения

1. **UI-бандл локально не собран** (нет `frontend/node_modules`); сборка —
   штатным `BUILD_UI.cmd`/`START.cmd` на машине деплоя (как в шагах 2–3).
2. **`require_roles` по умолчанию выключен** — легаси-маршруты продолжают
   работать с X-UI-Token; включение требует JWT-входа и пересборки фронтенда.
3. **Пароли импортированных/созданных пользователей случайны** — выдаются
   администратором через админку.
4. **Два процесса без общего lock** (web_ui 8878 + выделенный REST 8890) могут
   гоняться на уровне БД — для стенда достаточно одного процесса; при росте —
   `SELECT … FOR UPDATE` в репозитории.
5. **Мастерская**: импорт из localStorage выполняется при каждом входе
   преподавателя (upsert по `number` — идемпотентен); синхронизация правок —
   fire-and-forget по изменённым карточкам.
6. **`data/` на стенде пуст** — импорт реальных данных (Этап 3) выполняется
   `TEST_DATA.cmd` там, где лежат `t-*.json`/`s-*.json`/`curriculum/*.json`.
7. **`legacy_name_map`** остаётся для переходного периода и аудита.

---

## 7. Что дальше (вне этапа 5)

- Расширенный пул соединений/Extended Query при росте нагрузки;
- аналитика поверх БД (`insight_report` кэш), выдача паролей студентам;
- удаление файлового хранилища после полного перехода на `db-only`;
- хардненинг RBAC: привязка `student`/`teacher` к реальным маршрутам и
  разграничение «своих» работ по `user_id`.
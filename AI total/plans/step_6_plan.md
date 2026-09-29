# План Этапа 6. Финализация перехода на БД: RBAC по user_id, аналитика, db-only

**Дата:** 2026-09-29
**Модель:** Roo Code (режим architect)
**Источник:** [`plans/database_structure.qmd`](database_structure.qmd) — разделы 5–6 и секции «Что дальше» отчётов
[`workflow/step_2.md`](../workflow/step_2.md), [`workflow/step_3.md`](../workflow/step_3.md),
[`workflow/step_4.md`](../workflow/step_4.md), [`workflow/step_5.md`](../workflow/step_5.md),
[`workflow/step_6.md`](../workflow/step_6.md)
**Предыдущие шаги:** [`workflow/step_1.md`](../workflow/step_1.md) (подключение),
[`workflow/step_2.md`](../workflow/step_2.md) (Этап 2.1, JWT, схема 2.1.0),
[`workflow/step_3.md`](../workflow/step_3.md) (Этап 2.2, схема 2.2.0 и справочники),
[`workflow/step_4.md`](../workflow/step_4.md) (Этап 3, учебные данные, схема 2.3.0),
[`workflow/step_5.md`](../workflow/step_5.md) (Этап 4, мастерская — минимально),
[`workflow/step_6.md`](../workflow/step_6.md) (Этап 5, переключение репозитория, схема 2.4.0)
**Отчёт по завершении:** `workflow/step_7.md`

---

## 1. Постановка задачи

В документе [`plans/database_structure.qmd`](database_structure.qmd) этапы 1–5 завершены.
«Этап 6» в документе не описан — он формируется по секциям «Что дальше» отчётов и по
решению команды (2026-09-29): **максимальный скоуп** — закрыть весь завершающий блок:

1. **Хардненинг RBAC**: привязка ролей student/teacher/admin к реальным маршрутам и
   разграничение «своих» работ по `user_id` (студент — только свои сессии, преподаватель —
   только свои группы/задания/тренировки, админ — всё).
2. **Аналитика поверх БД**: кэш обезличенных отчётов `insight_report`, мониторинг
   преподавателя из БД, массовая выдача паролей студентам.
3. **Завершение перехода на БД**: режим `db-only` как целевой единственный, удаление
   файлового хранилища из рабочего пути, пул соединений / Extended Query, завершение
   переходного периода `legacy_name_map`.

### Что уже есть (не переделывается)

| Область | Текущее состояние |
|---|---|
| JWT + роли | [`rest_api.py`](../rest_api.py:166) — middleware: `/auth/*`, `/catalog/*`, `/workshop/*` защищены всегда, остальные при `auth.require_roles=true`; `auth_service.require_role` ([`auth_service.py`](../auth_service.py:71)) |
| Контракт ролей | у всех маршрутов [`api_contract.py`](../api_contract.py:114) задан `auth='student'/'teacher'/'admin'/'user'` |
| Связь сессии с пользователем | `session.student_id` (FK → user), `training_participant.user_id`, `training_card.operator_session_id` (схема 2.2.0) |
| Резолв legacy-имён | `legacy_name_map` + `user.display_name` ([`storage_repository.py`](../storage_repository.py:191), [`storage_documents.py`](../storage_documents.py:283)) |
| Аналитика на лету | `reports_insights` ([`application.py`](../application.py:198)) грузит все сессии и зовёт ИИ; таблица `insight_report` (схема 2.2.0) пуста |
| Хранилище | режимы files / files-to-db / db-only ([`storage_config.py`](../storage_config.py:21)), адаптер [`storage_adapter.py`](../storage_adapter.py:38) |
| Соединения | [`db_connection.py`](../db_connection.py:144) — Simple Query + `quote_literal`, новое соединение на каждый вызов репозитория |

---

## 2. Ключевые проектные решения

### 2.1. Идентификация «кто я» на маршрутах

JWT-user ↔ legacy-строка в документах сопоставляется по правилу (фиксируется решением
команды): **`user.display_name` → `user.login` → `user.full_name`**. Для студенческих
маршрутов параметр `{student}` сравнивается с этим именем; для преподавательских —
`teacher` из `task.approved_by` / `training.teacher` / заметок. При несовпадении — 403
`wrong_owner`, не 404 (не раскрываем существование чужих данных).

### 2.2. Разграничение «своих» работ на уровне данных

Фильтрация выполняется в [`application.py`](../application.py) / `teacher_portal` через
`payload['_auth_user']` (уже кладётся middleware-ом в [`rest_api.py`](../rest_api.py:175))
и новые методы репозитория (SQL-проекции, без загрузки полных документов):

| Роль | Видит | Реализация |
|---|---|---|
| `student` | сессии, где `session.student_id = user.id` | `list_sessions(owner=user_id)` — `WHERE student_id = …` |
| `teacher` | сессии/задания/тренировки своих учеников и свои | группы по `student_group.teacher_id`, тренировки по `training.teacher_id`, задания по `task.approved_by_id`; fallback на display_name для legacy-строк |
| `admin` | всё без фильтра | фильтр не применяется |

Строковые поля (`student`, `teacher`) в ответах сохраняются (контракты не меняются):
`name_of(user_id)` из `display_name` уже реализован в [`storage_documents.py`](../storage_documents.py:284).

### 2.3. `require_roles` становится обязательным

Флаг `auth.require_roles` переводится в **постоянно включённый** (дефолт `true` вместо
`false`), legacy-проверка `X-UI-Token` для доменных маршрутов отключается. Остаётся
запасной путь: `"auth": {"require_roles": false}` для локальных тестов без БД.

### 2.4. Аналитика: кэш `insight_report` + SQL-проекции

- `reports_insights`: ключ `(group_name|'*', period=YYYY-MM-DD)`. При запросе:
  1. если в `insight_report` есть свежая запись и максимальный `session.updated_at`
     не изменился — вернуть кэш;
  2. иначе пересчитать агрегаты (Python по проекции сессий), вызвать ИИ, upsert в
     `insight_report` (версия схемы **2.5.0**: unique-индекс `(group_name, period)`).
- Dashboard преподавателя переводится с `engine.list_items('s')` на проекцию
  `list_sessions_summary(...)` (без `task_snapshot`/`card` — только статусы, проценты,
  длительности, поля для фильтров) — это снимает главную нагрузку при росте данных.
- Новая таблица не нужна, `insight_report` уже в схеме 2.2.0
  ([`catalog_repository.py`](../catalog_repository.py:462)).

### 2.5. Выдача паролей студентам

- Эндпоинт `POST /auth/users/reset-passwords` (admin): принимает список `user_id`
  (или `group_id`) и режим — «задать один пароль» / «сгенерировать случайные».
  Ответ — массив `{user_id, login, display_name, password}` (одноразово, больше нигде
  не сохраняется; в БД только PBKDF2-хэш).
- Кнопка «Сбросить пароли» в админке (группа/выборка) + экспорт результата
  `.csv`/`.txt` для выдачи студентам.

### 2.6. Пул соединений и параметризованные запросы

- В [`db_connection.py`](../db_connection.py) добавляется **Extended Query**
  (`execute_params(sql, params)` — Parse/Bind/Execute, text format) — устранение
  экранирования через `quote_literal` в горячих операциях.
- **Thread-local кэш соединения** в репозиториях: одно соединение на поток вместо
  connect/close на каждый вызов (общий пул с блокировками — на следующий этап,
  при росте). Закрытие — по завершении потока сервера.
- Переводятся на `execute_params` сначала `auth_repository` и `storage_repository`
  (hot path), затем `catalog_repository` — без изменения поведения.

### 2.7. Целевой режим `db-only` и завершение переходного периода

- `storage_config.DEFAULT_MODE` → `'db-only'`; режимы `files`/`files-to-db`
  помечаются deprecated (остаются только для миграции и тестов).
- Файловые ветки `StorageAdapter` (`_file_*`, `_resource_file`, `_materials_file`)
  исключаются из рабочего пути: при `db-only` обращения к файлам не происходит.
- `data/*.json` и `data/curriculum/*.json` — архив/аудит, не читаются приложением.
- `legacy_name_map` **не удаляется** (нужна для обратного резолва старых строк и
  аудита), но перестаёт пополняться: новые пользователи создаются через `/auth/users`.
- `START_ALL.ps1`: шаг `init_storage.py --check` становится **критичным** (БД обязательна);
  добавляется `init_insights.py --check` (некритично).

### 2.8. Фронтенд

- `RequireRole` ([`auth-gate.jsx`](../frontend/src/auth-gate.jsx:52)) уже работает;
  добавляется: страница преподавателя «Аналитика» (таблица `insights`), кнопка сброса
  паролей в админке, отображение `display_name` в списках, авто-выход при 401.
- Студент входит по логину (translit имени) и видит только свои работы — гейт
  дополняется показом ошибки 403 вместо пустых списков.

---

## 3. Целевая архитектура

```{mermaid}
flowchart LR
    UI[Браузер React] --> API[REST /api/v1]
    API --> JWT[JWT middleware require_roles всегда включён]
    JWT --> OWNER[Проверка владельца по user_id]
    OWNER --> APP[application.dispatch]
    APP --> REPO[StorageRepository SQL-проекции и фильтры]
    REPO --> DB[(PostgreSQL 14)]
    APP --> INS[InsightsService кэш insight_report]
    INS --> DB
    ADMIN[Админка] --> AUTH[auth-service сброс паролей]
    AUTH --> DB
    CONN[db_connection Extended Query + thread-local пул]
    CONN --> REPO
    CONN --> AUTH
```

Слои:
1. `auth_service`/`auth_repository` — владелец, сброс паролей, `require_roles` default true;
2. `storage_repository`/`storage_adapter` — проекции, фильтры владельца, режим `db-only`;
3. `insights_service` — кэш `insight_report`, инвалидация;
4. `application`/`teacher_portal` — проброс `_auth_user` в бизнес-логику;
5. `db_connection` — Extended Query, thread-local соединение;
6. фронтенд — аналитика, сброс паролей, обработка 401/403.

---

## 4. Фазы реализации

### Фаза 0. Подготовка и фикстуры

- Зафиксировать состояние: `init_catalog.py --check`, `init_storage.py --check`,
  `init_auth.py --check`; версия схемы 2.4.0.
- Права БД на DDL (ALTER/INDEX) — подтвердить (как в Этапе 2.1).
- Фикстуры: пользователи student/teacher/admin + группы; сессии разных студентов;
  тренировки разных преподавателей (для unit/integration тестов владельца).

### Фаза 1. Хардненинг RBAC и разграничение «своих» работ

1. `auth_service`:
   - функция `owner_key(user) -> str|None` (display_name → login → full_name);
   - `require_owner(user, owner_key)` → 403 `wrong_owner` при несовпадении и роли не admin.
2. `storage_repository`:
   - `list_sessions(owner=user_id|None, teacher=user_id|None)` — SQL `WHERE student_id=…`
     либо JOIN групп преподавателя;
   - `list_tasks(owner=…)`, `list_trainings(owner=…)`, `list_scenarios(owner=…)`,
     `list_materials(owner=…)` — фильтры по `approved_by_id`/`teacher_id`/`created_by_id`;
   - проекция `list_sessions_summary(...)` для dashboard (без `task_snapshot`/`card`).
3. [`rest_api.py`](../rest_api.py:166): `require_roles()` трактуется как включённый
   (решение 2.3); `_auth_user` прокидывается в `dispatch` (уже прокидывается).
4. [`application.py`](../application.py) / [`teacher_portal.py`](../teacher_portal.py:19):
   - student-маршруты: `p['student']` обязан совпадать с `owner_key(_auth_user)`;
   - teacher-маршруты: фильтрация списков по владельцу; прямое чтение чужой работы —
     403;
   - admin: фильтры не применяются.
5. Интеграционные тесты: student → чужая сессия 403; teacher → чужие работы скрыты;
   admin видит всё; совпадение по display_name/login.

### Фаза 2. Выдача паролей студентам

1. `auth_repository`: `list_users(role='student')`, `list_group_members(group_id)`.
2. `auth_service`: `reset_passwords(ids, password|None)` — генерация `secrets.token_urlsafe`,
   PBKDF2-хэш, возврат одноразовых паролей.
3. Маршрут `POST /auth/users/reset-passwords` (`auth='admin'`, storage=False)
   в [`api_contract.py`](../api_contract.py:191); перегенерация `openapi.json`
   (`python build_api_contract.py`).
4. Фронтенд: кнопка в «Пользователи и доступ» (группа → сбросить, выгрузить CSV).

### Фаза 3. Аналитика поверх БД

1. Новый `insights_service.py`:
   - `get_insights(group, force=False)` — проверка кэша `insight_report`
     `(group_name, period, max_session_updated_at)`; пересчёт + ИИ при устаревании;
   - upsert в `insight_report` (схема **2.5.0**: `UNIQUE (group_name, period)`,
     индекс по `created_at`);
   - перевод текущей логики из [`application.py`](../application.py:198).
2. `teacher_portal.overview` → чтение через `list_sessions_summary` (проекция);
   добавление агрегатов: распределение статусов, средние `ai_percent/final_percent`,
   группы, длительности.
3. CLI `init_insights.py --check` + некритичный шаг в `START_ALL.ps1`.
4. Фронтенд: вкладка «Аналитика» у преподавателя (таблица ошибок по полям, summary,
   recommendations; кнопка «Обновить»).

### Фаза 4. Пул соединений и Extended Query

1. [`db_connection.py`](../db_connection.py): `execute_params(sql, params)` —
   Parse/Bind/Execute (text format), повторное использование PreparedStatement
   не требуется (имена анонимные).
2. Thread-local кэш соединения: `connection_local()` в `db_connection` или обёртка
   в репозиториях (`_connect()` → `with pooled_connection():`); закрытие при
   завершении потока.
3. Перевод hot-path запросов `auth_repository`/`storage_repository` на `execute_params`
   (параметры вместо `quote_literal`) — поведение не меняется, unit-тесты без БД
   остаются на конвертерах.
4. Проверка утечек сокетов (как в Этапе 2.2 — ResourceWarning) интеграционными тестами.

### Фаза 5. Режим `db-only` и завершение переходного периода

1. [`storage_config.py`](../storage_config.py:17): `DEFAULT_MODE='db-only'`;
   `files`/`files-to-db` — deprecated, допустимы только через env/конфиг для миграции.
2. [`web_ui.py`](../web_ui.py:293): при `db-only` сервер **не стартует** без доступной БД
   (уже реализовано для db-режимов) — проверка становится безусловной.
3. [`storage_adapter.py`](../storage_adapter.py): файловые ветки помечаются
   `deprecated`, при `db-only` недостижимы (упрощение: убрать вызовы, оставить методы
   как задел для миграции `--mirror`).
4. `init_storage.py`: `--mirror` остаётся для разового переноса; `--self-test`
   прогоняется в `db-only`.
5. `legacy_name_map`: перестать создавать записи (новые пользователи через
   `/auth/users`); обратный резолв — только по `user.display_name`.
6. Статус Этапа 6 в [`plans/database_structure.qmd`](database_structure.qmd),
   отчёт [`workflow/step_7.md`](../workflow/step_7.md).

### Фаза 6. Фронтенд (финал)

1. Обработка 401 (auto-logout) и 403 (сообщение «нет доступа») в [`api.js`](../frontend/src/api.js).
2. Вкладка «Аналитика» (преподаватель), кнопка «Сбросить пароли» (админ) — п. Фазы 2/3.
3. Показ `display_name` студента в шапке; гейт `RequireRole` — без изменений контрактов.

---

## 5. Новые и изменяемые файлы

### Новые
| Файл | Роль |
|---|---|
| `insights_service.py` | Кэш `insight_report`, инвалидация, агрегаты, вызов ИИ |
| `init_insights.py` | CLI `--check --self-test --pause`, exit 0/2 |
| `tests/test_rbac_owner.py` | Unit: owner_key, фильтры владельца (без БД) |
| `tests/test_insights_service.py` | Unit: инвалидация кэша, агрегаты |
| `tests/test_reset_passwords.py` | Unit: генерация/хэширование паролей |

### Изменяемые
| Файл | Изменение |
|---|---|
| `db_connection.py` | `execute_params` (Extended Query), thread-local соединение |
| `auth_service.py`, `auth_repository.py` | `owner_key`, `require_owner`, `reset_passwords`, `list_users/list_group_members` |
| `api_contract.py` | `POST /auth/users/reset-passwords`; перегенерация `openapi.json`, `ui/api-routes.js` |
| `rest_api.py` | `require_roles` всегда включён; проброс `_auth_user` (есть) |
| `storage_repository.py`, `storage_adapter.py`, `storage_config.py` | Проекции/фильтры владельца, `DEFAULT_MODE='db-only'`, deprecated-файлы |
| `application.py`, `teacher_portal.py` | Проверка владельца на student/teacher маршрутах; dashboard на проекции |
| `START_ALL.ps1` | Шаг storage-check критичный; шаг insights-check некритичный |
| `frontend/src/Admin.jsx`, `Teacher.jsx`, `api.js` | Сброс паролей, вкладка «Аналитика», обработка 401/403 |
| `plans/database_structure.qmd` | Статус Этапа 6, проектные решения |
| `workflow/step_7.md` | Новый отчёт |

---

## 6. Тесты и проверки

| Уровень | Что проверяется |
|---|---|
| Unit (конвертеры/сервисы) | `owner_key` по display_name/login/full_name; агрегаты insights; инвалидация по `max(updated_at)`; генерация паролей (PBKDF2 roundtrip) |
| Integration (живая БД) | Student не читает чужую сессию (403); teacher видит только свои группы/задания; admin — всё; `reset_passwords` для группы; upsert `insight_report` идемпотентен; `list_sessions_summary` без `task_snapshot`; Extended Query roundtrip; thread-local соединение не течёт (ResourceWarning нет) |
| Регрессия | `set PYTHONUTF8=1 && python -X utf8 -m unittest discover -s tests -p "test_*.py"` — известные 30 ошибок `test_multi_provider` вне scope |
| Ручной сценарий | `TEST_STORAGE.cmd` (db-only); полный цикл: вход студента → работа → проверка преподавателем → аналитика → сброс пароля |

---

## 7. Порядок включения на стенде

```
1. python init_storage.py --check          # схема 2.4.0 + данные
2. config.local.json: { "storage": { "mode": "files-to-db" } }  # переходно
3. START.cmd → проверить .runtime\storage-init.log
4. Накопительная проверка → mode: "db-only" (новый дефолт)
5. python init_insights.py --check         # аналитика
6. Админка: сбросить пароли студентам → выдать
7. Проверка RBAC: студент видит только свои работы; преподаватель — свою группу
```

---

## 8. Риски и ограничения

1. **Разграничение преподавателя по legacy-строкам**: старые тренировки/задания хранят
   `teacher` строкой; сопоставление с `user_id` возможно только через `display_name`
   и `legacy_name_map` — возможны пропуски (fallback: admin видит всё).
2. **Extended Query на stdlib** — заметная работа с wire-протоколом (Parse/Bind/Execute);
   основной риск этапа. Смягчение: внедряется после RBAC/аналитики, отдельным
   коммитом, покрывается интеграционными тестами на живую БД.
3. **`require_roles` обязателен** — без JWT-входа легаси-клиенты (X-UI-Token) перестают
   работать на доменных маршрутах; требуется пересборка UI (`BUILD_UI.cmd`).
4. **Кэш `insight_report`** может устареть между правками сессий — инвалидация по
   `max(session.updated_at)` и кнопка «Обновить».
5. **Thread-local соединение** живёт жизнью потока сервера; при `daemon_threads`
   закрытие выполняется при завершении процесса — допустимо для стенда.
6. **`data/` на стенде пуст** — реальный импорт (Этап 3) выполняется `TEST_DATA.cmd`
   там, где лежат файлы; на стенде фикстуры через тесты.
7. **Одноразовые пароли** выводятся только в ответе эндпоинта сброса; повторный запрос
   их не возвращает (в БД только хэш).

---

## 9. Открытые вопросы (нужно решение команды)

1. **`require_roles`**: подтвердить постоянное включение (дефолт true) либо оставить
   флаг `auth.require_roles` в конфиге с дефолтом true (рекомендуется).
2. **Сопоставление имени**: правило `display_name → login → full_name` — подтвердить;
   для студентов с пустым display_name использовать login.
3. **Границы преподавателя**: строго по группам (`student_group.teacher_id`) +
   свои задания/тренировки, или с fallback на `display_name` для legacy-данных?
4. **Пул соединений**: thread-local (простой, этот этап) vs общий пул с блокировкой
   (следующий этап) — подтвердить.
5. **`insight_report`**: период кэша — сутки или «до изменения данных» (рекомендуется)?
6. **Файловые ветки адаптера**: удалять код `files`/`files-to-db` совсем или оставить
   deprecated для миграции (`--mirror`)?
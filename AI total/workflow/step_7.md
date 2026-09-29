# Отчёт. Этап 7: усиление RBAC — JWT по умолчанию и владение по user_id

**Дата:** 2026-09-29
**Основание:** отдельное задание на исправление RBAC (утверждено: «Ок. Выполни этот план»),
разделы 2.1–2.3 [`plans/step_6_plan.md`](../plans/step_6_plan.md).
**Скоуп:** JWT/RBAC по умолчанию; проверка владения по `user_id` вместо `display_name`;
изоляция пользователей с одинаковыми именами; роли `student`/`teacher`/`admin`; регрессионные тесты.
**Вне скоупа:** аналитика (`insight_report`), фронтенд, массовая SQL-параметризация, удаление файлового хранилища.
**Изменения не коммичены** — рабочее дерево сохранено; незакоммиченные правки пользователя не тронуты.

---

## 1. Что сделано

### 1.1. JWT обязателен по умолчанию

| Файл | Изменение |
|---|---|
| `auth_crypto.py` | `get_auth_config()`: `require_roles` теперь `true` по умолчанию. Явное отключение сохранено: `REQUIRE_ROLES=false` (env) или `auth.require_roles=false` в конфиге. |
| `rest_api.py` | Маршруты с `route.auth` требуют Bearer JWT при включённых ролях; `/auth/*`, `/catalog/*`, `/workshop/*` защищены всегда. `X-UI-Token` не заменяет JWT (401 `unauthorized`). Роль `admin` допускается на маршрутах любой роли: `require_role(user, (route.auth, 'admin'))`. |
| `tests/test_auth_crypto.py` | Тест дефолта и явных переопределений (env/конфиг). |

### 1.2. Владение по ID, а не по имени (`rest_api.authorize_owner`)

- admin пропускает проверки владения.
- `student`: параметр `{student}` из URL сверяется с JWT (`require_owner`) и затем перезаписывается
  каноническим ключом; `_owner_id = user.id`; сессии `s-*` — `session.student_id == user.id`
  (SQL `session_belongs_to` при БД, иначе файл с `student_id`), иначе 403 `wrong_owner`.
- `teacher`: `teacher` сверяется и перезаписывается; задания `t-*` — `task.approved_by_id`
  (`task_belongs_to`, файловый fallback `owner_id`); сессии `s-*` — `session_belongs_to_teacher`
  (автор задания, `training.teacher_id`, группа преподавателя) либо файловый fallback
  `training.teacher_id`/`task.owner_id`; сценарии/тренировки — `scenario_belongs_to`/`training_belongs_to`
  (файловый fallback `owner_id`/`teacher_id`); `task_ids` из `teacher_launch` проверяются поэлементно.
- Списки (`materials_list`, `reports_insights`, `scenario_list`, `training_list`, `tasks`,
  `teacher_overview`, `teacher_dashboard`, `works`) получают `_owner_id` и фильтруются на уровне данных.
- `training_save` при JWT: обязателен репозиторий с `resolve_students` (иначе 422), участники
  резолвятся в ID, дубли ID → 422 «Обучающийся указан повторно», клиентский
  `participants[].user_id` перезаписывается.

### 1.3. Резолвер пользователей (`storage_repository.py`)

- `_resolve_name`: SQL ищет `display_name`/`login`/`full_name` с `LIMIT 2`; две строки или
  конфликт с `legacy_name_map` → `ValueError('Имя неоднозначно; выберите уникальный логин пользователя.')`.
- Новые `resolve_student(name)` и `resolve_students(names)`: только `role='student'`,
  `is_active=TRUE`, требуется ровно одна строка («Укажите уникальный логин действующего обучающегося»).
- `upsert_training` отвергает `NULL user_id` у участника; `training_participant_belongs_to`
  и `list_training_desks` работают по `user_id`.

### 1.4. Документы хранят ID (`storage_documents.py`)

- Сохранение и восстановление: `task.approved_by_id → owner_id`, `session.student_id`,
  `teacher_note_by_id`, `teacher_decision.teacher_id`, `scenario.created_by_id/approved_by_id → owner_id`,
  `training.teacher_id`, `participants[].user_id`, `dds_by_id`, `material.teacher_id`.
- При наличии ID имя преподавателя повторно не резолвится — неоднозначное имя не ломает сохранение.
- `training_to_rows` фильтрует исходные строки участников по допустимой роли перед `zip`,
  чтобы ID не сместились при пропущенных ролях.

### 1.5. Назначение тренировок (`teacher_portal.py`, `curriculum.py`)

- `teacher_launch` при JWT (`_owner_id` задан): все студенты резолвятся в ID до записи, дубли ID
  отвергаются; ключ идемпотентности — `(task_id, student_id)`; сохраняются `session.student_id`
  и `training.teacher_id`. Повторный вызов возвращает те же сессии даже при совпадении имён студентов.
- `curriculum._participants`: допускает одинаковые `display_name` при разных `user_id`, запрещает
  дубль ID; `desk`/`route_card`/`service_action` опираются на `user_id`; `route_card` пишет
  `dds_by_id`; `complete(..., teacher_id)` сверяет ID владельца.

### 1.6. Заметки и итоговые решения преподавателя

- `teacher_portal.teacher_note` сохраняет `teacher_note_by_id` (из `_owner_id`).
- `ai_core.finalize/finalize_percent(..., teacher_id=None)` пишут `teacher_decision.teacher_id`;
  `application.dispatch` передаёт `_owner_id`.
- Конвертеры `storage_documents` отдают предпочтение ID: при неоднозначном имени резолвер не вызывается.

### 1.7. Прочее

- `incident_training.publish`: карточка получает `owner_id`; повторная публикация того же
  content-hash другим преподавателем → 403 `wrong_owner`.
- `materials.add` при JWT пишет `teacher_id`.
- `storage_adapter`/`ai_core`: файловые списки фильтруются по owner/teacher ID; DB-списки с owner
  не откатываются к нефильтрованным файлам (см. `tests/test_storage_adapter.py`).
- `application.student_action`: admin обходит внутреннюю сверку имени.

---

## 2. Тесты

Профильные прогоны — все зелёные:

| Файл | Тестов | Примечание |
|---|---|---|
| `tests/test_rest_api.py` | 28 | legacy `setUp` ставит `REQUIRE_ROLES=false`; JWT-тесты mock `roles_required=True` |
| `tests/test_storage_documents.py` | 11 | round trip с ID, «ID переопределяет неоднозначные имена» |
| `tests/test_teacher_portal.py` | 5 | идемпотентность по `user_id`, отказ алиасов одного студента |
| `tests/test_auth_crypto.py` | 15 | дефолт `require_roles`, PBKDF2/JWT |
| `tests/test_storage_adapter.py` | 5 | фильтрация списков по owner без фолбэка |
| `tests/test_teacher_projection.py` | 3 | SQL-резолвер: отказ двух одинаковых имён |
| `tests/test_curriculum.py` | 4 | legacy HTTP-тест явно отключает роли |
| `tests/test_core.py` | 13 | |
| `tests/test_incident_training.py` / `test_teacher.py` / `test_student.py` / `test_training_progress.py` | 3 / 1 / 3 / 3 | |
| `tests/test_dialogue_gateway_integration.py` | 1 | legacy маршрут явно без ролей |

Новые/переписанные тесты:

- `test_jwt_launch_keys_idempotency_by_user_id` — два студента с одинаковым `display_name`,
  разными логинами/ID: повторное назначение возвращает те же сессии (`student_id` 11/12), имя не влияет.
- `test_jwt_launch_rejects_aliases_for_same_student` — два алиаса одного студента → отказ,
  сессии не создаются.
- `test_teacher_note_and_decision_record_authenticated_user_id` — заметка и решение пишут ID из JWT.
- `test_teacher_cannot_access_foreign_session_with_same_display_name` — преподаватель не получает
  чужие задание/сессию при совпадении имён; его списки пусты.
- `test_required_roles_reject_ui_token_and_wrong_role` — без JWT 401 `unauthorized`;
  студент на учительском маршруте 403 `forbidden`.
- `test_admin_can_read_student_and_teacher_resources` — admin читает студента/преподавателя/задание.
- `test_teacher_ids_survive_ambiguous_names` — конвертеры не зовут резолвер, когда есть ID.

Известные внешние ограничения (вне этого задания):

- Ранний полный прогон: 214 тестов, 31 ошибка — 30× `test_multi_provider`
  («Could not determine home directory», среда) и 1× интеграция с живой БД
  (нарушение NOT NULL `session.student_id`). Интеграционные тесты БД пропускаются без PostgreSQL;
  живой DB round trip этого задания не проверялся повторно.
- `git diff --check` показывает пробелы в части изменённых файлов — не исправлялись
  (чужие незакоммиченные правки).

---

## 3. Как запускать с учётом изменений

### 3.1. Аутентификация

- По умолчанию JWT обязателен. Вход: `POST /api/v1/auth/login` `{"login": "...", "password": "..."}`
  → access/refresh; далее `Authorization: Bearer <access>` на всех маршрутах `/api/v1` с ролями.
- Локальный запуск/тесты без JWT: переменная окружения `REQUIRE_ROLES=false`
  (или `auth.require_roles=false` в конфиге) до старта сервера.
- Роли: `student` — только свои сессии; `teacher` — свои задания (`approved_by_id`),
  тренировки (`training.teacher_id`), работы своих групп; `admin` — всё.

### 3.2. Хранилище

- Режимы `storage_config`: `files` (файлы), `files-to-db` (запись в БД+файл), `db-only` (только PostgreSQL).
- Назначение тренировок по JWT (`POST /api/v1/training-plans`, `PUT /api/v1/trainings/{id}`)
  требует базы пользователей: в режиме `files` ответ 422 «Для назначения по JWT требуется
  база пользователей». Используйте `files-to-db`/`db-only`.
- Схема применяется при старте адаптера (`ensure_schema`); недоступная БД поднимает
  `StorageUnavailable` на старте.

### 3.3. Сервер

Монтирование как в REST-тестах (`tests/test_rest_api.py`):

```python
from ai_core import Engine
from storage_adapter import StorageAdapter
from web_ui import make_server

engine = Engine(provider, 'data', storage=StorageAdapter('data', mode='files-to-db'))
make_server(engine, 8000, api_token='<UI-token>',
            allowed_origins=['http://localhost:5173'], legacy_api=False)
```

Существующий скрипт запуска (`START_ALL.ps1`) работает как раньше; главное —
переменные из 3.1–3.2: `REQUIRE_ROLES` и режим хранилища.

### 3.4. Поведение для пользователей

- Студенты/преподаватели с одинаковыми `display_name` изолированы: чужие данные →
  403 `wrong_owner` (не 404, существование чужих данных не раскрывается).
- Назначение тренировок: студенты указываются уникальным логином (или уникальным именем);
  два совпадающих имени → «Имя неоднозначно; выберите уникальный логин».
- Повторная отправка того же назначения не создаёт дубли сессий (ключ `(task_id, student_id)`).

### 3.5. Тесты

```
python -X utf8 -m unittest discover -s tests -p "test_rest_api.py"
python -X utf8 -m unittest discover -s tests -p "test_storage_documents.py"
python -X utf8 -m unittest discover -s tests -p "test_teacher_portal.py"
python -X utf8 -m unittest discover -s tests -p "test_teacher_projection.py"
python -X utf8 -m unittest discover -s tests -p "test_storage_adapter.py"
python -X utf8 -m unittest discover -s tests -p "test_auth_crypto.py"
python -X utf8 -m unittest discover -s tests -p "test_curriculum.py"
python -X utf8 -m unittest discover -s tests -p "test_core.py"
```

Интеграционные тесты (`test_storage_integration`, `test_auth_integration`, …) требуют
PostgreSQL и пропускаются автоматически, если БД недоступна.

---

## 4. Изменённые файлы (в рамках этого задания)

- Код: `auth_crypto.py`, `rest_api.py`, `storage_repository.py`, `storage_documents.py`,
  `storage_adapter.py`, `teacher_portal.py`, `curriculum.py`, `application.py`,
  `ai_core.py`, `incident_training.py`, `materials.py`.
- Тесты: `tests/test_auth_crypto.py`, `tests/test_rest_api.py`, `tests/test_storage_documents.py`,
  `tests/test_teacher_portal.py`, `tests/test_curriculum.py`,
  `tests/test_dialogue_gateway_integration.py`; новые: `tests/test_storage_adapter.py`,
  `tests/test_teacher_projection.py`.

---

*Отчёт охватывает только выполненное задание RBAC. Смежные направления плана
(аналитика `insight_report`, режим `db-only`, Extended Query) — следующие шаги
по [`plans/step_6_plan.md`](../plans/step_6_plan.md).*

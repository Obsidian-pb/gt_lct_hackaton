# Шаг 4. Этап 3. Перенос учебных данных из JSON в БД

**Дата:** 2026-09-29 (04:18–04:46 UTC+7)
**Модель:** Roo Code (режимы architect → code)
**Статус:** реализовано, проверено на живом сервере БД PostgreSQL 14.2
**Источник плана:** [`plans/step_3_plan.md`](../plans/step_3_plan.md)
**Предыдущие шаги:** [`workflow/step_1.md`](step_1.md) (подключение), [`workflow/step_2.md`](step_2.md) (Этап 2.1, пользователи/JWT), [`workflow/step_3.md`](step_3.md) (Этап 2.2, схема и справочники)

---

## 1. Постановка задачи (из `plans/database_structure.qmd`, этап 3)

1. Проверить наличие учебных данных: `data/t-*.json`, `data/s-*.json`,
   `data/curriculum/scenario-*.json`, `training-*.json`, `materials.json`.
2. `t-*.json` → `task` (+ `task_dds`, `task_incident_source`); для `incident-v1`
   заполнить `identity_hash`.
3. `s-*.json` → `session` (+ `session_turn`, `session_hint`, `session_card_edit`,
   `session_reveal`, `machine_assessment`, `ai_assessment`/`ai_assessment_field`,
   `teacher_decision`/`teacher_decision_field`).
4. `curriculum/scenario-*.json` → `scenario` + `scenario_task`.
5. `curriculum/training-*.json` → `training` + `training_scenario` +
   `training_participant` + `training_card` (+ `training_service_action`).
6. `curriculum/materials.json` → `material`.
7. Строковые имена студентов/преподавателей → записи `user` (сгенерированный
   login), связь по `display_name`, отдельная таблица соответствий на время
   переходного периода.

Объём согласован с командой (утверждён план `plans/step_3_plan.md`):
- **без REST/UI** — просмотр учебных данных появится на Этапе 5 (переключение
  репозитория); этап закрывается консольным инструментом;
- **стратегия** — транзакционная «полная перезапись» учебных таблиц;
- **в лаунчере** — только некритичный `--check`, полный импорт вручную через
  `TEST_DATA.cmd`.

---

## 2. Ключевые проектные решения

1. **Версия схемы `2.3.0`.** Новый модуль [`training_data_repository.py`](../training_data_repository.py)
   добавляет только таблицу `legacy_name_map` (name UNIQUE, user_id FK, kind
   student/teacher) и `ensure_schema()` — по образцу `auth/catalog`; версия
   фиксируется в `schema_migration`. Все прочие таблицы созданы Этапом 2.2
   (`catalog_repository`, 2.2.0) и не пересоздаются.
2. **Импорт — «полная перезапись» в одной транзакции.** Источник истины на этом
   этапе — JSON-файлы (приложение пишет только в файлы), поэтому
   `TRUNCATE ... RESTART IDENTITY CASCADE` учебных таблиц + повторная вставка
   дают идемпотентность. Таблицы `user`, справочники и служебные
   (`ai_generation_log`, `insight_report`) **не затрагиваются**.
3. **Маппинг имён → `user`.** Имя встречается как `student` (`session.student`,
   участники тренировок) и как `teacher` (`task.approved_by`,
   `scenario.created_by/approved_by`, `training.teacher`, `material.teacher`,
   `session.teacher_note_by`, `teacher_decision.teacher`). При конфликте ролей —
   один `user` с ролью `teacher` (выше приоритетом), обе связи фиксируются в
   `legacy_name_map` (одна строка на имя, `kind` по высшей роли). Логин —
   транслитерация имени с суффиксом при коллизии; пароль — случайный
   (`secrets.token_urlsafe`, PBKDF2 через [`auth_crypto.hash_password`](../auth_crypto.py)),
   выдаётся администратором через `PUT /auth/users/{id}`.
4. **`identity_hash` — полный SHA-256, только для `incident-v1`.** Считается по
   тому же кортежу, что и идентификатор в
   [`incident_training.publish`](../incident_training.py) (`[content, reference,
   caller_scenario, opening, level]`); `id = 't-' + hash[:12]`. Для legacy — `NULL`.
5. **Правило доставки `delivered`.** Реплика не доставлена, только если
   `delivery='lost'` или `delivered == ''` ([`dds.py`](../dds.py)); частично
   доставленная (`partial`) считается доставленной, в `event` сохраняется факт.
6. **Нормализация времени.** ISO-строки без смещения трактуются как UTC
   (`+00:00`), чтобы исключить зависимость от TZ сервера Postgres.
7. **Сиротские ссылки не роняют импорт.** Сессии/карточки/связи сценариев со
   ссылками на отсутствующие задания пропускаются с предупреждением в отчёте.
8. **Лаунчер.** В [`START_ALL.ps1`](../START_ALL.ps1) добавлен некритичный шаг
   `init_training_data.py --check` (лог `.runtime\training-data-init.log`);
   полный `--init` выполняется вручную (`TEST_DATA.cmd`).

---

## 3. Таблицы БД (DDL в `training_data_repository.SCHEMA_STATEMENTS`, версия 2.3.0)

| Таблица | Назначение |
|---|---|
| `legacy_name_map` (новая) | Соответствие строковых имён → `user_id` на переходный период: `name` UNIQUE, `user_id` FK → user ON DELETE CASCADE, `kind` CHECK (student/teacher) |

Наполняемые (созданы в 2.2.0): `task`, `task_dds`, `task_incident_source`,
`scenario`, `scenario_task`, `training`, `training_scenario`,
`training_participant`, `training_card`, `training_service_action`, `material`,
`session`, `session_turn`, `session_hint`, `session_card_edit`, `session_reveal`,
`machine_assessment`, `ai_assessment`, `ai_assessment_field`,
`teacher_decision`, `teacher_decision_field`.

---

## 4. Созданные/изменённые файлы

Новые модули бэкенда:

| Файл | Роль |
|---|---|
| [`training_data_repository.py`](../training_data_repository.py) | DDL v2.3.0 (`legacy_name_map`), батч-вставки (`insert_many`), `truncate_all`, методы user (поиск/создание/повышение роли), `counts()`, `integrity_issues()` |
| [`training_data_importer.py`](../training_data_importer.py) | Чистый парсер (без БД): `scan`, разбор задач/сессий/сценариев/тренировок/материалов, `normalize_ts`, `delivered_flag`, `compute_identity_hash`, `collect_names` |
| [`training_data_service.py`](../training_data_service.py) | Оркестратор: `parse_all` → `resolve_users` → `build_rowsets` → единая транзакция перезаписи; `import_all`/`check_state` |
| [`init_training_data.py`](../init_training_data.py) | CLI `--init [--dir] --check --self-test --pause`, exit 0/2 |
| [`TEST_DATA.cmd`](../TEST_DATA.cmd) | Ручной запуск `--init --check --self-test --pause` |

Изменённые файлы: [`START_ALL.ps1`](../START_ALL.ps1) (некритичный шаг
«Checking the training data layer…», лог `.runtime\training-data-init.log`),
[`plans/database_structure.qmd`](../plans/database_structure.qmd) (статус Этапа 3).

Новые тесты: [`tests/test_training_data_importer.py`](../tests/test_training_data_importer.py)
(unit, 17), [`tests/test_training_data_integration.py`](../tests/test_training_data_integration.py)
(живая БД, 5, скип при недоступности).

---

## 5. Проверки и их результаты

### 5.1 Проверка наличия данных (первый пункт этапа)
```
[DATA] Проверка: ОШИБКА: Учебные данные не найдены: tasks=0, sessions=0, scenarios=0, trainings=0, materials=нет
```
Каталог `data/` на текущем стенде пуст (он же скрыт от инструментов агента
`.codeassistantignore`); инструмент честно сообщает об отсутствии данных, а не
падает. Реальный импорт выполняется на стенде с данными (`TEST_DATA.cmd`).

### 5.2 Юнит-тесты парсера (без БД)
`python -X utf8 -m unittest tests.test_training_data_importer` — **17/17 OK**:
сканирование, legacy/dds/incident-v1 задачи (+ `identity_hash`), полная сессия
(реплики/hints/edits/reveals/machine/ai/решение преподавателя), правило
`delivered`, нормализация времени, сценарий, тренировка (карточки + действия
служб), материалы, сбор имён с приоритетом ролей, транслитерация, порядок
колонок `build_rowsets`.

### 5.3 Интеграционные тесты (живая БД)
`python -X utf8 -m unittest tests.test_training_data_integration` — **5/5 OK**
(скип при недоступности БД): полный импорт фикстур (task=2, task_incident_source=1,
scenario=1, training=1, material=1, session=1 при 2 файлах — сиротская сессия
пропущена с предупреждением, session_turn=2, machine/ai/decision по 1,
training_card=1, training_service_action=1, legacy_name_map>0); идемпотентность
повторного `--init` (пользователи не задваиваются); приоритет роли (студент,
выступивший преподавателем, повышен до teacher; `legacy_name_map.kind=teacher`);
`identity_hash` 64 hex у `incident-v1` и NULL у legacy; целостность FK без
нарушений; версия схемы 2.3.0.

### 5.4 Регрессия
`set PYTHONUTF8=1 && python -m unittest discover -s tests -p "test_*.py"`
— **171 тест**: все проходят, **кроме** известных 30 ошибок
`tests/test_multi_provider` по причине окружения (`patch.dict(os.environ,
clear=True)` ломает `Path.home()` на Windows — файлы `provider.py`/
`test_multi_provider.py` не менялись; задокументировано в `workflow/step_2.md`).

### 5.5 Статические проверки
- `python -m py_compile` всех новых/изменённых модулей и тестов — `COMPILE_OK`;
- парсер PowerShell для [`START_ALL.ps1`](../START_ALL.ps1) — `POWERSHELL_SYNTAX_OK`;
- CLI: `init_training_data.py --check` корректно отрабатывает сценарий
  «данных нет» (exit 2).

---

## 6. Как запустить

| Сценарий | Действие |
|---|---|
| Полный импорт + проверки | двойной клик `TEST_DATA.cmd` (или `python init_training_data.py --init --check --self-test`) |
| Импорт из другого каталога | `python init_training_data.py --init --dir D:\path\to\data` |
| Только проверка наличия/состояния | `python init_training_data.py --check` |
| Автоматически при старте | `START.cmd` → шаг «Checking the training data layer…» + `.runtime\training-data-init.log` |

После импорта: войти админом (`/admin-login`, admin/admin123) → «Пользователи и
доступ» → выдать пароли созданным пользователям (`PUT /auth/users/{id}`).

---

## 7. Замечания и ограничения

1. **На текущем стенде нет учебных данных** (`data/` пуст); конвейер проверен
   на фикстурах интеграционными тестами против живой БД. Импорт реальных данных
   — запуск `TEST_DATA.cmd` на стенде, где лежат `t-*.json`/`s-*.json`/
   `curriculum/*.json`; после запуска проверить `--check` (количества должны
   совпасть с числом файлов).
2. **`--init` перезаписывает учебные таблицы** (TRUNCATE + вставка). Пока
   источник истины — файлы, это безопасно; стратегия сменится на Этапе 5.
3. **Пароли импортированных пользователей случайны** и не выводятся в отчёт;
   доступ выдаёт администратор через админку (смена пароля уже реализована в
   `/auth/users`).
4. **`legacy_name_map`** — одна строка на имя (`UNIQUE(name)`); `kind`
   отражает высшую роль (teacher > student). Таблица нужна для переходного
   периода и может быть удалена после Этапа 5.
5. **Потеря точного фрагмента** частично доставленной реплики ДДС
   (`delivery='partial'`): схема хранит только boolean `delivered`; исходный
   текст сохраняется, фрагмент восстанавливается из файла при аудите.
6. **REST/UI не добавлялись** — просмотр учебных данных из БД и переключение
   репозитория — Этап 5.
7. **Типизация jsonb:** значения сериализуются в `_jsonb()` (строка JSON), что
   устраняет ошибку `column ... is of type jsonb but expression is of type
   integer` для `machine_assessment.compared` и аналогичных полей.

---

## 8. Что дальше (Этап 4)

- Импорт мастерской карточек из `localStorage` (`giik.card-workshop.v1`) →
  `workshop_card` + `workshop_card_reference` + `workshop_card_version` +
  `workshop_card_event` при входе преподавателя (идемпотентно).
- При необходимости — Extended Query и пул соединений.
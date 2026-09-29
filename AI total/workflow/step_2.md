# Шаг 2. Этап 2.1. Инициализация слоя пользователей и аутентификации

**Дата:** 2026-09-28 (12:20–13:30 UTC+7)
**Модель:** Roo Code (режимы architect → code)
**Статус:** реализовано, проверено на живом сервере БД PostgreSQL 14.2

---

## 1. Постановка задачи (из `plans/database_structure.qmd`, этап 2.1)

- Создать таблицы, необходимые для работы с пользователями и аутентификацией.
- Реализовать авторизацию и аутентификацию на основе JWT.
- Посеять Администратора (по решению команды — фиксированный пароль по умолчанию `admin/admin123`,
  переопределяется через `ADMIN_PASSWORD` / секцию `auth` в `config.local.json`).
- Протестировать вход в систему под учётной записью Администратора.

Объём согласован с командой: **максимальный** — бэкенд + фронтенд + минимальная панель админа
(CRUD пользователей и учебных групп через `/auth/users` и `/auth/groups`).

---

## 2. Ключевые проектные решения

1. **Никаких сторонних библиотек.** Криптография собрана на stdlib:
   - пароли — PBKDF2-HMAC-SHA256 (`hashlib.pbkdf2_hmac`, 200 000 итераций, соль 16 байт),
     формат `pbkdf2_sha256$iter$salt$hash`, сравнение `hmac.compare_digest`;
   - JWT — HS256 (`header.payload.signature`, base64url, HMAC-SHA256), проверка `exp` и подписи;
   - refresh-токены — случайные 32 байта (`secrets.token_urlsafe`), в БД хранится только SHA-256 хэш.
2. **Расширен wire-клиент PostgreSQL** ([`db_connection.py`](db_connection.py)): добавлен общий исполнитель
   Simple Query (`execute`/`fetchone`), разбор RowDescription/DataRow/CommandComplete/ErrorResponse,
   безопасное экранирование литералов `quote_literal()` (защита от SQL-инъекций) и контекст
   транзакции `transaction()`. До этого клиент умел только `SELECT 1`.
3. **Таблицы** (раздел 2.1 документа + служебные): `user` (роли admin/teacher/student, CHECK,
   unique login), `student_group`, `group_member` (PK group_id+user_id), `auth_session`
   (refresh-токены: rotation/revocation, срок 30 суток), `schema_migration` (версия `2.1.0`).
4. **Секрет JWT** — автогенерация в `config.local.json` (секция `auth`, файл не коммитится),
   переопределение env `JWT_SECRET`. TTL: access — 8 ч (переопределяется), refresh — 30 суток.
5. **Маршруты** добавлены в контракт [`api_contract.py`](api_contract.py) с новым полем `auth`
   (уровень защиты маршрута); JWT-middleware проверяет Bearer-токен и роли в
   [`rest_api.py`](rest_api.py) (401/403). Легаси-проверка `X-UI-Token`/`TRAINING_API_TOKEN`
   для прочих маршрутов сохранена; пути `/api/v1/auth/*` освобождены от неё в
   [`web_ui.py`](web_ui.py).
6. **Фронтенд:** вход админа переведён с localStorage на серверный `/auth/login`
   ([`admin-auth.js`](frontend/src/admin-auth.js), [`AdminLogin.jsx`](frontend/src/AdminLogin.jsx));
   панель «Пользователи и доступ» ([`Admin.jsx`](frontend/src/Admin.jsx)) работает через
   `/auth/users` и `/auth/groups` (вкладки «Пользователи», «Группы», «Роли», «Аудит»).
   REST-клиент ([`ui/api-client.js`](ui/api-client.js)) получил поддержку проброса заголовков.

---

## 3. Таблицы БД (DDL в `auth_repository.SCHEMA_STATEMENTS`)

| Таблица | Назначение | Ключевые ограничения |
|---|---|---|
| `user` | Пользователь системы | unique(login), CHECK role IN (admin,teacher,student), is_active |
| `student_group` | Учебная группа | unique(name), teacher_id FK → user ON DELETE SET NULL |
| `group_member` | Состав группы | PK(group_id,user_id), каскады |
| `auth_session` | Refresh-сессии | unique(refresh_hash), expires_at, revoked_at, replaced_by_id |
| `schema_migration` | Версии схемы | PK(version) — зафиксирована версия `2.1.0` |

Индексы: `user(role)`, `user(is_active)`, `group(teacher_id)`, `group_member(user_id)`,
`auth_session(user_id)`, `auth_session(expires_at)`.

---


## 4. Созданные/изменённые файлы

Новые модули бэкенда:

| Файл | Роль |
|---|---|
| [`auth_crypto.py`](auth_crypto.py) | PBKDF2-хэши, JWT HS256, управление секретами и настройками auth |
| [`auth_repository.py`](auth_repository.py) | DDL + CRUD пользователей, групп, участников, refresh-сессий |
| [`auth_service.py`](auth_service.py) | login/refresh/logout/me, seed_admin, RBAC, CRUD-логика |
| [`init_auth.py`](init_auth.py) | Инициализация схемы, посев админа, самопроверка входа |
| [`TEST_AUTH.cmd`](TEST_AUTH.cmd) | Ручной запуск `--init --self-test --pause` |

Изменённые файлы: [`db_connection.py`](db_connection.py), [`api_contract.py`](api_contract.py),
[`application.py`](application.py), [`rest_api.py`](rest_api.py), [`web_ui.py`](web_ui.py),
[`START_ALL.ps1`](START_ALL.ps1) (некритичный шаг инициализации auth, лог `.runtime\auth-init.log`),
[`ui/api-client.js`](ui/api-client.js), [`frontend/src/admin-auth.js`](frontend/src/admin-auth.js),
[`frontend/src/AdminLogin.jsx`](frontend/src/AdminLogin.jsx), [`frontend/src/Admin.jsx`](frontend/src/Admin.jsx).

Новые тесты: [`tests/test_auth_crypto.py`](tests/test_auth_crypto.py) (unit),
[`tests/test_auth_integration.py`](tests/test_auth_integration.py) (на живую БД, скип при недоступности).

API-маршруты этапа: `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`,
`GET|POST /auth/users`, `PUT|DELETE /auth/users/{user_id}`, `GET|POST /auth/groups`,
`PUT|DELETE /auth/groups/{group_id}`, `GET /auth/groups/{group_id}/members`,
`POST /auth/groups/{group_id}/members`, `DELETE /auth/groups/{group_id}/members/{user_id}`.
Документ OpenAPI перегенерирован (`python build_api_contract.py` → `openapi.json`, `ui/api-routes.js`).

---

## 5. Проверки и их результаты

### 5.1 Риск-чек прав БД (до миграции)

```
current_user=xgb_lct_hack, ddl_priv(CREATE)=t
CREATE TABLE/INSERT/SELECT/DROP -> OK, rowcount/tag парсятся
```

### 5.2 Инициализация и самопроверка входа (init_auth.py)

```
[AUTH] Проверка: Слой аутентификации готов: схема 2.1.0, пользователей в БД: 1.
[AUTH] Инициализация: Схема 2.1.0 создана; администратор 'admin' готов (id=1, пароль='admin123').
[AUTH] Самопроверка входа: Вход администратора пройден полностью: login → me → refresh → logout.
```

### 5.3 REST-поток (RestAPI / api/v1)

- `POST /auth/login` admin/admin123 → 200 + JWT;
- `GET /auth/me` с токеном → 200; без токена → 401;
- неверный пароль → 401 `wrong_credentials`;
- студент не может читать `/auth/users` → 403 `forbidden`;
- CRUD пользователей и групп (создание, изменение роли/статуса, состав группы) — работает.

### 5.4 Юнит- и интеграционные тесты

`python -m unittest tests.test_auth_crypto tests.test_auth_integration`

Покрытие unit: roundtrip PBKDF2, urlsafe-`-` в хэше (регрессия), неверный/повреждённый хэш,
JWT: подпись, tamper payload, wrong secret, exp, max_age, refresh-пары.
Покрытие интеграции: вход админа и me, неверный пароль 401, me без токена 401,
RBAC студента 403, CRUD пользователей, rotation refresh + logout 401,
CRUD групп и участников. Тест-данные уникальны и удаляются в tearDown.
Итог: **21/21 тестов OK** (14 unit + 7 интеграционных).

### 5.5 Регрессия существующих тестов

`python -m unittest discover -s tests -p "test_*.py"` — 136 тестов: все проходят,
**кроме** `tests/test_multi_provider` (30 ошибок), которые падают и до данного
этапа по причине окружения: тест использует `patch.dict(os.environ, {...}, clear=True)`
([test_multi_provider.py](tests/test_multi_provider.py:25)), полностью очищая переменные
окружения, из-за чего `Path.home()` в конструкторе [provider.py](provider.py:85)
на Windows не может определить домашний каталог. Файлы `provider.py` и
`test_multi_provider.py` данным этапом не изменялись.
Найденные прогоном два дефекта новых тестов (булевы значения PostgreSQL приходят
текстом `'t'/'f'`; длина пароля в сценарии «неверный пароль») устранены и перепроверены.
Дополнительно: `py_compile` всех изменённых модулей — OK; синтаксис `START_ALL.ps1`
(парсер PowerShell) — OK.

> Замечание: сборка фронтенда локально не выполнялась — `esbuild.exe` отсутствует
> (`frontend/node_modules` не установлен). Сборка выполняется штатным `BUILD_UI.cmd`
> на машине деплоя после `npm install`. Исходники и контракт маршрутов обновлены.

---

## 6. Как запустить

| Сценарий | Действие |
|---|---|
| Ручная инициализация + самопроверка входа | двойной клик `TEST_AUTH.cmd` |
| Инициализация/проверка из консоли | `python init_auth.py --init --check --self-test` |
| Автоматически при старте | `START.cmd` → шаг «Initializing the users/auth layer» + `.runtime\auth-init.log` |
| Вход администратора | браузер → `/admin-login` → `admin` / `admin123` |

### Дополнительно

1. Установить зависимости фронтенда (один раз):

```{bash}
cd frontend
npm install
```

2. Пересобрать и перезапустить приложение:

- либо запустить BUILD_UI.cmd и затем RESTART.cmd;
- либо просто START.cmd — он сам вызывает сборку перед запуском.

После этого в браузере обновить страницу админки (Ctrl+F5). 

Проверить после пересборки: войти в /admin-login под admin/admin123, открыть «Пользователи и доступ» → «Добавить пользователя» — если поле «Пароль» на месте, бандл обновлён и запись в БД работает.

---

## 7. Замечания и ограничения

1. **Фиксированный пароль админа** — для учебного стенда; на бою сменить через `ADMIN_PASSWORD`
   или секцию `auth.admin_password` в `config.local.json`, затем повторно запустить `init_auth.py`.
2. **Подключение к БД открывается на каждый вызов** (паттерн `data_layer`); пул соединений —
   следующий шаг оптимизации.
3. **Simple Query без параметров**: все значения вставляются через `quote_literal()`; переход на
   Extended Query (настоящие параметры) — кандидат на хардненинг в Этапе 2.2 при массовых операциях.
4. **JWT stateless access + refresh в БД**: отзыв сессии возможен только через refresh-токен;
   access-токен живёт до истечения срока (8 ч).
5. **Права на роли пока распространяются только на `/auth/*`**; полная ролевая защита остальных
   маршрутов REST — Этап 5 (переключение репозитория).
6. **UI-бандл не пересобран локально** (нет node_modules) — на сервере выполнить `BUILD_UI.cmd`.

---

## 8. Что дальше (Этап 2.2)

- Создание таблиц по разделу 2 документа (`task`, `session`, мастерская, справочники) с индексами
  и внешними ключами;
- импорт статических справочников из `catalog/classifier.json` и `ui/geo/*.json`;
- при необходимости — Extended Query и пул соединений.
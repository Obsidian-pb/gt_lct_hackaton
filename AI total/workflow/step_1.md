# Шаг 1. Подключение к PostgreSQL (слой данных)

**Дата:** 2026-09-28
**Статус:** выполнено, проверено на живом сервере БД

---

## 1. Постановка задачи

Создать для проекта механизм подключения к БД PostgreSQL. Пока **только подключение и не более того**.

Логика: при запуске приложения посредством `START.cmd` на сервере запускается также и слой
данных. Проверяется подключение: если БД подключилась — в консоль выводится сообщение, что БД
подключена; если нет — сообщение, что этого не произошло.

**Connection string:**

```
host=postgres81.1gb.ru port=5432 dbname=xgb_lct_hack user=xgb_lct_hack password=HBy-y9AxR8DU
```

Отдельная предварительная проверка самой возможности подключения к указанной БД — выполнена
первым делом (см. раздел 5).

---

## 2. Ключевое проектное решение

В проекте сознательно **нет сторонних Python-библиотек** (README: «сторонние Python-библиотеки
не нужны»), и `psycopg2` / `psycopg3` в окружении отсутствуют:

```
python -c "import psycopg2"   -> ModuleNotFoundError: No module named 'psycopg2'
python -c "import psycopg"    -> ModuleNotFoundError: No module named 'psycopg'
```

Поэтому вместо драйвера реализован **минимальный клиент wire-протокола PostgreSQL 3.0 только на
стандартной библиотеке** (`socket`, `ssl`, `struct`, `hashlib`, `hmac`, `base64`, `secrets`).

Реализовано:

- SSL-негатциация (режимы `prefer` / `require` / `disable`);
- Startup-пакет протокола 3.0 (`user`, `database`, `client_encoding=UTF8`);
- Методы аутентификации: `trust`, `cleartext` (req 3), `MD5` (req 5), `SCRAM-SHA-256`
  (req 10 → 11 → 12, RFC 5802 / RFC 7677);
- Чтение `ParameterStatus` (версия сервера), `BackendKeyData`, `NoticeResponse`;
- Проверка работоспособности сессии служебным `SELECT 1`;
- Корректное закрытие соединения (`Terminate`) и человекочитаемый разбор `ErrorResponse`.

Никаких прикладных запросов, миграций, ORM и работы с данными **не выполняется** — только
подключение и его проверка.

### Архитектура (3 модуля + 2 файла запуска)

| Файл | Роль |
|------|------|
| `db_config.py` | Настройки подключения: дефолты + переопределение через `config.local.json` и переменные окружения |
| `db_connection.py` | Клиент протокола PostgreSQL, `connect_from_config()` |
| `data_layer.py` | Слой данных: проверка подключения и вывод сообщения в консоль |
| `TEST_DB.cmd` | Ручная проверка подключения одним запуском |
| `START_ALL.ps1` | Интеграция: запуск слоя данных вместе с приложением |

### Приоритет источников настроек

```
DEFAULT_DB_CONFIG (db_config.py)  <  секция "postgres" в config.local.json  <  переменные окружения
```

Переменные окружения: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`.

### Коды возврата `data_layer.py`

| Код | Значение |
|-----|----------|
| `0` | БД подключена |
| `2` | БД не подключена |

---

## 3. Созданные файлы (полное содержимое)

### 3.1 `db_config.py`

PostgreSQL connection settings for the data layer.

Defaults match the project connection string. Values can be overridden by
environment variables (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD) or by
a "postgres" section inside config.local.json (not committed to the repo).


### 3.2 `db_connection.py`

Minimal PostgreSQL wire-protocol client (protocol 3.0) using stdlib only.

Supports SSL negotiation (prefer/require/disable) and password authentication
methods: trust, cleartext, MD5 and SCRAM-SHA-256 (RFC 5802 / RFC 7677).
The project keeps zero third-party Python dependencies, so psycopg2 is
deliberately not used. This module only opens a verified connection and
closes it; no queries beyond the internal "SELECT 1" verification are run.


### 3.3 `data_layer.py`

Data layer startup check for PostgreSQL.

Launched alongside the application (see START_ALL.ps1) and run standalone via
TEST_DB.cmd. The current scope is intentionally minimal: open and verify a
database connection and report the result to the console. No queries or data
logic are performed yet.

Exit codes: 0 = connected, 2 = not connected, 3 = misconfigured.


### 3.4 `TEST_DB.cmd`

Сделан по образцу существующего `CHECK_AI.cmd` (тот же порядок поиска `py` → `python`).


## 4. Изменения существующих файлов

### 4.1 `START_ALL.ps1` (его вызывает `START.cmd`)

Проверка слоя данных добавлена **после** открытия интерфейса, чтобы недоступная БД не задерживала
запуск приложения. Шаг **некритический**: ошибка подключения не приводит к падению лаунчера.
Вывод печатается в консоль лаунчера (зелёным при успехе, жёлтым при отказе) и сохраняется в
`.runtime\data-layer.log`.

Вставлен блок между `Start-Process 'http://127.0.0.1:8878'` и финальным сообщением «112 is running»:

```powershell
    Step 'Checking the data layer (PostgreSQL)...'
    try {
        $dataLayerOutput = (& $python 'data_layer.py' 2>&1 | Out-String).Trim()
        $dataLayerCode = $LASTEXITCODE
    } catch {
        $dataLayerOutput = $_.Exception.Message
        $dataLayerCode = 1
    }
    Set-Content -Path (Join-Path $runtime 'data-layer.log') -Value $dataLayerOutput -Encoding UTF8
    Write-Host ''
    if ($dataLayerCode -eq 0) {
        Write-Host $dataLayerOutput -ForegroundColor Green
    } else {
        Write-Host $dataLayerOutput -ForegroundColor Yellow
    }
```

### 4.2 Прочие файлы

`START.cmd` **не изменялся** — он уже делегирует всё в `START_ALL.ps1`, поэтому интеграция
выполнена на уровне лаунчера. `web_ui.py`, `ai_rest_server.py` и остальной код приложения не
затронуты: слой данных пока существует отдельно и не внедряется в HTTP-серверы.

---

## 5. Проверки и их результаты

### 5.1 Предварительная проверка доступности хоста

До написания кода проверена связность `postgres81.1gb.ru:5432`. HTTP-запрос к порту дал
`socket hang up` — признак того, что **TCP-порт открыт и слушается Postgres** (не
`connection refused`). Python-окружение проверено: `Python 3.11.7`, драйверов БД нет.

### 5.2 Живое подключение (прямой вызов клиента)

```
python -c "import db_config, db_connection; cfg=db_config.get_db_config(); c=db_connection.connect_from_config(cfg); print('OK', c.host, c.port, c.dbname, 'auth=', c._auth_method, 'ssl=', c.ssl_active, 'server=', c._server_params.get('server_version')); c.close()"
```

Вывод:

```
OK postgres81.1gb.ru 5432 xgb_lct_hack auth= md5 ssl= False server= 14.2 (Debian 14.2-1.pgdg110+1)
```

**Возможность подключения к указанной БД подтверждена**: сервер — PostgreSQL 14.2 (Debian),
аутентификация прошла успешно.

### 5.3 Успешный путь слоя данных

```
python data_layer.py
```

```
[DATA] БД подключена: postgres81.1gb.ru:5432/xgb_lct_hack (без SSL, auth=md5, сервер 14.2 (Debian 14.2-1.pgdg110+1))
EXITCODE=0
```

### 5.4 Путь отказа (недоступная БД)

Проверено на закрытом порту через переменные окружения:

```
$env:PGHOST='127.0.0.1'; $env:PGPORT='59999'; python data_layer.py
```

```
[DATA] БД НЕ подключена: Сервер 127.0.0.1:59999 недоступен (Подключение не установлено, т.к. конечный компьютер отверг запрос на подключение) [127.0.0.1:59999/xgb_lct_hack]
EXITCODE=2
```

Сообщение об отсутствующем подключении формируется корректно.

### 5.5 Статические проверки

| Проверка | Результат |
|----------|-----------|
| `python -m py_compile db_config.py db_connection.py data_layer.py` | `COMPILE_EXIT=0` |
| LSP/линтер по итогам редактирования | проблем не обнаружено |
| Парсер `System.Management.Automation.Language.Parser` для `START_ALL.ps1` | `syntax OK` |

---

## 6. Как запустить

| Сценарий | Действие |
|----------|----------|
| Только проверка подключения | двойной клик `TEST_DB.cmd` (ждает Enter перед закрытием) |
| Проверка из консоли | `python data_layer.py` |
| В составе приложения | обычный `START.cmd` → строка статуса БД в консоли лаунчера + `.runtime\data-layer.log` |

---

## 7. Замечания и ограничения

1. **SSL не используется.** Сервер принял соединение открытым текстом (`sslmode=prefer`: сначала
   пробуем TLS, при отказе идём без шифрования). Строгой проверки сертификата нет — при
   успешной негатциации TLS контекст создан с `check_hostname=False` и `CERT_NONE`.
2. **Пароль в репозитории.** Сейчас значения подключения лежат в `db_config.py` по умолчанию.
   Если не хотите светить пароль в git — вынесите его в `config.local.json` (файл не включается
   в ZIP и не передаётся) или в переменные окружения:
   ```json
   { "postgres": { "password": "HBy-y9AxR8DU" } }
   ```
3. **Проверен только успех аутентификации MD5.** Пути `trust`, `cleartext` и `SCRAM-SHA-256`
   реализованы, но на живом сервере не проверялись (данный хост использует MD5).
4. **Полный `START.cmd` не запускался**, чтобы не поднимать веб-сервер на портах 8878/8890 и не
   открывать браузер; интеграция проверена статически (парсер PowerShell) и прямым запуском
   `data_layer.py`.
5. **Объём строго по задаче:** только подключение и его проверка. Запросы, схемы, миграции,
   пул соединений и интеграция с REST API — следующие шаги.

---

## 8. Что дальше (не входит в шаг 1)

- Выполнение первых запросов (`SHOW tables`, чтение справочников) и, при необходимости,
  простые `INSERT`/`SELECT` через собственный слой;
- При росте нагрузки — переход на `psycopg3` в изолированном virtualenv либо добавление
  пула/переиспользования соединения вместо подключения на каждую проверку;
- Интеграция статуса БД в `/health` основного backend и панель мониторинга преподавателя;
- Хост-агностичность: проверка `sslmode=require` и поддержка `SCRAM-SHA-256` на целевом
  стенде, если провайдер сменит метод аутентификации.

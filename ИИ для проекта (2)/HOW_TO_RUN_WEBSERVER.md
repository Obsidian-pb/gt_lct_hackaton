# Как развернуть тренажёр 112 в интернете (публичный сервер)

Вариант «общий сервер в локальной сети» описан в `SHARED_SERVER.md`.
Этот документ — про **доступ по HTTPS извне**: выбор хостинга, требуемое ПО, пошаговый
запуск, безопасность и проверка.

Все ссылки на строки соответствуют текущему состоянию репозитория.

---

## 1. Архитектура

```
Интернет ──443──> nginx (TLS, заголовки, лимит запросов)
                    ├── 127.0.0.1:8878  web_ui.py        — интерфейс + REST /api/v1
                    └── 127.0.0.1:8890  ai_rest_server.py — диалог с «заявителем»
                                   └── 127.0.0.1:5432   PostgreSQL (только localhost)
```

Приложение **не умеет TLS** (`http.server.ThreadingHTTPServer` без обёртки SSL,
`web_ui.py:4,79`), поэтому наружу оно не смотрит никогда — только за обратным прокси.

| Компонент | Порт | Привязка |
|---|---|---|
| `web_ui.py` | 8878 (`web_ui.py:648`) | `127.0.0.1` |
| `ai_rest_server.py` | 8890 (`ai_rest_server.py:289`) | `127.0.0.1` |
| PostgreSQL | 5432 | `127.0.0.1` |

> Важно: у `--host` ровно два допустимых значения — `127.0.0.1` или `0.0.0.0`
> (`web_ui.py:649`). Привязать процесс к другому конкретному адресу нельзя.

---

## 2. Обязательные требования проекта (проверено по коду)

| Что | Требование | Источник |
|---|---|---|
| Python | **3.10 или новее** (установщик даёт 3.12.10) | `README.md:91`, `INSTALL_PYTHON.ps1:8`, `SETUP_SHARED_SERVER_NO_DOCKER.ps1:16` |
| Python-пакеты | **только `psycopg[binary]>=3.1,<4`** | `requirements-server.txt` |
| СУБД | **PostgreSQL** (проверено на 16). В серверном режиме без него запуск падает | `--require-postgres`, `web_ui.py:664-665`, `migrations/001…005` |
| libc | **glibc** (Ubuntu/Debian). На Alpine musl бинарные колёса `psycopg[binary]` ставятся нестабильно | тип пакета `binary` |
| Reverse proxy + TLS | **обязателен** | см. §1 |
| Исходящие соединения | HTTPS на API ИИ-провайдера (`api.giga.chat:443`, либо OpenAI/Gemini/Anthropic; для GigaChat ещё `ngw.devices.sberbank.ru:9443` — OAuth) | `provider.py:21-38,118` |
| HTTPS для пользователей | обязателен также из-за микрофона: без защищённого origins браузер блокирует `getUserMedia` | `microphone.html` |
| Целостность UI | при старте вызывается `validate_ui()`, требующая ~30 файлов в `ui/` | `ui_release.py:6-29`, `web_ui.py:662` |

**Что ставить НЕ нужно:**

- **Node.js / npm** — собранный бандл `ui/react/app.js` уже лежит в проекте.
  `BUILD_UI.cmd` на Linux всё равно не сработает: он ищет
  `frontend\node_modules\@esbuild\win32-x64\esbuild.exe` (жёстко win32).
  Если `frontend/src` не менялся — Node не нужен. Если менялся — соберите бандл на Windows
  и скопируйте один файл `ui/react/app.js`.
- **Docker** — опционально, и только для PostgreSQL (`docker-compose.postgres.yml`).
  Dockerfile приложения в проекте нет.
- **Piper / espeak-ng** — опционально, для серверной озвучки. Без них работает
  браузерный голос; `piper_tts.py:108-111` ищет бинарь `piper`/`piper.exe` рядом с проектом.

---

## 3. Выбор хостинга

### ❌ Не подходит: виртуальный (shared) хостинг

Причина не в Python, а в невозможности выполнить три условия:

1. настроить собственный reverse proxy с TLS и заголовками;
2. управлять systemd-сервисами и долгоживущим процессом;
3. иметь PostgreSQL с правом DDL — приложение само применяет миграции
   (`manage_db.py migrate`, `--auto-migrate`).

### ✅ Подходит: VPS/VDS на Linux

Оптимально: **Ubuntu 22.04 / 24.04 LTS**, полный root/sudo, systemd, nginx, свой PostgreSQL.

### ⚠️ PaaS (Render / Fly.io / Selectel Cloud Apps и т. п.)

Технически возможно, но неудобно: процесс пишет в локальные `data/`
(`Engine.directory.mkdir`, `ai_core.py`) и `piper_voices/`, нужен постоянный том;
выделенный AI REST — это второй сервис; один процесс не масштабируется горизонтально.

### Локация

- Обучающиеся в РФ + GigaChat → дата-центр в РФ (задержка, доступность API).
- OpenAI/Anthropic → хостинг обязан иметь стабильный исходящий доступ к этим API,
  иначе запросы ИИ падают с `RuntimeError` (`provider.py:157-159`).

### Конфигурация по размеру группы

| Одновременно активных мест | vCPU | RAM | Диск |
|---|---|---|---|
| до 15–20 | 1 | 2 ГБ | 20 ГБ SSD |
| 20–50 | 2 | 4 ГБ | 40 ГБ SSD |
| 50+ | 4 | 8 ГБ | 60+ ГБ SSD, PostgreSQL отдельно |

Модели Piper — по ~60 МБ каждая (`.gitignore` их не хранит: `piper_voices/*.onnx`),
закладывайте +250 МБ, если озвучка нужна.

### Чек-лист проверки тарифа до оплаты

1. `curl -I https://api.giga.chat/v1` (или ваш провайдер) — исходящие 443 открыты.
2. Доступен systemd: `systemctl status`, `systemctl enable --now`.
3. `apt install nginx postgresql` без ограничений.
4. Управляемый firewall: открыты только 80/443.
5. Есть снапшоты/бэкапы дисков либо консоль для `pg_dump` наружу.
6. Задержка с рабочих мест учебной сети < 50 мс (иначе диалог с «заявителем» дёргается).
7. Персональные данные обучающихся → 152-ФЗ: локация в РФ, договор и акты от оператора.

---

## 4. Пошаговое развертывание

Дальше — Ubuntu 24.04, проект в `/opt/trainer112`, домен `trainer.example.org`.

### Шаг 1. Установить ПО

```bash
apt update
apt install -y python3 python3-venv python3-pip \
               nginx postgresql \
               certbot python3-certbot-nginx \
               logrotate ufw fail2ban curl git
python3 --version   # ≥ 3.10
psql --version      # ≥ 12
```

### Шаг 2. Загрузить проект целиком

Копируйте **всю папку**, включая `ui/`, `catalog/`, `migrations/`, `certs/` — иначе
`validate_ui()` прервёт запуск с «Получена неполная копия интерфейса».

```bash
useradd -r -m -d /opt/trainer112 -s /usr/sbin/nologin trainer
mkdir -p /opt/trainer112
# rsync -a --exclude .runtime --exclude __pycache__ ./ local/ root@host:/opt/trainer112/
chown -R trainer:trainer /opt/trainer112
```

### Шаг 3. Виртуальное окружение

```bash
cd /opt/trainer112
sudo -u trainer python3 -m venv .venv
sudo -u trainer .venv/bin/pip install -r requirements-server.txt
```

### Шаг 4. PostgreSQL

Вариант А — системный PostgreSQL:

```bash
sudo -u postgres psql <<'SQL'
CREATE USER trainer112 PASSWORD 'ДЛИННЫЙ_ПАРОЛЬ_16+_БЕЗ_@:/#';
CREATE DATABASE trainer112 OWNER trainer112;
SQL
```

Вариант Б — Docker: раскройте `docker-compose.postgres.yml`, **обязательно** задав
`TRAINER_DB_PASSWORD` (там дефолт `change-this-before-public-deploy`), и убедитесь,
что проброс остался `127.0.0.1:5432:5432`.

### Шаг 5. Секреты и окружение

```bash
cat > /opt/trainer112/.env.server <<'ENV'
DATABASE_URL=postgresql://trainer112:ПАРОЛЬ@127.0.0.1:5432/trainer112
PUBLIC_ORIGIN=https://trainer.example.org
ALLOW_SELF_REGISTRATION=0
AI_REST_TOKEN=ЗАПОЛНИТЬ_НИЖЕ
AI_DIALOGUE_REST_URL=http://127.0.0.1:8890
ENV
chmod 600 /opt/trainer112/.env.server
chown trainer:trainer /opt/trainer112/.env.server

# токен между backend и AI REST: не короче 24 символов, ASCII, без пробелов
openssl rand -hex 32
```

Ограничения, которые код проверит сам:

- `DATABASE_URL` обязан начинаться с `postgresql://` или `postgres://` (`database.py:240`);
- `PUBLIC_ORIGIN` — строгий **HTTPS** origin без пути, логина и параметров
  (`web_ui.py:102-107`), иначе `ValueError('PUBLIC_ORIGIN: нужен точный HTTPS-адрес…')`;
- `AI_REST_TOKEN` — ≥ 24 символов ASCII без пробелов (`ai_rest_client.py:27`,
  `ai_rest_server.py:204`).

### Шаг 6. Ключ ИИ-провайдера

Файл `config.local.json` **не переносится** с рабочей машины — создайте новый с
выданным ключом. Формат (на примере GigaChat):

```json
{
  "authorization_key": "СЮДА_ОДНОЙ_СТРОКОЙ_НОВЫЙ_КЛЮЧ",
  "scope": "GIGACHAT_API_PERS",
  "model": "pro",
  "verify_ssl": true
}
```

```bash
chmod 600 /opt/trainer112/config.local.json
chown trainer:trainer /opt/trainer112/config.local.json
```

Допустимые переменные вместо файла: `AI_AUTHORIZATION_KEY`, `AI_PROVIDER`,
`AI_BASE_URL`, `AI_MODEL`, `AI_SCOPE`, `AI_CA_BUNDLE`, путь через `AI_PROJECT_CONFIG`
(`provider.py:87-123`). Ключ — одна строка без пробелов (`provider.py:102`).
Для GigaChat нужен корневой сертификат НУЦ: `certs/ai_provider_root_ca.pem`
или `AI_CA_BUNDLE` (`provider.py:134`).

### Шаг 7. Миграции и первый администратор

```bash
cd /opt/trainer112
set -a; . ./.env.server; set +a
sudo -u trainer .venv/bin/python manage_db.py migrate
sudo -u trainer .venv/bin/python manage_users.py bootstrap-admin
# либо: manage_users.py create admin "Администратор" admin
sudo -u trainer .venv/bin/python manage_users.py list
```

Пароль запрашивается через `getpass` (в историю shell не попадает), минимум 10 символов
(`shared_auth.py:29`, `manage_users.py:63,76`).

Перенос старых данных — **один раз и осознанно**, иначе он перезапишет рабочую БД:

```bash
sudo -u trainer .venv/bin/python manage_db.py import-legacy --data-dir data
# для объединения с заполненной базой добавьте --merge
```

### Шаг 8. systemd

`/etc/systemd/system/trainer112-ai.service`:

```ini
[Unit]
Description=Trainer112 dedicated AI REST
After=network-online.target postgresql.service

[Service]
Type=simple
User=trainer
WorkingDirectory=/opt/trainer112
EnvironmentFile=/opt/trainer112/.env.server
ExecStart=/opt/trainer112/.venv/bin/python ai_rest_server.py --host 127.0.0.1 --port 8890
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/trainer112-web.service`:

```ini
[Unit]
Description=Trainer112 shared server
After=network-online.target postgresql.service trainer112-ai.service

[Service]
Type=simple
User=trainer
WorkingDirectory=/opt/trainer112
EnvironmentFile=/opt/trainer112/.env.server
ExecStart=/opt/trainer112/.venv/bin/python web_ui.py \
  --shared-server --require-postgres --auto-migrate \
  --host 127.0.0.1 --port 8878 --no-browser
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/trainer112

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now trainer112-ai trainer112-web
systemctl status trainer112-web --no-pager
journalctl -u trainer112-web -n 50 --no-pager
```

### Шаг 9. nginx

```nginx
limit_req_zone $binary_remote_addr zone=login:10m rate=1r/m;

server {
    listen 443 ssl http2;
    server_name trainer.example.org;

    ssl_certificate     /etc/letsencrypt/live/trainer.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/trainer.example.org/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" always;

    # PUT /api/v1/workshop принимает до 8 МБ (web_ui.py:334)
    client_max_body_size 10m;

    location = /login {
        limit_req zone=login burst=3 nodelay;
        proxy_pass http://127.0.0.1:8878;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location / {
        proxy_pass http://127.0.0.1:8878;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}

server {
    listen 80;
    server_name trainer.example.org;
    return 301 https://$host$request_uri;
}
```

```bash
nginx -t && systemctl reload nginx
```

**Критично про `proxy_set_header Host`:** проверка доступа устроена так
(`web_ui.py:471-482`), что запрос проходит, только если заголовок `Host` **в точности**
равен `netloc` из `PUBLIC_ORIGIN` (или это `127.0.0.1:порт` в classroom-режиме).
Если nginx передаст другой `Host`, пользователи получат `403 «Доступ только через 127.0.0.1»`.
Если `PUBLIC_ORIGIN` указан с портом — `Host` тоже должен приходить с портом.

### Шаг 10. Сертификат

```bash
certbot --nginx -d trainer.example.org --redirect
```

### Шаг 11. Firewall

```bash
ufw default deny incoming
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ss -ltnp    # 8878/8890/5432 должны слушать только 127.0.0.1
```

### Шаг 12. Бэкапы

Резервируется **PostgreSQL**, а не папка `data` (`SHARED_SERVER.md`, раздел
«Резервное копирование»):

```bash
cat > /usr/local/bin/trainer112-backup.sh <<'SH'
#!/bin/sh
set -a; . /opt/trainer112/.env.server; set +a
mkdir -p /var/backups/trainer112
pg_dump -Fc "$DATABASE_URL" -f "/var/backups/trainer112/trainer112-$(date +%F).backup"
find /var/backups/trainer112 -name '*.backup' -mtime +14 -delete
SH
chmod 700 /usr/local/bin/trainer112-backup.sh
# cron: 30 3 * * * root /usr/local/bin/trainer112-backup.sh
```

Восстановление проверяется **на стенде**, а не в момент аварии:
`pg_restore -d новая_база файл.backup`.

---

## 5. Проверка после запуска

```bash
curl -s https://trainer.example.org/api/v1/health
```

Ожидается `"backend": "postgresql"` и номер схемы (сейчас миграций 5 — `migrations/`).
Если там `files` — серверный режим не включился, проверьте `DATABASE_URL` и
наличие флага `--require-postgres`.

| Проверка | Ожидаемый результат |
|---|---|
| `ss -ltnp` | 8878, 8890, 5432 — только на `127.0.0.1` |
| `curl http://IP:8878/` снаружи | соединение не установлено (порт закрыт) |
| DevTools → Application → Cookies | `trainer112_session` с флагами `Secure`, `HttpOnly`, `SameSite=Lax` (`web_ui.py:115-152`) |
| `curl -i https://…/api` | `410` — legacy RPC в серверном режиме отключён (`web_ui.py:608-611`) |
| `curl -i -X POST https://…/admin-reset/confirm` | `404/410` — локальный сброс отключён (`web_ui.py:592-597`) |
| `curl -I https://…` | TLS A+ на ssllabs, HSTS и CSP в ответе |
| Вход с 3-го неверного пароля за минуту | `503` от nginx (`limit_req`), срабатывание fail2ban |
| `/login` → `/admin` | редирект по роли (`web_ui.py:155-157`) |
| Диалог с заявителем | `dialogue_rest.state = available` в ответе API (`ai_rest_client.py:90-104`) |

---

## 6. Обновление версии

```bash
systemctl stop trainer112-web
rsync -a --delete --exclude .venv --exclude .env.server --exclude config.local.json \
      --exclude data ./ new_build/ root@host:/opt/trainer112/
cd /opt/trainer112 && set -a && . ./.env.server && set +a
sudo -u trainer .venv/bin/python manage_db.py migrate   # миграции не удаляют данные
chown -R trainer:trainer /opt/trainer112
systemctl start trainer112-web && systemctl status trainer112-web --no-pager
```

Если менялся `frontend/src` — пересоберите бандл на Windows
(`node build.mjs` в `frontend/`) и скопируйте `ui/react/app.js`.

---

## 7. Безопасность: что уже есть и что нужно закрыть

### Реализовано в коде

| Механизм | Место |
|---|---|
| PBKDF2-SHA256, 260 000 итераций, сравнение `hmac.compare_digest` | `shared_auth.py:20,34-45` |
| Минимум 10 символов в пароле, валидация логина и роли | `shared_auth.py:24-31` |
| Сессионная cookie `HttpOnly`, `SameSite=Lax`, `Secure` при HTTPS | `web_ui.py:115-152` |
| Сессии в PostgreSQL (`auth_sessions`), срок 12 ч | `shared_auth.py:21,135-151` |
| Строгая проверка `Origin` против `PUBLIC_ORIGIN` | `web_ui.py:231-233` |
| Валидация `PUBLIC_ORIGIN` как HTTPS-origin без пути | `web_ui.py:102-107` |
| Отзыв сессий при блокировке и при смене пароля | `shared_auth.py:236,245,251` (`revoke_user_sessions`) |
| Legacy `/api` и локальный сброс админа отключены в серверном режиме | `web_ui.py:592-611` |
| Секреты в `.gitignore`: `config.local.json`, `data/`, `.venv/`, `.runtime/` | `.gitignore` |
| Пароли через `getpass`, а не через argv | `manage_users.py:63,76` |

### Обязательно доработать/настроить на публичном сервере

1. **Никакого `--host 0.0.0.0`.** В этом режиме `local_host()` (`web_ui.py:471-482`)
   считает «своим» любой приватный адрес — обход ограничений из внутренней сети/VPN.
2. **`PUBLIC_ORIGIN` обязателен.** Без него cookie выдаётся **без `Secure`**, а значит
   пароль и сессия уходят открытым текстом; плюс ломается строгая проверка `Origin`.
3. **Подбора пароля нет.** В коде отсутствуют счётчики неудачных попыток, блокировки
   учётных записей и троттлинг — только `limit_req` в nginx и fail2ban.
4. **Приложение не пишет HTTP-логи**: `log_message` — пустая функция
   (`web_ui.py:163-165`), а `X-Forwarded-For` нигде не читается. Единственный источник
   IP-адресов клиента — access-лог nginx. Логи nginx включите и заведите logrotate.
5. **Заголовков безопасности в приложении нет** (CSP, `X-Frame-Options`,
   `X-Content-Type-Options`, `Referrer-Policy`) — их добавляет nginx (см. Шаг 9).
6. **TTL сессии 12 часов без скользящего отзыва** (`shared_auth.py:21`) — сократите,
   если риск компрометации выше лабораторного.
7. **`config.local.json` с ключом ИИ не переносить** с рабочей машины; выдать новый
   ключ и отозвать старый, если папка когда-либо архивировалась или пересылалась.
8. **`.env.server` НЕ включён в `.gitignore`** — а именно в нём лежат `DATABASE_URL`
   с паролем БД и `AI_REST_TOKEN`. В игноре есть `data/` (следовательно и
   `data/accounts.sqlite3` локального режима) и `config.local.json`, но не этот файл.
   При появлении git обязательно добавьте `.env.server`, иначе пароль базы уедет в историю
   коммитов. Файл в репозитории не создавайте — только на сервере, с `chmod 600`.
9. **Аудита действий** (кто создал/изменил/удалил) в коде нет — при требованиях
   к отчётности организуйте его отдельным слоем.
10. **Один процесс, стандартная библиотека HTTP.** Годится для учебной группы,
    не для высокой нагрузки; держите один экземпляр за проксией и считайте ёмкость
    по §3.

---

## 8. Типичные ошибки

| Симптом | Причина и решение |
|---|---|
| `PUBLIC_ORIGIN: нужен точный HTTPS-адрес общего сервера без пути` | В `PUBLIC_ORIGIN` попал путь, `http://`, логин или порт не по формату (`web_ui.py:102-107`) |
| `Сервер запущен не через PostgreSQL (backend=files)` | Не задан `DATABASE_URL`; `START_SHARED_SERVER` с `--require-postgres` прервёт запуск (`START_SHARED_SERVER.ps1:156`) |
| `Для серверного режима задайте DATABASE_URL` | Рядом с процессом нет окружения: проверьте `EnvironmentFile` в systemd |
| `Получена неполная копия интерфейса. Отсутствуют: ui/…` | Папка скопирована частично — загрузите `ui/` целиком (`ui_release.py:25-29`) |
| `403 «Доступ только через 127.0.0.1»` при работе через домен | `proxy_set_header Host` не совпадает с `netloc` из `PUBLIC_ORIGIN` (`web_ui.py:471-482`) |
| `403 Этот Origin не разрешён для API` | Другой домен/протокол в браузере, либо забыт `--allowed-origin` для отдельного фронтенда (`web_ui.py:231-233,653`) |
| `AI_REST_TOKEN не настроен` / `отклонил AI_REST_TOKEN` | Токен короче 24 символов или **разный** в двух сервисах (`ai_rest_client.py:26-28`) |
| `Нет связи с выделенным ИИ REST API` | Не запущен `trainer112-ai`, либо `AI_DIALOGUE_REST_URL` указывает не туда (`ai_rest_client.py:85`) |
| `ИИ: ключ содержит пробелы или недопустимые символы` | Ключ перенесён с переносом строки — одной строкой (`provider.py:102`) |
| `ИИ (…): не удалось проверить защищённое соединение` | Для GigaChat не найден корневой сертификат НУЦ: `certs/ai_provider_root_ca.pem` или `AI_CA_BUNDLE` (`provider.py:134,157`) |
| `413 payload_too_large` | Превышен лимит тела в приложении: 250 КБ по умолчанию, 8 МБ для `PUT /api/v1/workshop` (`web_ui.py:193,334`) |
| Порт 8878 занят | Старый экземпляр: `ss -ltnp`, остановите предыдущий процесс |
| `ui-error.log` в корне проекта | Приложение упало на старте и записало исключение туда (`web_ui.py:704`) |
| Озвучка не работает | Piper не собран под Linux — это штатная деградация, используется браузерный голос |

---

## 9. Полезные команды

```bash
journalctl -u trainer112-web -f          # журнал backend
journalctl -u trainer112-ai -f           # журнал AI REST
.venv/bin/python manage_users.py list
.venv/bin/python manage_users.py password 3
.venv/bin/python manage_users.py update 3 --disable
.venv/bin/python manage_db.py status
.venv/bin/python check_ai.py             # проверка подключения ИИ
pg_dump -Fc "$DATABASE_URL" -f trainer112.backup
```

Сброс забытого администратора: `RESET_ADMIN.ps1` (Windows-машина) или
`manage_users.py create`/`password` на сервере — подробности в `RESET_ADMIN_README.txt`.

---

## 10. Документация в проекте

- `SHARED_SERVER.md` — режим общего сервера, PostgreSQL, публикация за reverse proxy
- `AUTH_ROLES.md` — системные и учебные роли, вход
- `REST_API.md`, `AI_REST_API.md`, `openapi.json` — контракт API
- `POSTGRESQL_WITHOUT_DOCKER.md` — БД без Docker
- `AI_CONTRACT.md` — поведение ИИ-компонентов
- `README.md` — общий обзор и сценарии запуска

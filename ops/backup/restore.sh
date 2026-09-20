#!/bin/sh
# Восстановление базы стенда из резервной копии.
#
# Запускается в том же контейнере, что и копирование, поэтому версия
# клиентских утилит заведомо совпадает с версией сервера, а сеть и пароль
# уже настроены. Порядок применения — в docs/backup.md.
#
# Использование (из каталога проекта на сервере):
#   docker compose -f docker-compose.prod.yml run --rm -e CONFIRM=yes \
#       backup sh /opt/backup/restore.sh [имя-файла-копии]
# Без имени файла берётся последняя копия.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"

log() {
    echo "[restore] $*"
}

die() {
    log "ОШИБКА: $*"
    exit 1
}

case "${1:-}" in
    "")  source="${BACKUP_DIR}/latest.dump" ;;
    /*)  source="$1" ;;
    *)   source="${BACKUP_DIR}/$1" ;;
esac

[ -s "$source" ] || die "копия ${source} не найдена или пуста"

# Восстановление уничтожает текущее содержимое базы, поэтому оно не должно
# случаться из-за опечатки в команде.
[ "${CONFIRM:-}" = "yes" ] || die "повторите команду с CONFIRM=yes — база ${PGDATABASE} будет заменена"

log "проверяю архив $(basename "$source")"
pg_restore --list "$source" > /dev/null 2>&1 || die "архив повреждён, восстанавливать нечем"

# База удаляется и создаётся заново, а не восстанавливается поверх: при
# наложении копии на живую базу всё, чего в копии нет (строки, добавленные
# после снимка; таблицы, удалённые миграцией), осталось бы на месте, и
# состояние получилось бы смешанным — ни прежним, ни восстановленным.
# FORCE отцепляет оставшиеся подключения: приложение может быть ещё поднято.
log "пересоздаю базу ${PGDATABASE}"
psql --dbname=postgres --set=ON_ERROR_STOP=1 --quiet \
    --command="DROP DATABASE IF EXISTS \"${PGDATABASE}\" WITH (FORCE)"
psql --dbname=postgres --set=ON_ERROR_STOP=1 --quiet \
    --command="CREATE DATABASE \"${PGDATABASE}\""

# --exit-on-error обязателен: без него pg_restore досыпает ошибки в вывод и
# завершается успешно, то есть частичное восстановление выглядело бы удачным.
# --no-owner/--no-privileges позволяют развернуть копию под другой учётной
# записью, чем та, под которой она снята (например, на запасном сервере).
log "разворачиваю копию"
pg_restore --dbname="${PGDATABASE}" --no-owner --no-privileges --exit-on-error "$source"

tables="$(psql --dbname="${PGDATABASE}" --tuples-only --no-align \
    --command="SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
users="$(psql --dbname="${PGDATABASE}" --tuples-only --no-align \
    --command="SELECT count(*) FROM app_user")"

log "готово: таблиц ${tables}, учётных записей ${users}"
log "перезапустите приложение: docker compose -f docker-compose.prod.yml up -d backend"

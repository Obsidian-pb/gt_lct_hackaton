#!/bin/sh
# Снимок базы стенда в сжатый архив с проверкой пригодности архива.
#
# Формат custom, а не текстовый SQL: pg_dump сжимает его сам (не нужен ни
# внешний gzip, ни временный несжатый файл на диске) и, главное, такой архив
# читается `pg_restore --list`. Это единственный способ убедиться, что копия
# не оборвана, не разворачивая её в живую базу.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP="${BACKUP_KEEP:-14}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${BACKUP_DIR}/${PGDATABASE}-${STAMP}.dump"
# Пишем под временным именем и переименовываем только после проверки:
# оборванный дамп (упал контейнер, кончилось место на диске) не должен
# остаться в каталоге и выглядеть как готовая копия.
PARTIAL="${BACKUP_DIR}/.partial-${STAMP}.dump"

log() {
    echo "[backup] $(date -u '+%Y-%m-%d %H:%M:%SZ') $*"
}

fail() {
    log "ОШИБКА: $*"
    rm -f "$PARTIAL"
    # Отметка о неудаче нужна администратору: по ней видно, когда именно
    # сломалось, даже если логи контейнера уже провернулись по размеру.
    printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" > "${BACKUP_DIR}/last-failure"
    exit 1
}

mkdir -p "$BACKUP_DIR" || fail "каталог ${BACKUP_DIR} недоступен на запись"

log "снимаю копию базы ${PGDATABASE} с узла ${PGHOST}"
pg_dump --format=custom --compress=6 --file="$PARTIAL" \
    || fail "pg_dump завершился с ошибкой"

pg_restore --list "$PARTIAL" > /dev/null 2>&1 \
    || fail "архив не читается pg_restore — копия непригодна"

# Читаемый, но пустой архив тоже брак: так выглядит дамп базы, к которой
# подключились раньше, чем накатились миграции.
entries="$(pg_restore --list "$PARTIAL" 2>/dev/null | grep -cv '^;' || true)"
[ "${entries:-0}" -ge 1 ] || fail "архив читается, но не содержит объектов"

mv "$PARTIAL" "$TARGET"
# Ссылка на последнюю копию: восстановление и проверка состояния не должны
# требовать от человека разбираться в именах файлов.
ln -sfn "$(basename "$TARGET")" "${BACKUP_DIR}/latest.dump"

# Отметка об успехе в машинном виде — по ней healthcheck.sh решает, жив ли
# график копирования. Секунды эпохи, чтобы не разбирать даты в busybox.
printf '%s %s\n' "$(date -u +%s)" "$STAMP" > "${BACKUP_DIR}/last-success"

log "готово: $(basename "$TARGET"), $(du -h "$TARGET" | cut -f1), объектов в архиве: ${entries}"

# Ротация по количеству копий. Считаем по маске с завершающим Z, чтобы под
# удаление не попали ни служебные отметки, ни ссылка latest.dump.
total="$(ls -1t "${BACKUP_DIR}"/*Z.dump 2>/dev/null | wc -l)"
if [ "$total" -gt "$KEEP" ]; then
    ls -1t "${BACKUP_DIR}"/*Z.dump | tail -n +"$((KEEP + 1))" | while read -r old; do
        rm -f "$old" && log "удалена устаревшая копия $(basename "$old")"
    done
fi

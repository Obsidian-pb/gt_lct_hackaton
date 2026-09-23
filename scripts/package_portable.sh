#!/bin/sh
# Переносной комплект для Windows: работает без Docker и без установки.
#
# На выходе — dist/dds112-portable.zip: папка, которую копируют на диск
# и запускают start.cmd. Внутри — встраиваемый Python с зависимостями,
# PostgreSQL, сервер llama.cpp с моделью, наш код и собранный интерфейс.
# Права администратора на месте не нужны: ничего не устанавливается,
# службы не регистрируются, порты открываются только на 127.0.0.1.
#
# Собирается на Mac или Linux: все составляющие — готовые сборки под
# Windows x64, скачиваются один раз в кэш и дальше переиспользуются.
# Проверить результат можно только на Windows — этот скрипт лишь
# собирает и проверяет состав, запустить комплект здесь нельзя.
#
#     sh scripts/package_portable.sh            # полный комплект, ~2,7 ГБ
#     sh scripts/package_portable.sh --update   # только наш код и фронт,
#                                               # ~40 МБ, распаковывается поверх
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CACHE="${DDS112_CACHE:-$HOME/.cache/dds112-portable}"
OUT="${OUT:-$ROOT/dist}"
KIT="$OUT/dds112-portable"
MODE="${1:-full}"

PY_VER="3.12.10"
PG_VER="17.6-1"
LLAMA_TAG="b11136"
MODEL_FILE="${LLM_MODEL_FILE:-Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"

PY_ZIP="python-$PY_VER-embed-amd64.zip"
PG_ZIP="postgresql-$PG_VER-windows-x64-binaries.zip"
LLAMA_ZIP="llama-$LLAMA_TAG-bin-win-cpu-x64.zip"

fetch() {
  # $1 — имя файла в кэше, $2 — адрес. Докачивается при обрыве.
  [ -f "$CACHE/$1" ] && return 0
  echo "==> скачиваю $1"
  curl -fSL --retry 10 --retry-all-errors --retry-delay 10 -C - -o "$CACHE/$1" "$2"
}

crlf() {
  # Файлы cmd обязаны быть с переводами строк CRLF: с LF cmd путается
  # в метках и многострочных блоках. В репозитории они хранятся с LF.
  perl -pe 's/\r?\n/\r\n/' "$1" > "$2"
}

mkdir -p "$CACHE/wheels"

# --- Наш код: нужен в обоих режимах ------------------------------------------
echo "==> фронтенд (адрес API пустой: раздаёт тот же сервер)"
( cd frontend && VITE_API_BASE="" npm run build >/dev/null )

echo "==> классификатор"
[ -f backend/data/ekp.json ] || backend/.venv/bin/python backend/scripts/parse_ekp.py \
  --src classificator.xlsx --dst backend/data/ekp.json

rm -rf "$KIT"
mkdir -p "$KIT/app/backend/data" "$KIT/app/web" "$KIT/runtime"

echo "==> код приложения"
for d in app scripts migrations certs; do
  rsync -a --exclude __pycache__ --exclude '*.pyc' "backend/$d/" "$KIT/app/backend/$d/"
done
cp backend/alembic.ini "$KIT/app/backend/"
cp backend/data/ekp.json backend/data/tickets.json backend/data/ticket_rules.json "$KIT/app/backend/data/"
rsync -a frontend/dist/ "$KIT/app/web/"

crlf ops/portable/start.cmd "$KIT/start.cmd"
crlf ops/portable/stop.cmd "$KIT/stop.cmd"
crlf ops/portable/settings.example.cmd "$KIT/settings.example.cmd"
# Памятка — с BOM: так Блокнот старых Windows не примет UTF-8 за кодировку 1251.
printf '\xEF\xBB\xBF' > "$KIT/README-ЗАПУСК.txt"
perl -pe 's/\r?\n/\r\n/' "ops/portable/README-ЗАПУСК.txt" >> "$KIT/README-ЗАПУСК.txt"
mkdir -p "$KIT/runtime"
cp ops/portable/wait_health.py ops/portable/lan_addresses.py "$KIT/runtime/"

if [ "$MODE" = "--update" ]; then
  mkdir -p "$OUT"
  rm -f "$OUT/dds112-update.zip"
  ( cd "$KIT" && zip -q -r -n .mp3 "$OUT/dds112-update.zip" app start.cmd stop.cmd settings.example.cmd "README-ЗАПУСК.txt" runtime/wait_health.py runtime/lan_addresses.py )
  rm -rf "$KIT"
  echo "готово: $OUT/dds112-update.zip ($(du -h "$OUT/dds112-update.zip" | cut -f1))"
  echo "на месте: stop.cmd, распаковать поверх папки комплекта с заменой, start.cmd"
  exit 0
fi

# --- Среды выполнения ---------------------------------------------------------
fetch "$PY_ZIP" "https://www.python.org/ftp/python/$PY_VER/$PY_ZIP"
fetch "$PG_ZIP" "https://get.enterprisedb.com/postgresql/$PG_ZIP"
fetch "$LLAMA_ZIP" "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_TAG/$LLAMA_ZIP"
[ -f "$CACHE/$MODEL_FILE" ] || cp "ops/llm/models/$MODEL_FILE" "$CACHE/$MODEL_FILE" 2>/dev/null || {
  echo "нет файла модели: ни в $CACHE, ни в ops/llm/models — сначала sh ops/llm/fetch_model.sh" >&2
  exit 1
}

echo "==> Python: встраиваемая сборка и зависимости под Windows"
mkdir -p "$KIT/runtime/python"
unzip -q -o "$CACHE/$PY_ZIP" -d "$KIT/runtime/python"
# Встраиваемый Python по умолчанию не видит site-packages — включается
# правкой файла путей. Строка `import site` там закомментирована намеренно.
cat > "$KIT/runtime/python/python312._pth" <<'EOF'
python312.zip
.
Lib\site-packages
import site
EOF
# uvicorn[standard] тянет uvloop, которого под Windows нет; на Windows
# достаточно обычного uvicorn. colorama и tzdata pip добавил бы сам,
# но их условия зависят от платформы сборщика, а не целевой.
grep -vE '^pytest' backend/requirements.txt | sed -E 's/^uvicorn\[standard\]/uvicorn/' > "$CACHE/requirements-win.txt"
printf 'colorama\ntzdata\n' >> "$CACHE/requirements-win.txt"
# Сначала колёса складываются в кэш (уже скачанные pip пропускает), потом
# раскладываются из кэша без обращения к сети: так повторная сборка не
# зависит от связи, а состав зависимостей одинаков от сборки к сборке.
pip3 download -q --only-binary=:all: --platform win_amd64 --python-version 3.12 \
  --implementation cp --abi cp312 -r "$CACHE/requirements-win.txt" -d "$CACHE/wheels" 2>&1 | grep -v "Cache entry" || true
pip3 install -q --only-binary=:all: --platform win_amd64 --python-version 3.12 \
  --implementation cp --abi cp312 --target "$KIT/runtime/python/Lib/site-packages" \
  --no-index --find-links "$CACHE/wheels" -r "$CACHE/requirements-win.txt"
find "$KIT/runtime/python/Lib/site-packages" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -rf "$KIT/runtime/python/Lib/site-packages/bin"

echo "==> PostgreSQL: только bin, lib и share"
mkdir -p "$KIT/runtime/pgsql"
unzip -q -o "$CACHE/$PG_ZIP" 'pgsql/bin/*' 'pgsql/lib/*' 'pgsql/share/*' -d "$KIT/runtime"
rm -rf "$KIT/runtime/pgsql/share/doc" "$KIT/runtime/pgsql/share/man" "$KIT/runtime/pgsql/bin/pgAdmin*"

echo "==> llama.cpp: только сервер"
mkdir -p "$KIT/runtime/llama"
unzip -q -o "$CACHE/$LLAMA_ZIP" -d "$KIT/runtime/llama"
find "$KIT/runtime/llama" -name '*.exe' ! -name 'llama-server.exe' -delete

echo "==> библиотеки Visual C++"
# PostgreSQL и llama.cpp собраны MSVC и ждут msvcp140/vcruntime140 рядом
# с собой или в системе. На чистой Windows их может не быть, а ставить
# распространяемый пакет — это права администратора. Библиотеки кладутся
# рядом с каждым exe: так разрешено лицензией на распространяемые файлы.
if [ ! -f "$CACHE/vcruntime/msvcp140.dll" ]; then
  mkdir -p "$CACHE/vcruntime" "$CACHE/msvc-tmp"
  pip3 download -q --only-binary=:all: --platform win_amd64 --python-version 3.12 \
    --implementation cp --abi cp312 --no-deps msvc-runtime -d "$CACHE/msvc-tmp"
  unzip -q -o "$CACHE"/msvc-tmp/msvc_runtime-*.whl -d "$CACHE/msvc-tmp/unpacked"
  find "$CACHE/msvc-tmp/unpacked" -iname '*.dll' -exec cp -f {} "$CACHE/vcruntime/" \;
  rm -rf "$CACHE/msvc-tmp"
fi
for target in pgsql/bin llama python; do
  cp "$CACHE"/vcruntime/*.dll "$KIT/runtime/$target/"
done

echo "==> модель"
mkdir -p "$KIT/models"
cp "$CACHE/$MODEL_FILE" "$KIT/models/$MODEL_FILE"

# --- Проверка состава: то, без чего start.cmd точно не отработает ------------
for f in runtime/python/python.exe runtime/python/Lib/site-packages/uvicorn/__init__.py \
         runtime/python/Lib/site-packages/psycopg_binary/__init__.py \
         runtime/pgsql/bin/initdb.exe runtime/pgsql/bin/pg_ctl.exe runtime/pgsql/bin/postgres.exe \
         runtime/pgsql/share/postgres.bki runtime/llama/llama-server.exe runtime/llama/msvcp140.dll \
         app/backend/app/main.py app/backend/data/ekp.json app/web/index.html app/web/audio/ticket-1-1.mp3 \
         "models/$MODEL_FILE" start.cmd stop.cmd; do
  [ -e "$KIT/$f" ] || { echo "в комплекте нет $f" >&2; exit 1; }
done
# Иероглифов и LF в cmd быть не должно: первое — опечатка ввода, второе ломает cmd.
# perl, а не grep -P: у grep в macOS этого ключа нет, и проверка молча
# проходила бы мимо.
if perl -CSD -ne 'exit 1 if /[\x{4e00}-\x{9fff}]/' "$KIT/start.cmd" "$KIT/stop.cmd" "$KIT/README-ЗАПУСК.txt"; then :; else
  echo "в файлах комплекта иероглифы" >&2; exit 1
fi
for f in start.cmd stop.cmd settings.example.cmd; do
  perl -ne 'exit 1 unless /\r\n\z/' "$KIT/$f" || { echo "$f не в CRLF" >&2; exit 1; }
done

echo "==> архив"
mkdir -p "$OUT"
rm -f "$OUT/dds112-portable.zip"
# Модель, DLL и mp3 не сжимаются — их складываем без сжатия, это в разы быстрее.
( cd "$OUT" && zip -q -r -n .gguf:.dll:.pyd:.mp3:.exe dds112-portable.zip dds112-portable )
rm -rf "$KIT"

echo
echo "готово: $OUT/dds112-portable.zip ($(du -h "$OUT/dds112-portable.zip" | cut -f1))"
echo "на Windows: распаковать на диск, дважды щёлкнуть start.cmd"

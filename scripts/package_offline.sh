#!/bin/sh
# Сборка поставки для изолированного контура.
#
# На выходе — каталог dist/ с двумя вещами:
#   dds112-images.tar   все образы комплекса, включая модель: docker load -i
#   dds112-deploy/      файлы развёртывания: compose, скрипты копий, .env.example
#
# Образы собираются под linux/amd64 независимо от машины сборщика: серверы
# и рабочие места заказчика — x86-64, а разработка идёт на Apple Silicon,
# где образ по умолчанию получился бы arm64 и на месте не запустился.
# Сборка под чужую архитектуру идёт через эмуляцию и занимает заметно
# дольше обычной — это цена одного архива вместо инструкции по сборке.
#
#     sh scripts/package_offline.sh              # dist/
#     PLATFORM=linux/arm64 sh scripts/package_offline.sh   # для проверки на Mac
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PLATFORM="${PLATFORM:-linux/amd64}"
OUT="${OUT:-$ROOT/dist}"
MODEL_FILE="${LLM_MODEL_FILE:-Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"
LLM_TAG="${LLM_IMAGE_TAG:-qwen3-4b}"

[ -f "ops/llm/models/$MODEL_FILE" ] || {
  echo "нет файла модели ops/llm/models/$MODEL_FILE — сначала: sh ops/llm/fetch_model.sh" >&2
  exit 1
}

# Сборке значения переменных не нужны, но compose требует их наличия:
# обязательные переменные объявлены через `:?` и проверяются при разборе файла.
BUILD_ENV="$(mktemp)"
trap 'rm -f "$BUILD_ENV"' EXIT
cat > "$BUILD_ENV" <<EOF
DB_USER=build
DB_PASSWORD=build
DB_NAME=build
SECRET_KEY=build-only-value-not-used-at-runtime-000
DEMO_PASSWORD=build
LLM_MODEL_FILE=$MODEL_FILE
LLM_IMAGE_TAG=$LLM_TAG
EOF

COMPOSE="docker compose -p dds112 --env-file $BUILD_ENV -f docker-compose.prod.yml -f docker-compose.offline.yml"

echo "==> образы под $PLATFORM"
DOCKER_DEFAULT_PLATFORM="$PLATFORM" $COMPOSE build --pull
docker pull --platform "$PLATFORM" postgres:17-alpine

mkdir -p "$OUT/dds112-deploy"
echo "==> архив образов"
# --platform обязателен: под одним тегом могут лежать варианты для разных
# архитектур (образ базы уже скачан на Mac как arm64), и без указания
# платформы в архив уходит тот, что попался первым. Флаг есть с Docker 28.
docker save --platform "$PLATFORM" -o "$OUT/dds112-images.tar" \
  dds112-backend:latest \
  dds112-web:latest \
  "dds112-llm:$LLM_TAG" \
  postgres:17-alpine

echo "==> файлы развёртывания"
cp docker-compose.prod.yml docker-compose.offline.yml "$OUT/dds112-deploy/"
mkdir -p "$OUT/dds112-deploy/ops"
cp -R ops/backup "$OUT/dds112-deploy/ops/"
# Не backend/.env.example: тот описывает переменные процесса для разработки.
# Развёртыванию нужны шесть переменных compose — и ничего лишнего.
cat > "$OUT/dds112-deploy/.env.example" <<'EOF'
# Скопировать в .env и заполнить. Без первых пяти переменных compose
# намеренно не стартует.
DB_USER=trainer
DB_PASSWORD=
DB_NAME=trainer
SECRET_KEY=
DEMO_PASSWORD=
WEB_PORT=8090
# Ресурсы контейнера модели: по умолчанию 4 ядра и 4 ГБ.
# LLM_THREADS=4
# LLM_CPUS=4.0
# LLM_MEM_LIMIT=4g
EOF
cp docs/windows.md "$OUT/dds112-deploy/ЗАПУСК-НА-WINDOWS.md"
# Образы уже собраны — на месте `build:` только помешает: без исходников
# compose откажется собирать. Секция вырезается из копии для поставки.
python3 - "$OUT/dds112-deploy" "$LLM_TAG" <<'EOF'
import re, sys, pathlib
folder, tag = pathlib.Path(sys.argv[1]), sys.argv[2]
prod = folder / "docker-compose.prod.yml"
text = prod.read_text(encoding="utf-8")
text = re.sub(r"\n    build:\n      context: \.\n      dockerfile: backend/Dockerfile\n",
              "\n    image: dds112-backend:latest\n", text)
text = re.sub(r"\n    build:\n      context: \./frontend\n      dockerfile: Dockerfile\n",
              "\n    image: dds112-web:latest\n", text)
assert "build:" not in text, "в docker-compose.prod.yml осталась секция build"
prod.write_text(text, encoding="utf-8")
off = folder / "docker-compose.offline.yml"
text = off.read_text(encoding="utf-8")
text = re.sub(r"\n    build:\n      context: \./ops/llm\n      args:\n        MODEL_FILE: [^\n]+\n", "\n", text)
assert "build:" not in text, "в docker-compose.offline.yml осталась секция build"
off.write_text(text, encoding="utf-8")
EOF

echo
echo "готово:"
du -h "$OUT/dds112-images.tar" | sed 's/^/  /'
echo "  $OUT/dds112-deploy/"
echo
echo "на месте: docker load -i dds112-images.tar; в dds112-deploy заполнить .env и"
echo "  docker compose -f docker-compose.prod.yml -f docker-compose.offline.yml up -d"

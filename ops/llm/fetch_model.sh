#!/bin/sh
# Получение файла модели для образа ops/llm.
#
# Единственный шаг поставки, которому нужен интернет, — и выполняется он
# один раз, на машине сборщика, а не в контуре. Скачивание докачивается
# при обрыве: файл на гигабайты, а связь бывает всякая.
#
#     sh ops/llm/fetch_model.sh              # Qwen3 4B Instruct, ~2,3 ГБ
#     sh ops/llm/fetch_model.sh 8b           # Qwen3 8B, ~4,7 ГБ — точнее, но
#                                            # вдвое медленнее и тяжелее
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)/models"
mkdir -p "$DIR"

case "${1:-4b}" in
  4b)
    FILE="Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    URL="https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/$FILE"
    ;;
  8b)
    FILE="Qwen3-8B-Q4_K_M.gguf"
    URL="https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/$FILE"
    ;;
  *)
    echo "неизвестный вариант: $1 (ожидается 4b или 8b)" >&2
    exit 2
    ;;
esac

echo "модель: $FILE"
echo "в каталог: $DIR"
# --retry-all-errors: обрыв посреди файла тоже повод повторить, не только
# ошибка соединения. -C - продолжает с того места, где оборвалось.
curl -fSL --retry 10 --retry-all-errors --retry-delay 10 -C - -o "$DIR/$FILE" "$URL"
echo "готово: $(du -h "$DIR/$FILE" | cut -f1)"
echo "сборка образа: docker compose -f docker-compose.prod.yml -f docker-compose.offline.yml build llm"
[ "$FILE" = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf" ] || \
  echo "для этой модели при сборке задайте LLM_MODEL_FILE=$FILE"

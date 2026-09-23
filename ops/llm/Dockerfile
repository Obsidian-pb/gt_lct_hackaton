# Языковая модель внутри контура.
#
# Образ llama.cpp с сервером, совместимым с API OpenAI, и файлом модели
# внутри самого образа. Веса не скачиваются при запуске и не лежат отдельным
# томом: поставка в изолированный контур — это один архив `docker save`,
# и второй артефакт, который можно забыть на флешке, здесь лишний.
#
# Файл модели кладётся в ops/llm/models/ заранее (ops/llm/fetch_model.sh);
# имя передаётся аргументом сборки, чтобы сменить модель без правки файла.
FROM ghcr.io/ggml-org/llama.cpp:server

ARG MODEL_FILE=Qwen3-4B-Instruct-2507-Q4_K_M.gguf
COPY models/${MODEL_FILE} /models/model.gguf

# Контекста 8К хватает на системную подсказку, комментарий диспетчера
# и ответ с запасом; больший контекст на процессоре только тратит память.
# Параллельных запросов два: разбор пишется фоном, очередь не страшна,
# а каждый слот дополнительно резервирует память под контекст.
ENV LLAMA_ARG_MODEL=/models/model.gguf \
    LLAMA_ARG_ALIAS=qwen \
    LLAMA_ARG_HOST=0.0.0.0 \
    LLAMA_ARG_PORT=8080 \
    LLAMA_ARG_CTX_SIZE=8192 \
    LLAMA_ARG_N_PARALLEL=2 \
    LLAMA_ARG_FLASH_ATTN=on

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

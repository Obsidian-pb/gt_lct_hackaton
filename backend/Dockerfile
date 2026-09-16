FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Зависимости отдельным слоем, чтобы правки кода не пересобирали их.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
# Корневые сертификаты НУЦ Минцифры — нужны для TLS до GigaChat.
COPY backend/certs ./certs
COPY backend/pytest.ini ./

# Классификатор разбирается на этапе сборки: в образ попадает готовый ekp.json,
# сам xlsx во время работы не нужен.
COPY classificator.xlsx /tmp/classificator.xlsx
RUN python scripts/parse_ekp.py --src /tmp/classificator.xlsx --dst /app/data/ekp.json \
    && rm /tmp/classificator.xlsx

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

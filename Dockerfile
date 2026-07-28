# Prism Router gateway
FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_ROUTER_HOST=0.0.0.0 \
    MODEL_ROUTER_PORT=4000 \
    MODEL_ROUTER_CONFIG_DIR=/app/config \
    MODEL_ROUTER_TELEMETRY_PATH=/app/logs/telemetry.jsonl

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir .

EXPOSE 4000
CMD ["model-router"]

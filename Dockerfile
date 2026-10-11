# Prism Router gateway
FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_ROUTER_HOST=0.0.0.0 \
    MODEL_ROUTER_PORT=4000 \
    MODEL_ROUTER_CONFIG_DIR=/app/config \
    MODEL_ROUTER_TELEMETRY_PATH=/tmp/model-router/telemetry.jsonl \
    MODEL_ROUTER_MIRROR_PATH=/tmp/model-router/mirror.jsonl \
    MODEL_ROUTER_DRY_RUN=false \
    MODEL_ROUTER_MIRROR_MODE=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/logs /tmp/model-router \
    && chown -R app:app /app /tmp/model-router

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir '.[redis]' \
    && chown -R app:app /app

USER app

EXPOSE 4000

# Local docker run; Railway uses its own healthcheckPath from railway.toml
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('PORT') or os.environ.get('MODEL_ROUTER_PORT','4000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=3)"

# Railway (and similar hosts) inject PORT; fall back to 4000 locally.
CMD ["sh", "-c", "export MODEL_ROUTER_PORT=\"${PORT:-${MODEL_ROUTER_PORT:-4000}}\"; exec model-router"]

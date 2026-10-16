FROM node:24.18.1-bookworm-slim@sha256:235600a8101ab264e117b1768e925532262668dc9b581ef1dd7d96ced463b8e7 AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --global npm@11.16.0 && npm ci
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
COPY public ./public
COPY content ./content
COPY schemas ./schemas
COPY scripts ./scripts
RUN npm run build && node scripts/validate-content.mjs

FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS base
# Snapshot fixes Debian tool versions as well as Python/npm/uv versions.
RUN printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261015T000000Z bookworm main\ndeb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20261015T000000Z bookworm-security main\n' > /etc/apt/sources.list \
    && rm -f /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::https::Timeout=30 -o Acquire::Retries=2 -o Acquire::Check-Valid-Until=false update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS prepared
RUN apt-get -o Acquire::https::Timeout=30 -o Acquire::Retries=2 -o Acquire::Check-Valid-Until=false update \
    && apt-get -o Acquire::https::Timeout=30 -o Acquire::http::Timeout=30 -o Acquire::Retries=2 install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_NO_BUILD=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-editable
COPY server ./server
COPY scripts ./scripts
COPY content ./content
COPY schemas ./schemas
COPY resources ./resources
RUN uv run --no-sync python -m scripts.prepare_docker_resources \
    && uv run --no-sync python -m scripts.fetch_asr_model \
    && uv run --no-sync python -m scripts.check_bundled_resources \
    && uv run --no-sync python -m scripts.validate_audio_resources \
    && uv run --no-sync python -m scripts.validate_daily_reading --release

FROM base AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" LOVE_PINYIN_DATA_DIR=/data \
    LOVE_PINYIN_SOURCE_AUDIO_DIR=/app/private/pinyinsound \
    LOVE_PINYIN_ASR_CPU_ONLY=1
WORKDIR /app
COPY --from=prepared /app/.venv ./.venv
COPY --from=prepared /app/server ./server
COPY --from=prepared /app/scripts ./scripts
COPY --from=prepared /app/content ./content
COPY --from=prepared /app/schemas ./schemas
COPY --from=prepared /app/resources ./resources
COPY --from=prepared /app/private/pinyinsound ./private/pinyinsound
COPY --from=prepared --chmod=644 /app/models/whisper-small/ggml-small.bin ./models/whisper-small/ggml-small.bin
COPY --from=web /app/dist ./dist
COPY LICENSE THIRD_PARTY_NOTICES.md ./
RUN groupadd --gid 10001 pinyin && useradd --uid 10001 --gid pinyin --no-create-home pinyin \
    && mkdir /data && chown pinyin:pinyin /data \
    && chmod 755 models models/whisper-small
USER pinyin
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).read()"]
CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]

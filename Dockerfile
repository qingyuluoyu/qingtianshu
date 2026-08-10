FROM node:22-bookworm-slim AS frontend-build

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run generate:api:file && npm run build \
    && test -f dist/index.html


FROM python:3.11-slim-bookworm AS hermes-runtime

ARG HERMES_COMMIT=ab158e8088a847890057b75a63a951155ea93004

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git \
    && python -m venv /opt/hermes \
    && /opt/hermes/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && mkdir -p /opt/hermes-agent \
    && git -C /opt/hermes-agent init \
    && git -C /opt/hermes-agent remote add origin https://github.com/NousResearch/hermes-agent.git \
    && git -C /opt/hermes-agent -c http.version=HTTP/1.1 \
        fetch --depth 1 origin "${HERMES_COMMIT}" \
    && git -C /opt/hermes-agent checkout --detach FETCH_HEAD \
    && /opt/hermes/bin/pip install --no-cache-dir --editable /opt/hermes-agent \
    && rm -rf /opt/hermes-agent/.git /var/lib/apt/lists/* \
    && /opt/hermes/bin/hermes --version


FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QINGSHU_DATA_DIR=/data \
    BACKGROUND_JOBS_ENABLED=true \
    BACKGROUND_WORKER_MODE=external \
    HERMES_HOME=/data/hermes \
    HERMES_BIN=/opt/hermes/bin/hermes \
    HERMES_PYTHON_BIN=/opt/hermes/bin/python \
    QINGSHU_FRONTEND_DIST_DIR=/app/frontend/dist \
    HERMES_ENABLED=false

WORKDIR /app

COPY --from=hermes-runtime /opt/hermes /opt/hermes
COPY --from=hermes-runtime /opt/hermes-agent /opt/hermes-agent

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl --fail --silent --show-error \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends postgresql-client-17 \
    && apt-get purge --yes --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
COPY app ./app
COPY --from=frontend-build /frontend/dist /app/frontend/dist
RUN pip install --no-cache-dir "uv==0.7.12" \
    && uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:${PATH}"

COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

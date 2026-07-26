FROM python:3.11.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    QINGSHU_DATA_DIR=/data \
    HERMES_ENABLED=false

WORKDIR /app

RUN groupadd --system qingshu \
    && useradd --system --gid qingshu --home-dir /app qingshu \
    && mkdir -p /data \
    && chown -R qingshu:qingshu /app /data

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY scripts ./scripts
RUN chown -R qingshu:qingshu /app

USER qingshu

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

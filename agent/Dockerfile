FROM python:3.12-slim

# Container runs as root inside an isolated Docker network (Checkov CKV_DOCKER_3
# skipped in .checkov.yaml). Wiki volume permissions require root on first boot.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Put the uv-managed virtualenv on PATH so entrypoints (celery, uvicorn,
# alembic) resolve directly — the worker/beat compose commands call them
# without the `uv run` prefix.
ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "tracebow.main:app", "--host", "0.0.0.0", "--port", "8080"]

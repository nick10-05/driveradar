# syntax=docker/dockerfile:1
# DriveRadar backend image (DESIGN §7, §10.1).
# Build from backend/:  docker build -t driveradar-backend .
#
# Interview notes:
# - Multi-stage: the builder has uv and caches; the final image has only Python, the
#   venv and the app code. Smaller image, smaller attack surface.
# - Base images are pinned by tag (readable) and digest (exact bytes, can't change under us).
# - Runs as an unprivileged user. Migrations run on start, then uvicorn replaces the shell
#   (exec) so it is PID 1 and gets SIGTERM directly → graceful shutdown via the lifespan.

ARG PYTHON_IMAGE=python:3.13.18-slim-trixie@sha256:48d884813cf44e927cf64c5529dd630dd3b18338c6dc727991eef9b71e934a20

# ---------------------------------------------------------------- builder
FROM ${PYTHON_IMAGE} AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first: this layer is reused until pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app

# Numeric IDs, so platforms can verify "non-root" without resolving names.
USER 10001:10001

EXPOSE 8000

# Docker-level check for local runs (Render uses its own health check on /healthz).
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=2)"]

# --proxy-headers: trust X-Forwarded-* from the platform's proxy (the container is only
# reachable through it), so request.client is the real client IP.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --no-access-log --proxy-headers --forwarded-allow-ips '*'"]

# syntax=docker/dockerfile:1.7
# RISE API (FastAPI) image.  Build context MUST be the repo root:
#   docker build -f apps/api/Dockerfile -t rise-api .
# apps/api imports apps.agents (orchestrator graph) in-process, so both app
# trees plus the shared rise-core packages, prompts, and OPA policies ship here.

# --- Builder: resolve + install main deps into an in-project venv ---
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.4.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
WORKDIR /app
# rise-core is an editable path dependency (develop=true): its source must be
# present before `poetry install`, so copy it alongside the lockfile.
COPY pyproject.toml poetry.lock ./
COPY packages/rise-core/ packages/rise-core/
RUN poetry install --only main --no-root

# --- Runtime ---
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app:/app/packages/rise-core"
WORKDIR /app
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin rise
COPY --from=builder /app/.venv /app/.venv
COPY packages/ packages/
COPY apps/api/ apps/api/
COPY apps/agents/ apps/agents/
COPY prompts/ prompts/
COPY policies/ policies/
COPY alembic.ini ./
USER rise
EXPOSE 8000
# Liveness only depends on the process (readiness -> /readyz checks pg/redis/qdrant).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3).status==200 else 1)"
CMD ["uvicorn", "apps.api.src.main:app", "--host", "0.0.0.0", "--port", "8000"]

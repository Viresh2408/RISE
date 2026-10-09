# syntax=docker/dockerfile:1.7
# RISE agents (LangGraph orchestrator) image.  Build context MUST be repo root:
#   docker build -f apps/agents/Dockerfile -t rise-agents .
# The orchestrator graph is executed in-process by the API/worker; this image
# runs the thin liveness bootstrap (apps/agents/src/__main__.py) that compiles
# the graph on start (fail-loud) and health-checks it. See that module's
# docstring for scope.

# --- Builder: resolve + install main deps into an in-project venv ---
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.4.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
WORKDIR /app
COPY pyproject.toml poetry.lock ./
COPY packages/rise-core/ packages/rise-core/
RUN poetry install --only main --no-root

# --- Runtime ---
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app:/app/packages/rise-core" \
    AGENTS_HEALTH_PORT=8000
WORKDIR /app
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin rise
COPY --from=builder /app/.venv /app/.venv
COPY packages/ packages/
COPY apps/agents/ apps/agents/
COPY prompts/ prompts/
COPY policies/ policies/
USER rise
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3).status==200 else 1)"
CMD ["python", "-m", "apps.agents.src"]

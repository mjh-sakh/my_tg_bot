FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

FROM python:3.13-slim AS runtime
LABEL authors="mjh-ao"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY bot /app/bot
CMD ["python", "-m", "bot.main"]

FROM python:3.13-slim
LABEL authors="mjh-ao"

COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /uvx /bin/

RUN apt-get update && \
    apt-get install -y --no-install-recommends libmagic1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="${PYTHONPATH}:/app"
CMD ["python", "bot/main.py"]
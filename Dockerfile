FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for psycopg/pgvector + lxml (used transitively by selectolax fallback)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations

RUN pip install --upgrade pip && pip install .

# Cloud Run injects PORT.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn sales_agent.server:app --host 0.0.0.0 --port ${PORT}"]

# syntax=docker/dockerfile:1

# --- build stage: install dependencies into an isolated prefix ---
FROM python:3.11.9-slim-bookworm AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- runtime stage: minimal image, no build toolchain, non-root user ---
FROM python:3.11.9-slim-bookworm AS runtime
WORKDIR /app

COPY --from=build /install /usr/local
COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

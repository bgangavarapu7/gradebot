FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN useradd --create-home --uid 10001 appuser

# Dependencies first: this layer is rebuilt only when requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Test image: adds the dev tools and the whole repo. Used by `make test` / `make eval`.
FROM base AS dev
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY --chown=appuser:appuser . .
USER appuser
CMD ["pytest", "-q"]


# Runtime image (the default target): only what the API needs.
FROM base AS runtime
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser prompts ./prompts
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

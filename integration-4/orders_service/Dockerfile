FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Manifests first: the expensive dependency layer stays cached when only code changes.
# uv.lock is used when present (run `uv lock` once and commit it for reproducible builds).
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev

COPY app ./app

ENV PATH="/app/.venv/bin:$PATH"

# No secret is copied into, or baked into, this image (R1.8).
# Secrets are mounted at runtime under /run/secrets/ by Docker Compose.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ────────────────────────────────────────────────────────────────────────────
# Stage 1 – dependency installer
#   Uses uv for fast, reproducible installs from the lock file.
# ────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Pull the uv binary from its official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Copy only the files that affect dependency resolution first so that this
# layer is rebuilt only when dependencies actually change.
COPY pyproject.toml uv.lock .python-version ./

# Install production dependencies into a virtual environment inside the image.
# --frozen  → fail if lock file is out of sync with pyproject.toml
# --no-dev  → omit pytest, httpx, etc.
RUN uv sync --frozen --no-dev


# ────────────────────────────────────────────────────────────────────────────
# Stage 2 – runtime image
# ────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATABASE_URL=sqlite:///./data/auto.db \
    # Store Playwright browsers in a predictable, non-root location
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    # Suppress interactive apt prompts during playwright --with-deps
    DEBIAN_FRONTEND=noninteractive

# Copy uv and the installed virtual environment from the builder stage
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/pyproject.toml /app/uv.lock /app/.python-version ./

# Install Playwright Chromium browser + its OS-level system libraries
# (libnss3, libatk, libgbm, etc.). --with-deps handles apt-get internally.
RUN uv run playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Copy application source (changes most often → last layer)
COPY src/ ./src/
COPY ui/  ./ui/

# Persistent SQLite database directory; mount a named volume here in prod
RUN mkdir -p data

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

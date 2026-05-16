# API container for KOSPI Reporter.
#
# The directory layout under /app mirrors the repository so app/config.py
# resolves ROOT_DIR correctly. The same image runs the API (default CMD) or
# the scheduler worker (override CMD: python workers/scheduler.py).
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY apps/api/requirements.txt ./apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

# Application code: the API package, the shared kospi_core package, the worker.
COPY apps/api/app ./apps/api/app
COPY packages/core/kospi_core ./packages/core/kospi_core
COPY workers ./workers

ENV PYTHONPATH=/app/apps/api:/app/packages/core

# The SQLite database lives at /app/data/kospi.db. Mount a persistent volume
# at /app/data so it survives redeploys (see docs/deployment.md).
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

# Single-stage build: fastapi, uvicorn, and pydantic all ship prebuilt
# wheels for this image's platform, so no compiler toolchain is needed
# and a separate builder stage would add complexity without benefit.
FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/

# The "observability" extra (OpenTelemetry zero-code auto-instrumentation,
# Phase 2A.3) is installed into the image so it's available, but CMD below
# still launches plain Uvicorn — this image runs with no telemetry when
# used standalone. Docker Compose is what opts into instrumentation, by
# overriding the command to run through `opentelemetry-instrument`.
RUN pip install --no-cache-dir ".[observability]"

RUN groupadd --system app && useradd --system --gid app --no-create-home app
USER app

EXPOSE 8081

CMD ["uvicorn", "payment_service.main:app", "--host", "0.0.0.0", "--port", "8081"]

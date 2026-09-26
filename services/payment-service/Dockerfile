# Single-stage build: fastapi, uvicorn, and pydantic all ship prebuilt
# wheels for this image's platform, so no compiler toolchain is needed
# and a separate builder stage would add complexity without benefit.
FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir .

RUN groupadd --system app && useradd --system --gid app --no-create-home app
USER app

EXPOSE 8081

CMD ["uvicorn", "payment_service.main:app", "--host", "0.0.0.0", "--port", "8081"]

# Single-stage build: fastapi, uvicorn, pydantic, httpx, langgraph, and
# psycopg[binary] all ship prebuilt wheels for this image's platform,
# so no compiler toolchain is needed (matches investigator-service's/
# retrieval-service's own Dockerfile convention).
FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir .

RUN groupadd --system app && useradd --system --gid app --no-create-home app
USER app

EXPOSE 8003

CMD ["uvicorn", "agent_runtime_service.main:app", "--host", "0.0.0.0", "--port", "8003"]

# Phase 17A item 6: the retention scheduler sidecar's image. Built
# from the repository root (see deploy/docker-compose.override.yml's
# `build.context: ../`) so it can reuse scripts/prune-telemetry-
# samples.py directly -- no copy/duplication of that script.
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir asyncpg==0.31.0

COPY scripts/prune-telemetry-samples.py ./prune-telemetry-samples.py
COPY deploy/scripts/retention-loop.sh ./retention-loop.sh

RUN groupadd --system app && useradd --system --gid app --no-create-home app && \
    chmod +x ./retention-loop.sh
USER app

CMD ["./retention-loop.sh"]

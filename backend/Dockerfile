FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2 AS dependencies
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TOKENIZERS_PARALLELISM=false HF_HUB_DISABLE_TELEMETRY=1 LANGSMITH_TRACING=false \
    LANGCHAIN_TRACING_V2=false QUARRY_DATA_DIR=/data QUARRY_MODEL_CACHE=/models
WORKDIR /app
RUN groupadd --gid 10001 quarry && useradd --uid 10001 --gid quarry --create-home quarry && mkdir /data && chown quarry:quarry /data
COPY backend/requirements.lock /tmp/requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes -r /tmp/requirements.lock
FROM dependencies AS test-dependencies
COPY backend/requirements-dev.lock /tmp/requirements-dev.lock
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes -r /tmp/requirements-dev.lock

FROM dependencies AS evaluation-dependencies
COPY backend/requirements-eval.lock /tmp/requirements-eval.lock
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes -r /tmp/requirements-eval.lock
COPY infra/harden_eval.py /usr/local/share/quarry/harden_eval.py
RUN python /usr/local/share/quarry/harden_eval.py

FROM dependencies AS runtime-libraries
COPY infra/python-runtime.py /tmp/python-runtime.py
RUN python /tmp/python-runtime.py

FROM gcr.io/distroless/base-debian13:nonroot@sha256:6c591b4ac789b683ab3665327181e7cfb7a39b5834f42dcb73d7becb8d18a5d9 AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false \
    HF_HUB_DISABLE_TELEMETRY=1 HF_HOME=/tmp/quarry-huggingface LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false \
    QUARRY_DATA_DIR=/data QUARRY_MODEL_CACHE=/models LD_LIBRARY_PATH=/usr/local/lib:/opt/quarry-libs \
    PATH=/usr/local/bin
WORKDIR /app
COPY --from=runtime-libraries /usr/local /usr/local
COPY --from=runtime-libraries /runtime-libs/ /opt/quarry-libs/
COPY --from=runtime-libraries /runtime-status/ /var/lib/dpkg/status.d/
COPY --from=runtime-libraries /usr/share/doc/ /usr/share/doc/
COPY --from=runtime-libraries --chown=10001:10001 /data /data
COPY --chown=10001:10001 backend /app
COPY --chown=10001:10001 evaluation /app/evaluation
USER 10001:10001
EXPOSE 8000
ENTRYPOINT []
CMD ["/usr/local/bin/python", "-m", "uvicorn", "quarry.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--limit-concurrency", "100"]

FROM test-dependencies AS test
ENV COVERAGE_FILE=/tmp/quarry.coverage RUFF_CACHE_DIR=/tmp/quarry-ruff
COPY --chown=quarry:quarry backend /app
COPY --chown=quarry:quarry evaluation /app/evaluation
COPY --chown=quarry:quarry scripts /opt/quarry-operator
USER 10001:10001
CMD ["pytest", "--cov=quarry", "--cov-branch", "--cov-report=term-missing"]

FROM evaluation-dependencies AS evaluation
COPY --chown=quarry:quarry backend /app
COPY --chown=quarry:quarry evaluation /app/evaluation
USER 10001:10001
ENV RAGAS_DO_NOT_TRACK=true
CMD ["python", "-m", "quarry.benchmark"]

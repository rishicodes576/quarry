# API-only runtime: retain the upstream binary and required dynamic libraries.
# Retain package inventory/licenses so vulnerability scanning remains possible.
FROM qdrant/qdrant:v1.20.0@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2 AS upstream
COPY infra/qdrant-runtime.sh /tmp/quarry-runtime.sh
RUN sh /tmp/quarry-runtime.sh
FROM scratch
COPY --from=upstream /runtime /
COPY --from=upstream /qdrant/qdrant /qdrant/qdrant
COPY --from=upstream /qdrant/config /qdrant/config
COPY docs/licenses/qdrant.LICENSE /usr/share/licenses/qdrant/LICENSE
WORKDIR /qdrant
USER 10001:10001
ENV RUN_MODE=production QDRANT__SERVICE__ENABLE_STATIC_CONTENT=false
ENTRYPOINT ["/qdrant/qdrant"]

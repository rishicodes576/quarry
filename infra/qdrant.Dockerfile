# API-only runtime: retain the upstream binary and required dynamic libraries.
# Retain package inventory/licenses so vulnerability scanning remains possible.
FROM qdrant/qdrant:v1.20.0@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2 AS upstream
RUN set -eu; mkdir -p /runtime/var/lib/dpkg /runtime/usr/share/doc /runtime/etc/ssl/certs /runtime/tmp /runtime/qdrant/storage /runtime/qdrant/snapshots; \
    chmod 1777 /runtime/tmp; chown -R 10001:10001 /runtime/qdrant; \
    cp --parents /lib/x86_64-linux-gnu/libunwind-ptrace.so.0 /lib/x86_64-linux-gnu/libunwind-x86_64.so.8 /lib/x86_64-linux-gnu/libunwind.so.8 /lib/x86_64-linux-gnu/libgcc_s.so.1 /lib/x86_64-linux-gnu/libm.so.6 /lib/x86_64-linux-gnu/libc.so.6 /lib/x86_64-linux-gnu/liblzma.so.5 /lib64/ld-linux-x86-64.so.2 /runtime/; \
    cp /etc/os-release /runtime/etc/; cp /etc/ssl/certs/ca-certificates.crt /runtime/etc/ssl/certs/; \
    dpkg-query -s libc6 libunwind8 libgcc-s1 liblzma5 ca-certificates > /runtime/var/lib/dpkg/status; \
    cp -r /usr/share/doc/libc6 /usr/share/doc/libunwind8 /usr/share/doc/libgcc-s1 /usr/share/doc/liblzma5 /usr/share/doc/ca-certificates /runtime/usr/share/doc/
FROM scratch
COPY --from=upstream /runtime /
COPY --from=upstream /qdrant/qdrant /qdrant/qdrant
COPY --from=upstream /qdrant/config /qdrant/config
COPY docs/licenses/qdrant.LICENSE /usr/share/licenses/qdrant/LICENSE
WORKDIR /qdrant
USER 10001:10001
ENV RUN_MODE=production QDRANT__SERVICE__ENABLE_STATIC_CONTENT=false
ENTRYPOINT ["/qdrant/qdrant"]

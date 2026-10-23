# Unmodified upstream 4.48 source, with an explicitly patched Go dependency/toolchain.
FROM golang:1.26-alpine@sha256:5cb67f19c5e7994dcb80c074f7cfca8aeeada45bbdca035f73df269cefdcce61 AS build
ENV CGO_ENABLED=0 GOMAXPROCS=2 GOTOOLCHAIN=local
ADD --checksum=sha256:93199495e93a981451d1fefecb5aa71e12aa1692093eed2338bbfe7f08960bfb https://codeload.github.com/seaweedfs/seaweedfs/tar.gz/refs/tags/4.48 /tmp/seaweed.tar.gz
WORKDIR /src
RUN tar -xzf /tmp/seaweed.tar.gz --strip-components=1 -C /src
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go get golang.org/x/net@v0.60.0 && go build -p 2 -trimpath -ldflags="-s -w" -o /out/weed ./weed
FROM alpine:3.22@sha256:d406446bc05b82480756ce8f1287964d28768c23955fa9480d2a74a2eae7a654
RUN apk add --no-cache ca-certificates && addgroup -g 10001 -S quarry && adduser -S quarry -u 10001 -G quarry
COPY --from=build /out/weed /usr/bin/weed
COPY --from=build /src/docker/filer.toml /etc/seaweedfs/filer.toml
COPY --from=build /src/LICENSE /usr/share/licenses/seaweedfs/LICENSE
COPY --from=build /src/go.mod /src/go.sum /usr/share/quarry/seaweedfs/
USER 10001:10001
WORKDIR /data
ENTRYPOINT ["/usr/bin/weed"]
CMD ["mini", "-dir=/data", "-ip=127.0.0.1", "-ip.bind=127.0.0.1", "-webdav=false", "-admin.ui=false", "-s3.iam=false", "-s3.port.iceberg=0", "-s3.port.lance=0", "-master.telemetry=false", "-volume.max=48", "-s3.concurrentUploadLimitMB=32", "-s3.concurrentFileUploadLimit=8", "-s3.readerCacheSizeMB=32"]

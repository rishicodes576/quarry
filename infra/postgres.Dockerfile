FROM golang:1.26-alpine@sha256:5cb67f19c5e7994dcb80c074f7cfca8aeeada45bbdca035f73df269cefdcce61 AS build
ENV CGO_ENABLED=0 GOMAXPROCS=2 GOTOOLCHAIN=local
ADD --checksum=sha256:cd9719b775dbfedae53923c9b0dc792b66d42c51e0b36652ed6f747fbadc0164 https://codeload.github.com/tianon/gosu/tar.gz/refs/tags/1.19 /tmp/source.tar.gz
WORKDIR /src
RUN tar -xzf /tmp/source.tar.gz --strip-components=1
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go build -p 2 -trimpath -ldflags="-w" -o /out/gosu .
FROM postgres:18-alpine@sha256:83148c0bc09eac4d598b70a61e1404d0212b76c95c504bfd6c81a4c59ec91792
RUN apk add --no-cache 'brotli-libs=1.2.1-r0' 'libcurl=8.23.0-r0'
COPY --from=build /out/gosu /usr/local/bin/gosu
COPY --from=build /src/LICENSE /usr/share/licenses/gosu/LICENSE
COPY --from=build /src/go.mod /src/go.sum /usr/share/quarry/gosu/

USER postgres

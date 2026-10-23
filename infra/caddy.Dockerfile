FROM golang:1.26-alpine@sha256:5cb67f19c5e7994dcb80c074f7cfca8aeeada45bbdca035f73df269cefdcce61 AS build
ENV CGO_ENABLED=0 GOMAXPROCS=2 GOTOOLCHAIN=local
ADD --checksum=sha256:86e39de5fa0bc433a9cd574a00e7751059903401f3389c61f8937fd0ad0180f5 https://codeload.github.com/caddyserver/caddy/tar.gz/refs/tags/v2.11.7 /tmp/source.tar.gz
WORKDIR /src
RUN tar -xzf /tmp/source.tar.gz --strip-components=1
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go get golang.org/x/net@v0.60.0 && go build -p 2 -trimpath -ldflags="-s -w" -o /out/caddy ./cmd/caddy
FROM alpine:3.22@sha256:d406446bc05b82480756ce8f1287964d28768c23955fa9480d2a74a2eae7a654
RUN apk add --no-cache ca-certificates && mkdir -p /etc/caddy /config /data \
    && chown -R 10001:10001 /config /data
COPY --from=build /out/caddy /usr/bin/caddy
COPY --from=build /src/LICENSE /usr/share/licenses/caddy/LICENSE
COPY --from=build /src/go.mod /src/go.sum /usr/share/quarry/caddy/
USER 10001:10001
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]

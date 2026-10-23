FROM golang:1.26-alpine@sha256:5cb67f19c5e7994dcb80c074f7cfca8aeeada45bbdca035f73df269cefdcce61 AS build
ENV CGO_ENABLED=0 GOMAXPROCS=2 GOTOOLCHAIN=local
ADD --checksum=sha256:86e39de5fa0bc433a9cd574a00e7751059903401f3389c61f8937fd0ad0180f5 https://codeload.github.com/caddyserver/caddy/tar.gz/refs/tags/v2.11.7 /tmp/source.tar.gz
WORKDIR /src
RUN tar -xzf /tmp/source.tar.gz --strip-components=1
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go get golang.org/x/net@v0.60.0 && go build -p 2 -trimpath -ldflags="-s -w" -o /out/caddy ./cmd/caddy
FROM caddy@sha256:24ec7b05bc532c7bb57f727030c5056e257ff7138b4b50460306819ff79362bd
COPY --from=build /out/caddy /usr/bin/caddy
COPY --from=build /src/LICENSE /usr/share/licenses/caddy/LICENSE
COPY --from=build /src/go.mod /src/go.sum /usr/share/quarry/caddy/
USER 10001:10001

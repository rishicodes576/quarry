FROM node:25-alpine@sha256:bdf2cca6fe3dabd014ea60163eca3f0f7015fbd5c7ee1b0e9ccb4ced6eb02ef4 AS assets
ADD --checksum=sha256:85889973cedc04644e71cabdcdaf5d77cf428c785928936cc5ab554c0d6f0a66 https://codeload.github.com/axllent/mailpit/tar.gz/refs/tags/v1.31.6 /tmp/source.tar.gz
WORKDIR /src
RUN tar -xzf /tmp/source.tar.gz --strip-components=1 && npm ci --no-audit --no-fund && npm run package && rm -rf node_modules
FROM golang:1.26-alpine@sha256:5cb67f19c5e7994dcb80c074f7cfca8aeeada45bbdca035f73df269cefdcce61 AS build
ENV CGO_ENABLED=0 GOMAXPROCS=2 GOTOOLCHAIN=local
WORKDIR /src
COPY --from=assets /src ./
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go build -p 2 -trimpath -ldflags="-s -w -X github.com/axllent/mailpit/config.Version=v1.31.6-quarry" -o /out/mailpit .
FROM axllent/mailpit@sha256:23fe39e81bde596a918000b3135c0f85dc8bb4c9ea6be274b051143f3e300387
COPY --from=build /out/mailpit /mailpit
COPY --from=build /src/LICENSE /usr/share/licenses/mailpit/LICENSE
COPY --from=build /src/go.mod /src/go.sum /usr/share/quarry/mailpit/
USER 10001:10001

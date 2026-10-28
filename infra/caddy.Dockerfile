FROM golang:1.26-alpine@sha256:5cb67f19c5e7994dcb80c074f7cfca8aeeada45bbdca035f73df269cefdcce61 AS build
ENV CGO_ENABLED=0 GOMAXPROCS=2 GOTOOLCHAIN=local
ADD --checksum=sha256:86e39de5fa0bc433a9cd574a00e7751059903401f3389c61f8937fd0ad0180f5 https://codeload.github.com/caddyserver/caddy/tar.gz/refs/tags/v2.11.7 /tmp/source.tar.gz
WORKDIR /src
RUN tar -xzf /tmp/source.tar.gz --strip-components=1
COPY infra/harden_jose.go security/jose-v3-backport.json /tmp/quarry-jose/
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go get golang.org/x/net@v0.60.0 github.com/go-jose/go-jose/v4@v4.1.6 \
    && go mod download github.com/go-jose/go-jose/v3@v3.0.5 \
    && cp -R /go/pkg/mod/github.com/go-jose/go-jose/v3@v3.0.5 /src/quarry-jose-v3 \
    && chmod -R u+w /src/quarry-jose-v3 \
    && go run /tmp/quarry-jose/harden_jose.go /tmp/quarry-jose/jose-v3-backport.json /src/quarry-jose-v3 \
    && go mod edit -replace github.com/go-jose/go-jose/v3=./quarry-jose-v3 \
    && mkdir -p /out \
    && (go test -mod=readonly -p 2 -count=1 -timeout 10m github.com/go-jose/go-jose/v3/... > /out/jose-upstream-tests.log 2>&1 || { cat /out/jose-upstream-tests.log; exit 1; })
COPY infra/jose_regression_test.go /src/quarry-jose-v3/quarry_regression_test.go
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go test -mod=readonly -p 2 -count=1 -run '^TestQuarry' -timeout 30s github.com/go-jose/go-jose/v3 \
    && go test -mod=readonly -c -trimpath -o /out/quarry-jose-regression github.com/go-jose/go-jose/v3 \
    && go list -mod=readonly -m -json all > /out/jose-selected-modules.json \
    && go list -mod=readonly -deps -test -json github.com/go-jose/go-jose/v3 > /out/jose-test-deps.json \
    && go build -p 2 -trimpath -ldflags="-s -w" -o /out/caddy ./cmd/caddy
FROM alpine:3.22@sha256:d406446bc05b82480756ce8f1287964d28768c23955fa9480d2a74a2eae7a654
RUN apk add --no-cache ca-certificates && mkdir -p /etc/caddy /config /data \
    && chown -R 10001:10001 /config /data
COPY --from=build /out/caddy /usr/bin/caddy
COPY --from=build /out/quarry-jose-regression /usr/bin/quarry-jose-regression
COPY --from=build /out/jose-upstream-tests.log /usr/share/quarry/caddy/jose-upstream-tests.log
COPY --from=build /out/jose-selected-modules.json /out/jose-test-deps.json /usr/share/quarry/caddy/
COPY --from=build /src/quarry-jose-v3/jwk.go /src/quarry-jose-v3/shared.go /src/quarry-jose-v3/jws.go /src/quarry-jose-v3/jwe.go /src/quarry-jose-v3/LICENSE /usr/share/quarry/caddy/jose-v3/
COPY security/jose-v3-backport.json security/JOSE_BACKPORT.md /usr/share/quarry/caddy/
COPY infra/jose_regression_test.go /usr/share/quarry/caddy/jose_regression_test.go
COPY --from=build /src/LICENSE /usr/share/licenses/caddy/LICENSE
COPY --from=build /src/go.mod /src/go.sum /usr/share/quarry/caddy/
USER 10001:10001
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]

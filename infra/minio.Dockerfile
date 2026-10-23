# Community MinIO is source-only. Build the final security release without a paid image.
FROM golang:1.26-alpine@sha256:5cb67f19c5e7994dcb80c074f7cfca8aeeada45bbdca035f73df269cefdcce61 AS build
ENV CGO_ENABLED=0 GOMAXPROCS=2
RUN go install -trimpath -ldflags="-s -w -X github.com/minio/minio/cmd.Version=RELEASE.2025-10-15T17-29-55Z -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z" github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z
FROM alpine:3.22@sha256:d406446bc05b82480756ce8f1287964d28768c23955fa9480d2a74a2eae7a654
RUN apk add --no-cache ca-certificates && addgroup -g 10001 -S quarry && adduser -S quarry -u 10001 -G quarry
COPY --from=build /go/bin/minio /usr/local/bin/minio
USER 10001:10001
EXPOSE 9000
ENTRYPOINT ["minio"]

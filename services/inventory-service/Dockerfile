# Builder stage: compiles and tests the service on the target Go
# version. Go isn't installed on developer hosts for this repo, so this
# build is also the authoritative local test path (see Makefile).
FROM golang:1.27 AS builder
WORKDIR /build

COPY go.mod go.sum ./
RUN go mod download
COPY cmd/ cmd/
COPY internal/ internal/

RUN gofmt -l . | tee /tmp/gofmt-diff && test ! -s /tmp/gofmt-diff
RUN go vet ./...
RUN go test ./...
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/inventory-service ./cmd/inventory-service

# Runtime stage: distroless nonroot — no shell, no package manager, no
# Go toolchain, minimal attack surface. Distroless has no curl/wget, so
# the Docker/Compose healthcheck instead runs this same binary in its
# built-in "healthcheck" mode (a plain HTTP GET against its own
# /health), via the exec form (no shell required).
FROM gcr.io/distroless/static-debian12:nonroot
USER nonroot:nonroot

COPY --from=builder /out/inventory-service /inventory-service

EXPOSE 8082

ENTRYPOINT ["/inventory-service"]

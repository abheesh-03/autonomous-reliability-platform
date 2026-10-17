# Builder stage: compiles and tests the service on the target Go
# version. Same convention services/inventory-service/Dockerfile
# already establishes -- this build is also the authoritative local
# test path (see Makefile's tool-gateway-test target).
FROM golang:1.27 AS builder
WORKDIR /build

COPY go.mod ./
RUN go mod download
COPY cmd/ cmd/
COPY internal/ internal/

RUN gofmt -l . | tee /tmp/gofmt-diff && test ! -s /tmp/gofmt-diff
RUN go vet ./...
RUN go test ./...
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/tool-gateway ./cmd/tool-gateway

# Runtime stage: distroless nonroot -- no shell, no package manager,
# no Go toolchain, no Docker socket, no privileged capability of any
# kind (Phase 8 §WHY WE ARE NOT USING THE DOCKER SOCKET). The
# Docker/Compose healthcheck runs this same binary in its built-in
# "healthcheck" mode, via the exec form (no shell required) --
# distroless has no curl/wget.
FROM gcr.io/distroless/static-debian12:nonroot
USER nonroot:nonroot

COPY --from=builder /out/tool-gateway /tool-gateway

EXPOSE 8004

ENTRYPOINT ["/tool-gateway"]

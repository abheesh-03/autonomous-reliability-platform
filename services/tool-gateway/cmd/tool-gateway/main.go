package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/config"
	"github.com/abheesh-03/autonomous-reliability-platform/services/tool-gateway/internal/server"
)

const (
	healthURL       = "http://localhost:8004/health"
	shutdownTimeout = 10 * time.Second
)

func main() {
	// The runtime image is distroless (no shell, no curl/wget), so the
	// Docker/Compose healthcheck calls this same binary in
	// "healthcheck" mode instead -- same convention
	// inventory-service's own cmd/inventory-service/main.go already
	// establishes.
	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		os.Exit(runHealthcheck())
	}

	if err := run(); err != nil {
		log.Fatal(err)
	}
}

func run() error {
	settings := config.FromEnv()

	// Phase 8 correction round (finding #3): a runtime, fail-closed
	// boundary over scripts/init-remediation-secrets.sh's own
	// distinctness guarantee -- an operator can hand-edit .env or wire
	// up a different deployment system that never ran that script at
	// all. Refuses to start rather than silently widen privilege; see
	// config.Settings.ValidateNoTokenCollisions's own docstring.
	if err := settings.ValidateNoTokenCollisions(); err != nil {
		return err
	}

	srv := server.New(settings)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	serveErr := make(chan error, 1)
	go func() {
		log.Printf("tool-gateway listening on %s", settings.ListenAddr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			serveErr <- err
			return
		}
		serveErr <- nil
	}()

	select {
	case <-ctx.Done():
		log.Println("shutdown signal received, shutting down gracefully")
	case err := <-serveErr:
		return err
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		return err
	}

	log.Println("HTTP server shutdown complete")
	return nil
}

func runHealthcheck() int {
	client := http.Client{Timeout: 3 * time.Second}

	resp, err := client.Get(healthURL)
	if err != nil {
		log.Println("healthcheck request failed:", err)
		return 1
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Println("healthcheck received non-200 status:", resp.StatusCode)
		return 1
	}

	return 0
}

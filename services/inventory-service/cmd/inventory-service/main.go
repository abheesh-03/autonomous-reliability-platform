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

	"github.com/abheesh-03/autonomous-reliability-platform/services/inventory-service/internal/server"
	"github.com/abheesh-03/autonomous-reliability-platform/services/inventory-service/internal/telemetry"
)

const (
	listenAddr      = "0.0.0.0:8082"
	healthURL       = "http://localhost:8082/health"
	shutdownTimeout = 10 * time.Second
)

func main() {
	// The runtime image is distroless (no shell, no curl/wget), so the
	// Docker/Compose healthcheck calls this same binary in "healthcheck"
	// mode instead of installing an HTTP utility just for that purpose.
	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		os.Exit(runHealthcheck())
	}

	if err := run(); err != nil {
		log.Fatal(err)
	}
}

func run() (runErr error) {
	// Telemetry is only ever initialized here, in the normal server
	// path — never for the "healthcheck" subcommand above, which
	// os.Exit()s before run() is even called. A setup failure fails
	// startup clearly rather than running with partial telemetry.
	shutdownTelemetry, err := telemetry.Setup(context.Background())
	if err != nil {
		return err
	}

	// Deferred (rather than called once near the end of the happy
	// path) so telemetry is still flushed/closed on every exit from
	// run() after Setup succeeds — including an unexpected
	// ListenAndServe error or a failed srv.Shutdown — not just the
	// clean shutdown path. Uses its own fresh context/timeout, not the
	// HTTP server's shutdownCtx: if HTTP shutdown consumes most or all
	// of its timeout, telemetry must still get an independent flush
	// window.
	defer func() {
		telemetryShutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
		defer cancel()

		if err := shutdownTelemetry(telemetryShutdownCtx); err != nil {
			runErr = errors.Join(runErr, err)
			return
		}
		log.Println("shutdown complete")
	}()

	srv := server.New(listenAddr)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	serveErr := make(chan error, 1)
	go func() {
		log.Printf("inventory-service listening on %s", listenAddr)
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

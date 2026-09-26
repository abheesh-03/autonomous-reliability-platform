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

func run() error {
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

	log.Println("shutdown complete")
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

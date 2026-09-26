package server

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHealthRouteAcceptsGet(t *testing.T) {
	srv := New(":0")

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()

	srv.Handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status %d for GET /health, got %d", http.StatusOK, rec.Code)
	}
}

func TestHealthRouteRejectsNonGet(t *testing.T) {
	srv := New(":0")

	req := httptest.NewRequest(http.MethodPost, "/health", nil)
	rec := httptest.NewRecorder()

	srv.Handler.ServeHTTP(rec, req)

	if rec.Code == http.StatusOK {
		t.Fatalf("expected POST /health to be rejected, got status %d", rec.Code)
	}
}

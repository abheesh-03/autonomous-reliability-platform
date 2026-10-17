package api

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRequireExecutionToken_MissingHeaderRejected(t *testing.T) {
	called := false
	handler := RequireExecutionToken("real-token", func(w http.ResponseWriter, r *http.Request) {
		called = true
	})

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	if called {
		t.Fatal("wrapped handler must never run without a valid token")
	}
}

func TestRequireExecutionToken_WrongTokenRejected(t *testing.T) {
	handler := RequireExecutionToken("real-token", func(w http.ResponseWriter, r *http.Request) {
		t.Fatal("wrapped handler must never run")
	})

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer wrong-token")
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
}

func TestRequireExecutionToken_UnconfiguredServerTokenAlwaysFailsClosed(t *testing.T) {
	handler := RequireExecutionToken("", func(w http.ResponseWriter, r *http.Request) {
		t.Fatal("wrapped handler must never run when no server-side token is configured")
	})

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer anything")
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
}

func TestRequireExecutionToken_CorrectTokenPassesThrough(t *testing.T) {
	called := false
	handler := RequireExecutionToken("real-token", func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer real-token")
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if !called {
		t.Fatal("wrapped handler must run for a valid token")
	}
}

func TestRequireExecutionToken_NoSecretLeaksInResponse(t *testing.T) {
	handler := RequireExecutionToken("super-secret-token", func(w http.ResponseWriter, r *http.Request) {})

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer wrong-token")
	rec := httptest.NewRecorder()
	handler(rec, req)

	body := rec.Body.String()
	if strings.Contains(body, "super-secret-token") {
		t.Fatalf("expected token value never to appear in response body, got: %s", body)
	}
}

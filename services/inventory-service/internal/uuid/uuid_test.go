package uuid

import (
	"regexp"
	"testing"
)

var v4Pattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func TestNewV4ReturnsCanonicalVersion4UUID(t *testing.T) {
	id, err := NewV4()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if !v4Pattern.MatchString(id) {
		t.Fatalf("expected a canonical UUID v4, got %q", id)
	}
}

func TestNewV4ReturnsDifferentIDsEachCall(t *testing.T) {
	first, err := NewV4()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	second, err := NewV4()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if first == second {
		t.Fatalf("expected two distinct UUIDs, got the same value twice: %q", first)
	}
}

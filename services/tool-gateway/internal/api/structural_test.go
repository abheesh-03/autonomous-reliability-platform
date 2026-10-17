package api

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// Phase 8 §TOOL-GATEWAY TESTING: "no os/exec, no Docker API/socket
// access". This walks every .go source file in this module (never
// *_test.go files themselves, which are allowed to use test-only
// helpers like httptest freely) and asserts none of them import
// os/exec, reference the Docker socket path, or import the Docker
// client SDK -- a structural proof, not merely a claim in a comment,
// mirroring the convention
// services/agent-runtime-service/tests/test_read_only_guarantees.py
// already establishes for that service's own credential boundary.
func TestNoShellExecOrDockerAccessAnywhereInModule(t *testing.T) {
	moduleRoot := "../.." // internal/api -> module root

	forbidden := []string{
		`"os/exec"`,
		"/var/run/docker.sock",
		"docker.sock",
		"github.com/docker/docker",
		"github.com/moby/moby",
	}

	err := filepath.WalkDir(moduleRoot, func(path string, d os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if d.IsDir() {
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}

		content, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		for _, needle := range forbidden {
			if strings.Contains(string(content), needle) {
				t.Errorf("forbidden reference %q found in %s", needle, path)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("failed to walk module source tree: %v", err)
	}
}

// Phase 8 §NO CALLER-SUPPLIED EXECUTION TARGET: ExecuteRequest itself
// must never grow a field that could carry a URL, hostname, shell
// command, container id, or Docker service name -- a structural
// check on the type itself, not just on today's behavior.
func TestExecuteRequestHasExactlyOneField(t *testing.T) {
	typ := reflect.TypeOf(ExecuteRequest{})
	if typ.NumField() != 1 {
		t.Fatalf("ExecuteRequest must have exactly one field (proposal_id), found %d", typ.NumField())
	}
	if typ.Field(0).Tag.Get("json") != "proposal_id" {
		t.Fatalf("ExecuteRequest's one field must be proposal_id, found json tag %q", typ.Field(0).Tag.Get("json"))
	}
}

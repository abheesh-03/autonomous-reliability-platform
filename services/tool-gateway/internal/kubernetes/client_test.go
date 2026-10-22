package kubernetes

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"errors"
	"math/big"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func newTestClient(t *testing.T, handler http.HandlerFunc) *Client {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	return newWithTransport(srv.URL, "reliability-sandbox", "", srv.Client())
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (func() bool {
		for i := 0; i+len(substr) <= len(s); i++ {
			if s[i:i+len(substr)] == substr {
				return true
			}
		}
		return false
	})()
}

// ---------------------------------------------------------------------
// GetDeployment
// ---------------------------------------------------------------------

func TestGetDeployment_Success(t *testing.T) {
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			t.Fatalf("expected GET, got %s", r.Method)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"metadata": map[string]any{"name": "crashloop-demo", "uid": "uid-1", "resourceVersion": "100", "generation": 2},
			"spec":     map[string]any{"replicas": 1},
			"status":   map[string]any{"observedGeneration": 2, "replicas": 1, "readyReplicas": 1, "availableReplicas": 1},
		})
	})
	d, err := c.GetDeployment(context.Background(), "crashloop-demo")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if d.Metadata.UID != "uid-1" {
		t.Fatalf("expected uid-1, got %s", d.Metadata.UID)
	}
	if d.Metadata.ResourceVersion != "100" {
		t.Fatalf("expected resourceVersion 100, got %s", d.Metadata.ResourceVersion)
	}
}

func TestGetDeployment_Forbidden(t *testing.T) {
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
	})
	_, err := c.GetDeployment(context.Background(), "crashloop-demo")
	if err != ErrForbidden {
		t.Fatalf("expected ErrForbidden, got %v", err)
	}
}

func TestGetDeployment_NotFound(t *testing.T) {
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})
	_, err := c.GetDeployment(context.Background(), "crashloop-demo")
	if err != ErrNotFound {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

// ---------------------------------------------------------------------
// Write-path allowlist / namespace scoping
// ---------------------------------------------------------------------

func TestClient_NeverIssuesWritesExceptThePatchMethod(t *testing.T) {
	var methodsSeen []string
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		methodsSeen = append(methodsSeen, r.Method)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"metadata": map[string]any{"name": "crashloop-demo", "uid": "uid-1", "resourceVersion": "1"},
			"items":    []any{},
		})
	})
	_, _ = c.GetDeployment(context.Background(), "crashloop-demo")
	_, _, _ = c.ListPods(context.Background())
	_, _, _ = c.ReplicaSetUIDsOwnedBy(context.Background(), "uid-1")
	_, _ = c.PatchDeploymentRestartAnnotation(context.Background(), "crashloop-demo", "now", "proposal-1", "uid-1", "1")

	for _, m := range methodsSeen {
		if m != http.MethodGet && m != http.MethodPatch {
			t.Fatalf("unexpected HTTP method issued: %s", m)
		}
	}
}

func TestListPods_BoundedToConfiguredNamespace(t *testing.T) {
	var pathSeen string
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		pathSeen = r.URL.Path
		_ = json.NewEncoder(w).Encode(map[string]any{"items": []any{}})
	})
	_, complete, err := c.ListPods(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !complete {
		t.Fatal("expected a complete (no continuation) result")
	}
	if !contains(pathSeen, "/reliability-sandbox/") {
		t.Fatalf("expected path to be scoped to reliability-sandbox, got %s", pathSeen)
	}
	if contains(pathSeen, "secret") {
		t.Fatalf("unexpected secrets-shaped path: %s", pathSeen)
	}
}

// ---------------------------------------------------------------------
// Issue 3: atomic resourceVersion-conditioned PATCH
// ---------------------------------------------------------------------

func TestPatchDeploymentRestartAnnotation_SendsOnlyTheRestartAnnotationsAndIdentityPreconditions(t *testing.T) {
	var capturedBody map[string]any
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPatch {
			t.Fatalf("expected PATCH, got %s", r.Method)
		}
		_ = json.NewDecoder(r.Body).Decode(&capturedBody)
		_ = json.NewEncoder(w).Encode(map[string]any{"metadata": map[string]any{"uid": "uid-1"}})
	})
	_, err := c.PatchDeploymentRestartAnnotation(context.Background(), "crashloop-demo", "2026-01-01T00:00:00Z", "proposal-1", "uid-1", "100")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	metadata, ok := capturedBody["metadata"].(map[string]any)
	if !ok {
		t.Fatalf("expected a top-level 'metadata' key carrying the identity precondition, got %v", capturedBody)
	}
	if metadata["uid"] != "uid-1" || metadata["resourceVersion"] != "100" {
		t.Fatalf("expected metadata.uid=uid-1 and metadata.resourceVersion=100, got %v", metadata)
	}

	spec, ok := capturedBody["spec"].(map[string]any)
	if !ok {
		t.Fatalf("expected a 'spec' key in the patch body, got %v", capturedBody)
	}
	// The patch must touch ONLY spec.template.metadata.annotations --
	// never replicas, image, or any other field.
	if _, hasReplicas := spec["replicas"]; hasReplicas {
		t.Fatal("patch body unexpectedly touches spec.replicas")
	}
	template, _ := spec["template"].(map[string]any)
	templateMetadata, _ := template["metadata"].(map[string]any)
	annotations, _ := templateMetadata["annotations"].(map[string]any)
	if annotations[RestartedForProposalAnnotation] != "proposal-1" {
		t.Fatalf("expected the proposal-marker annotation to be set, got %v", annotations)
	}
}

func TestPatchDeploymentRestartAnnotation_ResourceVersionConflictIsErrConflict(t *testing.T) {
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusConflict)
	})
	_, err := c.PatchDeploymentRestartAnnotation(context.Background(), "crashloop-demo", "now", "proposal-1", "uid-1", "100")
	if err != ErrConflict {
		t.Fatalf("expected ErrConflict, got %v", err)
	}
}

func TestPatchDeploymentRestartAnnotation_422IsAlsoErrConflict(t *testing.T) {
	// Some API server versions report an immutable-field (uid)
	// mismatch via 422 rather than 409 -- both mean the same thing
	// here: the resource's identity/version no longer matches.
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnprocessableEntity)
	})
	_, err := c.PatchDeploymentRestartAnnotation(context.Background(), "crashloop-demo", "now", "proposal-1", "uid-1", "100")
	if err != ErrConflict {
		t.Fatalf("expected ErrConflict, got %v", err)
	}
}

// ---------------------------------------------------------------------
// Issue 4: pagination / completeness / malformed items
// ---------------------------------------------------------------------

func TestListPods_FollowsContinuationToken(t *testing.T) {
	calls := 0
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		if !contains(r.URL.RawQuery, "continue=") {
			_ = json.NewEncoder(w).Encode(map[string]any{
				"metadata": map[string]any{"continue": "tok-1"},
				"items":    []any{map[string]any{"metadata": map[string]any{"name": "pod-a", "uid": "pod-a-uid"}, "status": map[string]any{"phase": "Running"}}},
			})
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"metadata": map[string]any{},
			"items":    []any{map[string]any{"metadata": map[string]any{"name": "pod-b", "uid": "pod-b-uid"}, "status": map[string]any{"phase": "Running"}}},
		})
	})
	pods, complete, err := c.ListPods(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !complete {
		t.Fatal("expected complete=true once the continuation page was followed to its end")
	}
	if len(pods) != 2 || calls != 2 {
		t.Fatalf("expected 2 pods across 2 page fetches, got %d pods, %d calls", len(pods), calls)
	}
}

func TestListPods_EmptyFirstPageWithContinuationIsNeverReportedComplete(t *testing.T) {
	// Reproduces the exact independent-review finding: {metadata:
	// {continue: "next"}, items: []} must never be silently treated
	// as a complete, empty list.
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		if !contains(r.URL.RawQuery, "continue=") {
			_ = json.NewEncoder(w).Encode(map[string]any{"metadata": map[string]any{"continue": "next"}, "items": []any{}})
			return
		}
		w.WriteHeader(http.StatusForbidden) // the next page is unreachable in this test
	})
	pods, complete, err := c.ListPods(context.Background())
	if err != nil {
		t.Fatalf("unexpected error (a later-page failure must be reported as incomplete, not an error): %v", err)
	}
	if complete {
		t.Fatal("expected complete=false -- a continuation token existed and the next page could not be read")
	}
	if len(pods) != 0 {
		t.Fatalf("expected 0 pods preserved from the empty first page, got %d", len(pods))
	}
}

func TestListPods_BoundedAtMaxPages(t *testing.T) {
	calls := 0
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		_ = json.NewEncoder(w).Encode(map[string]any{
			"metadata": map[string]any{"continue": "keep-going"}, // always more pages
			"items":    []any{},
		})
	})
	_, complete, err := c.ListPods(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if complete {
		t.Fatal("expected complete=false -- the bounded page limit was reached")
	}
	if calls > maxPages {
		t.Fatalf("expected at most %d page fetches, got %d (unbounded pagination loop)", maxPages, calls)
	}
}

func TestListPods_MalformedItemIsSkippedButForcesIncomplete(t *testing.T) {
	// Correction round (Issue 4): reproduces the exact independent-
	// review finding -- a malformed item being silently skipped must
	// ALSO make `complete` false, never true merely because pagination
	// itself terminated cleanly.
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"items": []any{
				"not-an-object", // malformed
				map[string]any{"metadata": map[string]any{"name": "good-pod", "uid": "good-pod-uid"}, "status": map[string]any{"phase": "Running"}},
			},
		})
	})
	pods, complete, err := c.ListPods(context.Background())
	if err != nil {
		t.Fatalf("unexpected error (a malformed item must be skipped, never fatal): %v", err)
	}
	if complete {
		t.Fatal("expected complete=false -- a malformed item was skipped, so this collection is never fully reliable")
	}
	if len(pods) != 1 || pods[0].Name != "good-pod" {
		t.Fatalf("expected exactly the one well-formed pod preserved, got %+v", pods)
	}
}

func TestListPods_ItemMissingUIDIsTreatedAsMalformedAndForcesIncomplete(t *testing.T) {
	// Correction round (Issue 4): a syntactically VALID item that is
	// nonetheless missing its essential identity field (uid) must be
	// treated the same as a malformed item -- never silently
	// defaulted to an empty-string identity.
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"items": []any{
				map[string]any{"metadata": map[string]any{"name": "no-uid-pod"}, "status": map[string]any{"phase": "Running"}},
				map[string]any{"metadata": map[string]any{"name": "good-pod", "uid": "good-pod-uid"}, "status": map[string]any{"phase": "Running"}},
			},
		})
	})
	pods, complete, err := c.ListPods(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if complete {
		t.Fatal("expected complete=false -- an item missing its essential uid field was skipped")
	}
	if len(pods) != 1 || pods[0].Name != "good-pod" {
		t.Fatalf("expected only the well-formed pod to be collected, got %+v", pods)
	}
}

func TestReplicaSetUIDsOwnedBy_IncompleteOnForbiddenNextPage(t *testing.T) {
	c := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		if !contains(r.URL.RawQuery, "continue=") {
			_ = json.NewEncoder(w).Encode(map[string]any{
				"metadata": map[string]any{"continue": "next"},
				"items":    []any{map[string]any{"metadata": map[string]any{"uid": "rs-1", "ownerReferences": []any{map[string]any{"kind": "Deployment", "uid": "uid-1"}}}}},
			})
			return
		}
		w.WriteHeader(http.StatusForbidden)
	})
	owned, complete, err := c.ReplicaSetUIDsOwnedBy(context.Background(), "uid-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if complete {
		t.Fatal("expected complete=false")
	}
	if !owned["rs-1"] {
		t.Fatal("expected the first page's real evidence to still be preserved")
	}
}

// ---------------------------------------------------------------------
// Issue 5: construction-time credential/identity validation
// ---------------------------------------------------------------------

func TestNew_RejectsMissingAPIServerURL(t *testing.T) {
	_, err := New(ExecutorCredentials{CACertPEM: []byte("x"), BearerToken: "t"}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for a missing APIServerURL")
	}
}

func TestNew_RejectsMissingCACert(t *testing.T) {
	_, err := New(ExecutorCredentials{APIServerURL: "https://example.invalid", BearerToken: "t"}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error when no CA certificate is configured (never trust the ambient root store)")
	}
}

func TestNew_RejectsMissingCredential(t *testing.T) {
	_, err := New(ExecutorCredentials{APIServerURL: "https://example.invalid", CACertPEM: []byte("x")}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error when neither a client cert nor a bearer token is configured")
	}
}

func TestNew_RejectsAmbiguousCredential(t *testing.T) {
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid", CACertPEM: []byte("x"),
		ClientCertPEM: []byte("cert"), ClientKeyPEM: []byte("key"), BearerToken: "t",
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error when BOTH a client cert and a bearer token are configured")
	}
}

// ---------------------------------------------------------------------
// Issue 2 (this correction round): transport/credential hardening --
// absolute HTTPS URL, no embedded userinfo, no unexpected path/query/
// fragment, and a complete (never partial) client certificate/key pair.
// ---------------------------------------------------------------------

func TestNew_RejectsHTTPURL(t *testing.T) {
	_, err := New(ExecutorCredentials{
		APIServerURL: "http://example.invalid", CACertPEM: []byte("x"), BearerToken: "t",
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for an unencrypted http:// APIServerURL")
	}
}

func TestNew_RejectsMalformedURL(t *testing.T) {
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid:\x7f", CACertPEM: []byte("x"), BearerToken: "t",
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for a malformed APIServerURL")
	}
}

func TestNew_RejectsEmbeddedUserCredentialsInURL(t *testing.T) {
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://user:pass@example.invalid", CACertPEM: []byte("x"), BearerToken: "t",
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for a URL with embedded user credentials")
	}
}

func TestNew_RejectsUnexpectedPathInURL(t *testing.T) {
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid/some/path", CACertPEM: []byte("x"), BearerToken: "t",
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for a URL with an unexpected path component")
	}
}

func TestNew_RejectsUnexpectedQueryInURL(t *testing.T) {
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid?foo=bar", CACertPEM: []byte("x"), BearerToken: "t",
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for a URL with an unexpected query component")
	}
}

func TestNew_RejectsUnexpectedFragmentInURL(t *testing.T) {
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid#frag", CACertPEM: []byte("x"), BearerToken: "t",
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for a URL with an unexpected fragment component")
	}
}

func TestNew_AcceptsValidHTTPSBearerTokenConfiguration(t *testing.T) {
	// Positive control: a valid, bare https:// URL with a bearer token
	// must still construct successfully.
	caPEM, _ := generateSelfSignedCertForTest(t)
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid:6443", CACertPEM: caPEM, BearerToken: "t",
	}, "reliability-sandbox", time.Second)
	if err != nil {
		t.Fatalf("expected a valid https bearer-token configuration to succeed, got %v", err)
	}
}

func TestNew_RejectsPartialClientCertMissingKey(t *testing.T) {
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid", CACertPEM: []byte("x"),
		ClientCertPEM: []byte("cert-only"),
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for a client certificate configured with no matching key")
	}
}

func TestNew_RejectsPartialClientKeyMissingCert(t *testing.T) {
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid", CACertPEM: []byte("x"),
		ClientKeyPEM: []byte("key-only"),
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for a client key configured with no matching certificate")
	}
}

func TestNew_RejectsPartialClientCertEvenWithBearerTokenAlsoPresent(t *testing.T) {
	// Correction round (Issue 2): the specific regression this
	// finding describes -- a PARTIAL cert/key pair must never be
	// silently folded into "no client cert configured" and allowed to
	// fall through as valid bearer-only auth, discarding the dangling
	// incomplete field.
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid", CACertPEM: []byte("x"),
		ClientCertPEM: []byte("cert-only"), BearerToken: "t",
	}, "reliability-sandbox", time.Second)
	if err == nil {
		t.Fatal("expected an error for an incomplete client cert/key pair even when a bearer token is also configured")
	}
	if !errors.Is(err, ErrMisconfigured) {
		t.Fatalf("expected ErrMisconfigured, got %v", err)
	}
}

func TestNew_AcceptsValidMutualTLSConfiguration(t *testing.T) {
	// Positive control: a COMPLETE client cert/key pair, no bearer
	// token, must still construct successfully. Uses a real,
	// self-signed cert/key pair (tls.X509KeyPair must actually parse
	// it) -- generated inline so this test has no external fixture
	// dependency.
	caPEM, _ := generateSelfSignedCertForTest(t)
	certPEM, keyPEM := generateSelfSignedCertForTest(t)
	_, err := New(ExecutorCredentials{
		APIServerURL: "https://example.invalid", CACertPEM: caPEM,
		ClientCertPEM: certPEM, ClientKeyPEM: keyPEM,
	}, "reliability-sandbox", time.Second)
	if err != nil {
		t.Fatalf("expected a valid mTLS configuration to succeed, got %v", err)
	}
}

// generateSelfSignedCertForTest produces a real, parseable self-signed
// certificate/key PEM pair purely for exercising New()'s own PEM/
// X509KeyPair parsing paths -- never used to validate anything about
// real TLS trust semantics (this package's own real CA/cert material
// always comes from configuration, never from a test helper).
func generateSelfSignedCertForTest(t *testing.T) (certPEM, keyPEM []byte) {
	t.Helper()
	priv, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("failed to generate test key: %v", err)
	}
	template := x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "tool-gateway-test"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
		KeyUsage:     x509.KeyUsageKeyEncipherment | x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		IsCA:         true,
	}
	der, err := x509.CreateCertificate(rand.Reader, &template, &template, &priv.PublicKey, priv)
	if err != nil {
		t.Fatalf("failed to create test certificate: %v", err)
	}
	certPEM = pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyPEM = pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(priv)})
	return certPEM, keyPEM
}

func TestValidateSandboxIdentity_ExactMatchRequired(t *testing.T) {
	if err := ValidateSandboxIdentity(AllowedNamespace, AllowedClusterName); err != nil {
		t.Fatalf("expected the exact allowlisted identity to pass, got %v", err)
	}
	if err := ValidateSandboxIdentity("some-other-namespace", AllowedClusterName); err == nil {
		t.Fatal("expected an unsupported namespace to be rejected")
	}
	if err := ValidateSandboxIdentity(AllowedNamespace, "some-other-cluster"); err == nil {
		t.Fatal("expected an unsupported cluster name to be rejected")
	}
}

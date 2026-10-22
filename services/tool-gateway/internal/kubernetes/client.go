// Package kubernetes is tool-gateway's bounded, read+patch Kubernetes
// REST client for the ONE executable Kubernetes remediation action
// (Phase 12B-D §GATE 6 KUBERNETES EXECUTOR). Mirrors
// detectors/clients/kubernetes_client.py's own discipline, in Go:
//
//   - a FIXED, small set of REST paths, each with exactly one
//     substitution point (the namespace, validated before use) plus,
//     for the one PATCH this package can ever issue, the exact
//     allowlisted deployment name -- never a caller-supplied path;
//   - exactly ONE write method exists on this client at all
//     (PatchDeploymentRestartAnnotation), and it can only ever send a
//     strategic-merge-patch touching `spec.template.metadata.annotations`
//     -- no other field, no other verb, no exec/attach/port-forward,
//     and no Secrets method anywhere in this package;
//   - bounded timeouts and a bounded item cap on every list call;
//   - mutual-TLS OR bearer-token auth, built from an explicit
//     ExecutorCredentials value -- never the ambient/default
//     kubeconfig, never cluster-admin.
//
// Correction round (Issue 3 + Issue 4):
//   - PatchDeploymentRestartAnnotation now carries the expected
//     resourceVersion IN the patch body -- Kubernetes' own documented
//     optimistic-concurrency mechanism for PATCH requests: the API
//     server rejects the request with 409 Conflict if the resource's
//     actual current resourceVersion no longer matches, exactly as it
//     would for a PUT. This makes the identity/precondition check
//     ATOMIC with the write itself, never a separate GET-then-PATCH
//     race window.
//   - ListPods/ReplicaSetUIDsOwnedBy now follow Kubernetes'
//     `metadata.continue` pagination token, bounded to maxPages, and
//     report a `complete bool` -- a caller MUST treat `complete=false`
//     as "evidence gap", never as "the remaining items don't exist".
//     Malformed individual items are skipped (counted, never crash the
//     whole collection), mirroring detectors/kubernetes/parser.py's
//     own defensive discipline.
package kubernetes

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	// MaxItems is a defensive cardinality cap mirroring
	// detectors/clients/kubernetes_client.py's own MAX_ITEMS --
	// applied as the `limit` query parameter on every LIST call, and
	// as the total accumulated-items ceiling across pages.
	MaxItems = 500
	// maxPages bounds how many continuation pages a single ListPods/
	// ReplicaSetUIDsOwnedBy call will ever follow -- "bounded
	// pagination," never an open-ended loop (mirrors detectors/
	// kubernetes/collector.py's own _MAX_PAGES).
	maxPages       = 5
	defaultTimeout = 10 * time.Second
)

var (
	// ErrUnavailable means the Kubernetes API server could not be
	// reached at all (connection refused/timeout/DNS failure) --
	// genuinely transient.
	ErrUnavailable = errors.New("kubernetes API server unavailable")
	// ErrForbidden means the API server was reached but returned 403
	// (RBAC) -- distinct from ErrUnavailable so a caller can tell
	// "nothing answered" apart from "something answered and refused".
	ErrForbidden = errors.New("kubernetes API server forbade this request")
	// ErrNotFound means the API server returned 404 for this exact
	// resource.
	ErrNotFound = errors.New("kubernetes resource not found")
	// ErrConflict means the PATCH's own resourceVersion precondition
	// failed (HTTP 409) -- the resource was modified (or replaced)
	// between the GET that read this resourceVersion and this PATCH.
	// Correction round, Issue 3: this is the ATOMIC identity/
	// precondition failure signal -- never silently retried without
	// re-reading current state first.
	ErrConflict = errors.New("kubernetes resource was concurrently modified (resourceVersion conflict)")
	// ErrUnexpectedResponse means the API server responded, but not
	// with a 2xx/403/404/409 this client understands, or with a body
	// that did not match the expected shape.
	ErrUnexpectedResponse = errors.New("kubernetes API server returned an unexpected response")
	// ErrMisconfigured means New() was called with a namespace/cluster
	// identity or credential shape this package refuses to construct a
	// client from at all -- Issue 5: "reject missing/insecure/
	// ambiguous executor credentials and misconfigured target
	// settings." Never reached by a live HTTP call; this is a
	// construction-time refusal.
	ErrMisconfigured = errors.New("kubernetes executor is misconfigured")
)

// AllowedNamespace and AllowedClusterName are the ONLY sandbox
// identity this executor may ever be configured for (Issue 5). Never
// read from configuration -- these are the actual, hard-coded values
// every caller's claimed configuration is compared against.
const (
	AllowedNamespace   = "reliability-sandbox"
	AllowedClusterName = "kind-reliability-lab"
)

// ValidateSandboxIdentity fails closed unless the caller's claimed
// namespace and cluster name EXACTLY match the one authorized sandbox
// identity. Issue 5: "Do not trust a configuration label alone as
// proof that an arbitrary API server is the intended cluster" --this
// is necessary but not sufficient on its own (a misconfigured
// APIServerURL could still point this claimed identity at the wrong
// endpoint); it is combined with New()'s own credential-shape
// validation below, which is the part that actually binds the
// connection to a specific, non-ambient, non-default trust root.
func ValidateSandboxIdentity(namespace, clusterName string) error {
	if namespace != AllowedNamespace {
		return fmt.Errorf("%w: namespace %q is not the one authorized sandbox namespace (%q)", ErrMisconfigured, namespace, AllowedNamespace)
	}
	if clusterName != AllowedClusterName {
		return fmt.Errorf("%w: cluster name %q is not the one authorized sandbox cluster (%q)", ErrMisconfigured, clusterName, AllowedClusterName)
	}
	return nil
}

// ExecutorCredentials is an explicit, narrowly-scoped identity for the
// Kubernetes EXECUTOR role -- deliberately a SEPARATE Go type from
// anything resembling a full kubeconfig, so this package can never
// accidentally be handed a caller's ambient kubeconfig or
// cluster-admin credential. Exactly one of (CACertPEM +
// (ClientCertPEM + ClientKeyPEM)) or BearerToken is expected to be
// set; neither is required to be non-empty here (an unconfigured
// executor simply means every call below fails closed via TLS/auth
// errors -- never a reason to fall back to an unauthenticated
// request).
type ExecutorCredentials struct {
	APIServerURL  string
	CACertPEM     []byte
	ClientCertPEM []byte
	ClientKeyPEM  []byte
	BearerToken   string
}

// Client is tool-gateway's bounded Kubernetes client, scoped to
// EXACTLY one namespace (set at construction) -- never cluster-wide
// discovery, mirroring detectors/clients/kubernetes_client.py's own
// single-namespace scoping.
type Client struct {
	baseURL    string
	namespace  string
	httpClient *http.Client
	bearer     string
}

// New builds a Client from explicit ExecutorCredentials. Returns an
// error (never panics) if the certificate material cannot be parsed,
// or if the credential shape itself is missing/insecure/ambiguous
// (Issue 5) -- a malformed OR incomplete credential must fail closed
// at construction, never silently fall back to an unauthenticated or
// ambient-trust-store transport.
func New(creds ExecutorCredentials, namespace string, timeout time.Duration) (*Client, error) {
	if timeout <= 0 {
		timeout = defaultTimeout
	}

	if strings.TrimSpace(creds.APIServerURL) == "" {
		return nil, fmt.Errorf("%w: APIServerURL must be set -- never falls back to an ambient/default endpoint", ErrMisconfigured)
	}
	// Correction round (Issue 2): require an absolute, plain HTTPS
	// endpoint -- never assume a configured TLS transport implies
	// HTTPS (a transport is also applied to a plain-HTTP connection
	// without error; the scheme itself must be checked). No embedded
	// user credentials, and no unexpected path/query/fragment, so this
	// client can only ever be pointed at exactly one bare API server
	// origin, never something that could smuggle a second meaning into
	// the "endpoint" configuration value.
	if err := validateAPIServerURL(creds.APIServerURL); err != nil {
		return nil, err
	}
	// Issue 5: never trust the system/ambient root CA pool for this
	// connection -- an explicit CA is required, so this client can
	// only ever validate the one, specific API server it was
	// configured for, never "any HTTPS server with a publicly-trusted
	// certificate".
	if len(creds.CACertPEM) == 0 {
		return nil, fmt.Errorf("%w: CACertPEM must be set -- this client never trusts the ambient/system certificate pool", ErrMisconfigured)
	}
	hasCertPart := len(creds.ClientCertPEM) > 0
	hasKeyPart := len(creds.ClientKeyPEM) > 0
	// Correction round (Issue 2): an INCOMPLETE client certificate/key
	// pair -- exactly one of the two fields set -- is never silently
	// folded into "no client cert configured" (which, with a bearer
	// token also present, would previously fall through as valid
	// bearer-only auth and silently discard the dangling incomplete
	// field). Always a hard configuration error, checked BEFORE the
	// ambiguous-credential check below.
	if hasCertPart != hasKeyPart {
		return nil, fmt.Errorf("%w: an incomplete client certificate/key pair was configured -- ClientCertPEM and ClientKeyPEM must both be set together, never just one (this is checked even when a bearer token is also configured)", ErrMisconfigured)
	}
	hasClientCert := hasCertPart && hasKeyPart
	hasBearerToken := strings.TrimSpace(creds.BearerToken) != ""
	if !hasClientCert && !hasBearerToken {
		return nil, fmt.Errorf("%w: no credential configured -- either (ClientCertPEM+ClientKeyPEM) or BearerToken is required", ErrMisconfigured)
	}
	if hasClientCert && hasBearerToken {
		return nil, fmt.Errorf("%w: both a client certificate AND a bearer token are configured -- exactly one authentication mechanism is required, never both (likely a configuration error)", ErrMisconfigured)
	}

	tlsConfig := &tls.Config{MinVersion: tls.VersionTLS12}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(creds.CACertPEM) {
		return nil, fmt.Errorf("%w: could not parse the configured CA certificate", ErrUnexpectedResponse)
	}
	tlsConfig.RootCAs = pool
	if hasClientCert {
		cert, err := tls.X509KeyPair(creds.ClientCertPEM, creds.ClientKeyPEM)
		if err != nil {
			return nil, fmt.Errorf("%w: could not parse the configured client certificate/key: %v", ErrUnexpectedResponse, err)
		}
		tlsConfig.Certificates = []tls.Certificate{cert}
	}

	return &Client{
		baseURL:   creds.APIServerURL,
		namespace: namespace,
		bearer:    creds.BearerToken,
		httpClient: &http.Client{
			Timeout:   timeout,
			Transport: &http.Transport{TLSClientConfig: tlsConfig},
		},
	}, nil
}

// validateAPIServerURL is Issue 2's own construction-time transport
// hardening: an absolute "https" URL, with a non-empty host, no
// embedded userinfo (e.g. "https://user:pass@host"), and no path/
// query/fragment component -- this client always builds its own
// fixed, bounded REST paths by concatenating `c.baseURL + path` (see
// do()), so a baseURL carrying its own path/query/fragment could
// otherwise silently redirect every request this client ever makes to
// an unintended, caller-chosen location.
func validateAPIServerURL(raw string) error {
	parsed, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("%w: APIServerURL could not be parsed as a URL: %v", ErrMisconfigured, err)
	}
	if parsed.Scheme != "https" {
		return fmt.Errorf("%w: APIServerURL must be an absolute https:// URL, got scheme %q -- unencrypted transport is never permitted", ErrMisconfigured, parsed.Scheme)
	}
	if parsed.User != nil {
		return fmt.Errorf("%w: APIServerURL must not contain embedded user credentials", ErrMisconfigured)
	}
	if parsed.Host == "" {
		return fmt.Errorf("%w: APIServerURL must contain a valid host", ErrMisconfigured)
	}
	if parsed.Path != "" {
		return fmt.Errorf("%w: APIServerURL must not contain a path component, got %q", ErrMisconfigured, parsed.Path)
	}
	if parsed.RawQuery != "" {
		return fmt.Errorf("%w: APIServerURL must not contain a query component", ErrMisconfigured)
	}
	if parsed.Fragment != "" {
		return fmt.Errorf("%w: APIServerURL must not contain a fragment component", ErrMisconfigured)
	}
	return nil
}

// newWithTransport is the test-only seam (mirrors every other
// client in this service using httptest.Server + a real *http.Client
// pointed at it, never a mocked transport internal) -- unexported, so
// it can never be reached from outside this package's own tests.
func newWithTransport(baseURL, namespace, bearer string, httpClient *http.Client) *Client {
	return &Client{baseURL: baseURL, namespace: namespace, bearer: bearer, httpClient: httpClient}
}

// NewInsecureForTesting builds a Client against a plain-HTTP
// httptest.Server, deliberately bypassing New()'s own Issue-5
// credential/identity validation (there is no TLS, and no real
// identity, to validate against a local in-memory test server). This
// is the test-only seam for OTHER packages' tests (api/*_test.go) that
// need a real *kubernetes.Client wired to an httptest.Server -- never
// called from server.go or any other non-test production code path.
func NewInsecureForTesting(baseURL, namespace string, timeout time.Duration) *Client {
	if timeout <= 0 {
		timeout = defaultTimeout
	}
	return &Client{baseURL: baseURL, namespace: namespace, httpClient: &http.Client{Timeout: timeout}}
}

func (c *Client) do(ctx context.Context, method, path string, body []byte) (int, []byte, error) {
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return 0, nil, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	if c.bearer != "" {
		req.Header.Set("Authorization", "Bearer "+c.bearer)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/strategic-merge-patch+json")
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return 0, nil, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20)) // 1 MiB bound, defensive
	if err != nil {
		return resp.StatusCode, nil, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	return resp.StatusCode, respBody, nil
}

// Deployment is the small, bounded subset of a real Deployment object
// this package actually needs -- extra JSON fields are ignored (Go's
// default `encoding/json` behavior), never a strict/exhaustive mirror.
type Deployment struct {
	Metadata struct {
		Name            string `json:"name"`
		UID             string `json:"uid"`
		ResourceVersion string `json:"resourceVersion"`
		Generation      int64  `json:"generation"`
	} `json:"metadata"`
	Spec struct {
		Replicas *int32 `json:"replicas"`
		Template struct {
			Metadata struct {
				Annotations map[string]string `json:"annotations"`
			} `json:"metadata"`
		} `json:"template"`
	} `json:"spec"`
	Status struct {
		ObservedGeneration int64 `json:"observedGeneration"`
		Replicas           int32 `json:"replicas"`
		ReadyReplicas      int32 `json:"readyReplicas"`
		AvailableReplicas  int32 `json:"availableReplicas"`
		Conditions         []struct {
			Type   string `json:"type"`
			Status string `json:"status"`
			Reason string `json:"reason"`
		} `json:"conditions"`
	} `json:"status"`
}

// GetDeployment is a single, bounded GET -- the identity/precondition
// read used both before patching (UID/generation/resourceVersion
// check) and (via the SAME method) during recovery verification.
func (c *Client) GetDeployment(ctx context.Context, name string) (*Deployment, error) {
	path := fmt.Sprintf("/apis/apps/v1/namespaces/%s/deployments/%s", c.namespace, name)
	status, body, err := c.do(ctx, http.MethodGet, path, nil)
	if err != nil {
		return nil, err
	}
	switch status {
	case http.StatusForbidden:
		return nil, ErrForbidden
	case http.StatusNotFound:
		return nil, ErrNotFound
	case http.StatusOK:
		var d Deployment
		if jsonErr := json.Unmarshal(body, &d); jsonErr != nil {
			return nil, fmt.Errorf("%w: %v", ErrUnexpectedResponse, jsonErr)
		}
		return &d, nil
	default:
		return nil, fmt.Errorf("%w: http %d", ErrUnexpectedResponse, status)
	}
}

// PodSummary is the small, bounded subset of a real Pod object this
// package needs for recovery verification -- current container
// waiting reason and restart count, never logs/env/secrets.
type PodSummary struct {
	UID                string
	Name               string
	Phase              string
	OwnerReplicaSetUID string
	ContainersReady    bool
	WaitingReason      string // "" if no container is currently waiting
	RestartCount       int32
}

type podListResponse struct {
	Metadata struct {
		Continue string `json:"continue"`
	} `json:"metadata"`
	Items []json.RawMessage `json:"items"`
}

type podItem struct {
	Metadata struct {
		Name            string `json:"name"`
		UID             string `json:"uid"`
		OwnerReferences []struct {
			Kind string `json:"kind"`
			UID  string `json:"uid"`
		} `json:"ownerReferences"`
	} `json:"metadata"`
	Status struct {
		Phase             string `json:"phase"`
		ContainerStatuses []struct {
			Ready        bool  `json:"ready"`
			RestartCount int32 `json:"restartCount"`
			State        struct {
				Waiting *struct {
					Reason string `json:"reason"`
				} `json:"waiting"`
			} `json:"state"`
		} `json:"containerStatuses"`
	} `json:"status"`
}

// parsePodItem returns ok=false both for a syntactically malformed
// item (JSON unmarshal failure) AND for an item that parses but is
// missing its essential identity field (Correction round, Issue 4:
// "malformed or missing essential item identity/ownership fields must
// not be treated as a fully reliable collection"). A missing UID is
// never defaulted to the empty string and treated as a real pod --
// among other things, an empty-string UID would otherwise collide
// with an unowned pod's zero-value OwnerReplicaSetUID if a
// replicaset item were ALSO missing its UID (see the analogous check
// in ReplicaSetUIDsOwnedBy below).
func parsePodItem(raw json.RawMessage) (PodSummary, bool) {
	var item podItem
	if err := json.Unmarshal(raw, &item); err != nil {
		return PodSummary{}, false
	}
	if item.Metadata.UID == "" {
		return PodSummary{}, false
	}
	summary := PodSummary{UID: item.Metadata.UID, Name: item.Metadata.Name, Phase: item.Status.Phase}
	for _, ref := range item.Metadata.OwnerReferences {
		if ref.Kind == "ReplicaSet" {
			summary.OwnerReplicaSetUID = ref.UID
		}
	}
	allReady := len(item.Status.ContainerStatuses) > 0
	for _, cs := range item.Status.ContainerStatuses {
		if !cs.Ready {
			allReady = false
		}
		if cs.RestartCount > summary.RestartCount {
			summary.RestartCount = cs.RestartCount
		}
		if cs.State.Waiting != nil && cs.State.Waiting.Reason != "" {
			summary.WaitingReason = cs.State.Waiting.Reason
		}
	}
	summary.ContainersReady = allReady
	return summary, true
}

// ListPods is bounded to this client's own namespace, MaxItems, and
// maxPages pagination pages -- never cluster-wide, never unbounded.
// Returns (pods, complete, err): `complete=false` means a continuation
// page existed that this call did NOT follow (the bounded page/item
// cap was reached) or a LATER page failed/was forbidden/malformed --
// in that case `pods` still contains whatever WAS successfully
// collected (never discarded), but the caller MUST NOT treat this as
// a complete picture of the namespace's pods (Issue 4: never derive a
// healthy/unhealthy conclusion from an incomplete collection).
// `complete=false` ALSO results from any single item in an otherwise
// fully-paginated collection being malformed or missing its essential
// identity field (correction round, Issue 4 follow-up) -- pagination
// completeness alone is not "reliable"; a collection with even one
// dropped item is never treated as the whole truth either.
func (c *Client) ListPods(ctx context.Context) ([]PodSummary, bool, error) {
	var pods []PodSummary
	continueToken := ""
	pagesFetched := 0
	// Correction round (Issue 4): a malformed/identity-less item being
	// silently skipped must ALSO make the overall collection
	// unreliable -- `complete` previously reflected ONLY whether
	// pagination itself fully terminated, which let a page containing
	// skipped-but-undetected malformed items still report
	// complete=true. Never again: any skipped item forces complete=false,
	// exactly like an incomplete pagination walk.
	anyMalformed := false

	for {
		path := fmt.Sprintf("/api/v1/namespaces/%s/pods?limit=%d", c.namespace, MaxItems)
		if continueToken != "" {
			path += "&continue=" + url.QueryEscape(continueToken)
		}
		status, body, err := c.do(ctx, http.MethodGet, path, nil)
		if err != nil {
			if pagesFetched == 0 {
				return nil, false, err
			}
			return pods, false, nil // a later page transport failure -- preserve what we have, report incomplete
		}
		pagesFetched++

		switch status {
		case http.StatusForbidden:
			if pagesFetched == 1 {
				return nil, false, ErrForbidden
			}
			return pods, false, nil
		case http.StatusNotFound:
			if pagesFetched == 1 {
				return nil, false, ErrNotFound
			}
			return pods, false, nil
		case http.StatusOK:
			var resp podListResponse
			if jsonErr := json.Unmarshal(body, &resp); jsonErr != nil {
				if pagesFetched == 1 {
					return nil, false, fmt.Errorf("%w: %v", ErrUnexpectedResponse, jsonErr)
				}
				return pods, false, nil
			}
			for _, raw := range resp.Items {
				if summary, ok := parsePodItem(raw); ok {
					pods = append(pods, summary)
				} else {
					anyMalformed = true // skipped, never crash the whole collection, but never "fully reliable" either
				}
				if len(pods) >= MaxItems {
					return pods, resp.Metadata.Continue == "" && !anyMalformed, nil
				}
			}
			if resp.Metadata.Continue == "" {
				return pods, !anyMalformed, nil
			}
			if pagesFetched >= maxPages {
				return pods, false, nil
			}
			continueToken = resp.Metadata.Continue
		default:
			if pagesFetched == 1 {
				return nil, false, fmt.Errorf("%w: http %d", ErrUnexpectedResponse, status)
			}
			return pods, false, nil
		}
	}
}

type replicaSetListResponse struct {
	Metadata struct {
		Continue string `json:"continue"`
	} `json:"metadata"`
	Items []json.RawMessage `json:"items"`
}

type replicaSetItem struct {
	Metadata struct {
		UID             string `json:"uid"`
		OwnerReferences []struct {
			Kind string `json:"kind"`
			UID  string `json:"uid"`
		} `json:"ownerReferences"`
	} `json:"metadata"`
}

// ReplicaSetUIDsOwnedBy resolves which ReplicaSet UIDs, in this
// client's namespace, are owned by the given Deployment UID -- the one
// extra lookup ListPods' own pod-to-Deployment attribution needs,
// since a Pod's ownerReferences point at its ReplicaSet, never
// directly at its Deployment. Same bounded-pagination/completeness
// contract as ListPods.
func (c *Client) ReplicaSetUIDsOwnedBy(ctx context.Context, deploymentUID string) (map[string]bool, bool, error) {
	owned := map[string]bool{}
	continueToken := ""
	pagesFetched := 0
	itemsSeen := 0
	// Correction round (Issue 4): same "any skipped item forces
	// complete=false" discipline as ListPods above.
	anyMalformed := false

	for {
		path := fmt.Sprintf("/apis/apps/v1/namespaces/%s/replicasets?limit=%d", c.namespace, MaxItems)
		if continueToken != "" {
			path += "&continue=" + url.QueryEscape(continueToken)
		}
		status, body, err := c.do(ctx, http.MethodGet, path, nil)
		if err != nil {
			if pagesFetched == 0 {
				return nil, false, err
			}
			return owned, false, nil
		}
		pagesFetched++

		switch status {
		case http.StatusForbidden:
			if pagesFetched == 1 {
				return nil, false, ErrForbidden
			}
			return owned, false, nil
		case http.StatusNotFound:
			if pagesFetched == 1 {
				return nil, false, ErrNotFound
			}
			return owned, false, nil
		case http.StatusOK:
			var resp replicaSetListResponse
			if jsonErr := json.Unmarshal(body, &resp); jsonErr != nil {
				if pagesFetched == 1 {
					return nil, false, fmt.Errorf("%w: %v", ErrUnexpectedResponse, jsonErr)
				}
				return owned, false, nil
			}
			for _, raw := range resp.Items {
				var item replicaSetItem
				if jsonErr := json.Unmarshal(raw, &item); jsonErr != nil {
					anyMalformed = true // malformed item skipped, never fatal, never "fully reliable"
					continue
				}
				if item.Metadata.UID == "" {
					// Missing essential identity field -- never
					// defaulted to "" (which would otherwise collide
					// with an unowned pod's zero-value
					// OwnerReplicaSetUID and falsely attribute it to
					// this malformed ReplicaSet).
					anyMalformed = true
					continue
				}
				itemsSeen++
				for _, ref := range item.Metadata.OwnerReferences {
					if ref.Kind == "Deployment" && ref.UID == deploymentUID {
						owned[item.Metadata.UID] = true
					}
				}
				if itemsSeen >= MaxItems {
					return owned, resp.Metadata.Continue == "" && !anyMalformed, nil
				}
			}
			if resp.Metadata.Continue == "" {
				return owned, !anyMalformed, nil
			}
			if pagesFetched >= maxPages {
				return owned, false, nil
			}
			continueToken = resp.Metadata.Continue
		default:
			if pagesFetched == 1 {
				return nil, false, fmt.Errorf("%w: http %d", ErrUnexpectedResponse, status)
			}
			return owned, false, nil
		}
	}
}

// RestartMarkerAnnotation is the ONE annotation key this package ever
// writes -- it encodes the proposal id a restart was performed for,
// which is what makes PatchDeploymentRestartAnnotation's own
// at-most-one-rollout-per-proposal idempotency check possible (see
// executor.go). "kubectl.kubernetes.io/restartedAt" is the standard
// `kubectl rollout restart` annotation; this package reuses that exact
// mechanism rather than inventing a new one.
const (
	RestartedAtAnnotation          = "kubectl.kubernetes.io/restartedAt"
	RestartedForProposalAnnotation = "reliability.internal/restarted-for-proposal"
)

// PatchDeploymentRestartAnnotation is the ONE write method this entire
// package has. It can only ever send a strategic-merge-patch
// containing EXACTLY the two annotations above under
// spec.template.metadata.annotations, PLUS `metadata.resourceVersion`
// and `metadata.uid` -- never any other field. Correction round,
// Issue 3: including `resourceVersion` in the patch body is
// Kubernetes' own documented optimistic-concurrency mechanism for
// PATCH requests -- the API server itself rejects this request with
// 409 (surfaced here as ErrConflict) if the resource's actual current
// resourceVersion no longer matches what the caller last read, closing
// the GET-then-PATCH race window atomically rather than relying on a
// separate, non-atomic comparison. `uid` is also included (Kubernetes
// additionally rejects a patch whose stated UID does not match a live
// resource's own immutable UID) as a second, redundant identity
// safeguard.
func (c *Client) PatchDeploymentRestartAnnotation(ctx context.Context, name, restartedAt, proposalID, expectedUID, expectedResourceVersion string) (int, error) {
	patch := map[string]any{
		"metadata": map[string]any{
			"uid":             expectedUID,
			"resourceVersion": expectedResourceVersion,
		},
		"spec": map[string]any{
			"template": map[string]any{
				"metadata": map[string]any{
					"annotations": map[string]string{
						RestartedAtAnnotation:          restartedAt,
						RestartedForProposalAnnotation: proposalID,
					},
				},
			},
		},
	}
	payload, err := json.Marshal(patch)
	if err != nil {
		return 0, fmt.Errorf("%w: %v", ErrUnexpectedResponse, err)
	}
	path := fmt.Sprintf("/apis/apps/v1/namespaces/%s/deployments/%s", c.namespace, name)
	status, _, err := c.do(ctx, http.MethodPatch, path, payload)
	if err != nil {
		return 0, err
	}
	switch status {
	case http.StatusForbidden:
		return status, ErrForbidden
	case http.StatusNotFound:
		return status, ErrNotFound
	case http.StatusConflict, http.StatusUnprocessableEntity:
		// 409: resourceVersion precondition failed. 422: some API
		// server versions report an immutable-field (uid) mismatch
		// this way instead -- both mean the same thing here: the
		// resource changed identity/version since it was last read.
		return status, ErrConflict
	case http.StatusOK:
		return status, nil
	default:
		return status, fmt.Errorf("%w: http %d", ErrUnexpectedResponse, status)
	}
}

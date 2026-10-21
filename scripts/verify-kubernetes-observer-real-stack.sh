#!/usr/bin/env bash
#
# verify-kubernetes-observer-real-stack.sh — Phase 12A OPT-IN,
# READ-ONLY real-cluster acceptance for the Kubernetes observation
# stage (detectors/kubernetes/, detectors/clients/kubernetes_client.py).
#
# Unlike every other verify-*.sh script in this repo, this one talks
# to a real, separate kind cluster (NOT the docker-compose stack) via
# an EXPLICIT kubeconfig path and EXPLICIT context name -- it never
# reads or writes `~/.kube/config`, never runs `kubectl config
# use-context`, never changes the developer's own default kubectl
# context, and never starts/stops/modifies the kind cluster itself.
#
# This script is entirely OPT-IN: if the expected kubeconfig file does
# not exist, it SKIPS (exit 0) rather than failing -- the Kubernetes
# observer is an additive capability, and its absence must never be
# treated as a failure of this repo's other acceptance gates.
#
# Only GET-equivalent, read-only Kubernetes API calls are ever made
# (via `python -m detectors analyze --kubeconfig ...`, which itself
# only ever calls KubernetesClient's 4 GET-only methods -- see
# detectors/tests/test_safety_controls.py's own structural proof of
# that). No Pod, Deployment, or other object in the cluster is ever
# created, modified, or deleted by this script.
#
# This script HONESTLY reports whatever the cluster's CURRENT state
# actually is -- it never assumes a failure is present, and it never
# fabricates one. A "0 Kubernetes findings" result is a valid, honest
# outcome (a healthy cluster), not a test failure.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

KUBECONFIG_PATH="${K8S_OBSERVER_KUBECONFIG:-$HOME/kubernetes-reliability-lab/kubeconfig}"
KUBE_CONTEXT="${K8S_OBSERVER_CONTEXT:-kind-reliability-lab}"
KUBE_NAMESPACE="${K8S_OBSERVER_NAMESPACE:-reliability-sandbox}"

main() {
cd "$REPO_ROOT"

echo "=== Phase 12A real-cluster check: confirming an explicit, opt-in kubeconfig is present ===" >&2
if [[ ! -f "$KUBECONFIG_PATH" ]]; then
  echo "SKIPPED: no kubeconfig found at $KUBECONFIG_PATH -- this script is opt-in and never fabricates a cluster connection. Set K8S_OBSERVER_KUBECONFIG to point at a real kubeconfig to run this check." >&2
  exit 0
fi

echo "=== Phase 12A: python -m detectors analyze --kubeconfig ... (read-only Kubernetes observation, namespace=$KUBE_NAMESPACE) ===" >&2
# --network host: the kind API server is reachable on the HOST's
# loopback interface (e.g. https://127.0.0.1:<port>), same reasoning
# as verify-detectors-real-stack.sh's own use of --network host.
# The kubeconfig is bind-mounted READ-ONLY -- this script never writes
# to it.
#
# Correction round (Issue 5): KUBE_CONTEXT/KUBE_NAMESPACE are
# user-configurable (via K8S_OBSERVER_CONTEXT/K8S_OBSERVER_NAMESPACE)
# and must NEVER be interpolated into the text of the generated
# `bash -c` script -- a value containing a single quote could
# otherwise break out of that quoting and inject arbitrary shell
# syntax into a container that has both --network host and a
# read-write mount of this entire repository. They are instead passed
# as container ENVIRONMENT VARIABLES (`-e`); the inner script
# references them only as `"$KUBE_CONTEXT"`/`"$KUBE_NAMESPACE"`
# (expanded by the INNER shell from its own environment at runtime,
# never re-parsed as shell syntax), and the whole inner script is
# single-quoted so the OUTER shell never substitutes into it at all.
# A malformed/adversarial value still fails safely: it is passed to
# `python -m detectors analyze` as one literal argument, which
# `KubernetesClient`'s own namespace-regex validation
# (`detectors/clients/kubernetes_client.py`) or an "unknown context"
# `KubernetesConfigError` rejects outright -- never executed as a
# command. The report-printing step is its own tracked file
# (scripts/_k8s_report_print.py), not inline Python source, so this
# script never needs Python nested inside shell-inside-shell quoting.
docker run --rm --network host \
  -v "$REPO_ROOT:/app" \
  -v "$KUBECONFIG_PATH:/tmp/k8s-observer-kubeconfig:ro" \
  -e KUBE_CONTEXT="$KUBE_CONTEXT" \
  -e KUBE_NAMESPACE="$KUBE_NAMESPACE" \
  -w /app python:3.13-slim bash -c '
  set -euo pipefail
  pip install -q -r detectors/requirements.txt -r catalog/requirements.txt
  python -m detectors analyze \
    --kubeconfig /tmp/k8s-observer-kubeconfig \
    --kube-context "$KUBE_CONTEXT" \
    --kube-namespace "$KUBE_NAMESPACE" \
    --output /tmp/phase12a-real-cluster-report.json
  echo "--- Kubernetes collection outcomes + findings (as observed, never fabricated) ---" >&2
  python3 scripts/_k8s_report_print.py /tmp/phase12a-real-cluster-report.json
'

echo "" >&2
echo "PHASE 12A REAL-CLUSTER CHECK COMPLETE: this script's own report above is an honest, as-observed snapshot of the real kind cluster at the time it ran -- it is NOT a substitute for the offline test suite's exercised failure scenarios, and no cluster object, credential file, or kubectl context was ever created, modified, or deleted." >&2
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi

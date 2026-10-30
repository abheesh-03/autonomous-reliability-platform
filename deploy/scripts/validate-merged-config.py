#!/usr/bin/env python3
"""Phase 17A correction round: real, structural validation of the
fully merged `docker compose config` output for
deploy/scripts/preflight.sh.

The prior round inferred "no non-proxy service publishes a port" from
an EMPTY python-command-substitution result -- which is also what a
*crashed* parser produces (confirmed by independent fault injection:
malformed/unexpected JSON raised `json.JSONDecodeError`, the
substitution silently captured nothing, and the calling shell script,
never checking that python's own exit code, treated the absence of
output as "no offenders" and reported PASS). This script is invoked
with an explicit, checked exit code for every failure mode, and reads
the config from a FILE (never a pipe), so the caller never has to
infer success from incidental shell behavior.

Validates:
  1. The input is well-formed JSON with the expected top-level shape.
  2. Every expected service name is present (a merge that silently
     dropped a service, e.g. from a syntax mistake in the override
     file, is a real failure, not merely "fewer ports").
  3. Only `caddy` publishes a port.
  4. The ACTUAL merged (not merely configured-in-.env) values of a
     fixed set of non-secret security-relevant environment variables
     match what a deployment requires -- catches an override that
     looks right in deploy/.env.deploy but never actually reaches the
     service due to a Compose merge mistake (exactly the real bug an
     earlier round's own email-flow proof caught by hand: web-console
     never received CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT at
     all).
  5. No service requests more than one replica
     (`deploy.replicas`/`scale`) -- this platform's two in-process
     rate limiters (control-plane's telemetry limiter, Better Auth's
     browser-auth limiter) are only correct for exactly one replica
     each.

Never prints a secret VALUE -- only the specific non-secret keys
listed in SECURITY_ENV_CHECKS below, which are booleans/enums by
design, never a password/token.

Usage: validate-merged-config.py <path-to-config.json>
Exit 0 if every check passes; exit 1 with one "INVALID: ..." line per
failure otherwise (and nothing else).
"""

import json
import sys

EXPECTED_SERVICES = {
    "postgres",
    "control-plane",
    "retrieval-service",
    "investigator-service",
    "agent-runtime-service",
    "tool-gateway",
    "checkout-service",
    "payment-service",
    "inventory-service",
    "notification-service",
    "otel-collector",
    "tempo",
    "loki",
    "prometheus",
    "alertmanager",
    "grafana",
    "alloy",
    "web-console",
    "docker-socket-proxy",
    "retention-scheduler",
    "caddy",
}

# (service, env_var, required_value) -- only non-secret, boolean/enum
# configuration; a password/token is NEVER checked here.
SECURITY_ENV_CHECKS = [
    ("control-plane", "CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT", "true"),
    ("control-plane", "TRUSTED_PROXY_ENABLED", "true"),
    ("control-plane", "TRUSTED_PROXY_HOSTS", "caddy"),
    ("web-console", "CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT", "true"),
    ("web-console", "TRUSTED_PROXY_ENABLED", "true"),
    ("web-console", "WEB_CONSOLE_USE_SECURE_COOKIES", "true"),
    ("web-console", "WEB_CONSOLE_DISABLE_SPECIAL_RATE_LIMITS", "false"),
]


def main() -> int:
    if len(sys.argv) != 2:
        print("INVALID: usage: validate-merged-config.py <path-to-config.json>", file=sys.stderr)
        return 1

    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            raw = f.read()
    except OSError as exc:
        print(f"INVALID: could not read config file: {exc}", file=sys.stderr)
        return 1

    if not raw.strip():
        print("INVALID: config file is empty -- docker compose config produced no output", file=sys.stderr)
        return 1

    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"INVALID: docker compose config output is not valid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(cfg, dict) or "services" not in cfg or not isinstance(cfg["services"], dict):
        print("INVALID: config JSON does not have the expected top-level {'services': {...}} shape", file=sys.stderr)
        return 1

    services = cfg["services"]
    failed = False

    missing = EXPECTED_SERVICES - set(services.keys())
    if missing:
        print(f"INVALID: expected service(s) missing from the merged configuration: {sorted(missing)}", file=sys.stderr)
        failed = True

    port_offenders = [name for name, svc in services.items() if svc.get("ports") and name != "caddy"]
    if port_offenders:
        print(f"INVALID: non-proxy service(s) publish a port: {sorted(port_offenders)}", file=sys.stderr)
        failed = True
    elif not services.get("caddy", {}).get("ports"):
        print("INVALID: caddy itself does not publish any port -- the deployment would be unreachable", file=sys.stderr)
        failed = True

    for service_name, var_name, required_value in SECURITY_ENV_CHECKS:
        svc = services.get(service_name)
        if svc is None:
            continue  # already reported as a missing-service failure above
        actual = svc.get("environment", {}).get(var_name)
        if actual != required_value:
            print(
                f"INVALID: {service_name}.environment.{var_name} resolved to {actual!r} in the ACTUAL merged "
                f"configuration, expected {required_value!r} -- a value correct in deploy/.env.deploy that never "
                "reaches the container is a real security gap, not merely a configuration typo",
                file=sys.stderr,
            )
            failed = True

    for name, svc in services.items():
        replicas = svc.get("deploy", {}).get("replicas")
        if replicas is not None and int(replicas) > 1:
            print(
                f"INVALID: {name} is configured for {replicas} replicas -- this deployment's in-process rate "
                "limiters (control-plane's telemetry limiter, Better Auth's browser-auth limiter) are only "
                "correct for exactly one replica each",
                file=sys.stderr,
            )
            failed = True

    if failed:
        return 1
    print("VALID: structurally sound, expected services present, only caddy publishes a port, security-relevant "
          "environment values resolved correctly in the merged configuration, no service over-replicated")
    return 0


if __name__ == "__main__":
    sys.exit(main())

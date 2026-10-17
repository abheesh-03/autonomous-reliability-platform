"""Environment-variable settings for payment-service's Phase 8
controlled-fault endpoints.

Follows the same "read individual environment variables, never crash
the process for a missing secret" convention every other service in
this platform's config module already uses (e.g.
control_plane.core.config.WebhookSettings) -- an unconfigured token
just makes its own endpoint fail closed (401), and an unset
PAYMENT_FAULT_INJECTION_ENABLED just means the enable endpoint always
safely refuses (Phase 8 §PAYMENT SERVICE CONTROLLED FAULT's own
"default false, Compose/CI may explicitly enable it" requirement).
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("payment_service.config")


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes")


def _opt_env(name: str) -> str | None:
    raw = os.environ.get(name, "")
    return raw if raw.strip() else None


@dataclass(frozen=True)
class FaultInjectionSettings:
    """`enabled` gates the ENABLE endpoint only -- it has no effect on
    CLEAR or the read-only status endpoint, both of which must always
    work (clearing/observing a fault that could not have been enabled
    in the first place is always safe). Defaults to False: a genuinely
    local-development/test-only mechanism that must be explicitly
    opted into by Compose/CI, never on by default."""

    enabled: bool
    injection_token: str | None
    remediation_token: str | None

    @classmethod
    def from_env(cls) -> "FaultInjectionSettings":
        injection_token = _opt_env("PAYMENT_FAULT_INJECTION_TOKEN")
        remediation_token = _opt_env("PAYMENT_REMEDIATION_TOKEN")

        # Phase 8 correction round (finding #3): a runtime, fail-closed
        # guard over scripts/init-remediation-secrets.sh's own
        # distinctness guarantee -- an operator can hand-edit .env or
        # wire up a different deployment system that never ran that
        # script at all. If the two configured values are EQUAL, the
        # one credential meant to only RECOVER the controlled fault
        # would also be able to CREATE it (Phase 8 §SEPARATE
        # FAILURE-INJECTION AND REMEDIATION CREDENTIALS -- exactly the
        # guarantee this split exists to prevent). Deliberately does
        # NOT crash the process (unlike tool-gateway's own dedicated-
        # mutation-service guard): POST /payments/authorize must remain
        # available regardless, so both colliding endpoints are simply
        # made permanently unauthenticatable (neither token is ever
        # set on app.state) instead. Never logs either token VALUE --
        # variable names only.
        if injection_token is not None and remediation_token is not None and injection_token == remediation_token:
            logger.error(
                "PAYMENT_FAULT_INJECTION_TOKEN and PAYMENT_REMEDIATION_TOKEN are configured with the same "
                "value -- refusing to use either; the fault-injection-enable and the "
                "remediation-clear/read endpoints will fail closed (401) until these are made distinct"
            )
            injection_token = None
            remediation_token = None

        return cls(
            enabled=_bool_env("PAYMENT_FAULT_INJECTION_ENABLED", False),
            injection_token=injection_token,
            remediation_token=remediation_token,
        )

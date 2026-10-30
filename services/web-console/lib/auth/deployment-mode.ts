/**
 * Phase 17A: the single, shared "is this a real, secure deployment"
 * flag -- extracted from lib/auth/email-verification-delivery.ts
 * (which defined it privately before this phase) so auth.ts, the new
 * password-reset delivery module, and the trusted-proxy IP
 * configuration all read the EXACT same signal, never a second,
 * independently-drifting flag. Reuses
 * CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT -- the same explicit
 * switch control-plane's own OrganizationContextSettings and
 * agent-runtime-service's mirror of it already use to distinguish a
 * real, tenant-isolated deployment from local development.
 */
import "server-only";

export function isSecureDeployment(): boolean {
  const raw = (process.env.CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT ?? "").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

import "server-only";

import { NextResponse } from "next/server";

/**
 * Explicitly configured trusted origin for THIS console's own
 * same-origin browser mutation APIs -- deliberately never derived
 * from a request's own Host/X-Forwarded-Host header, which an
 * attacker fully controls and which this server must never trust for
 * this purpose. Defaults to the exact origin docker-compose.yml binds
 * this container to (127.0.0.1-only -- see that file's own
 * web-console service comment); override via
 * WEB_CONSOLE_TRUSTED_ORIGIN only if this console is ever bound to a
 * different local address. Read fresh on every call (never cached at
 * module load), matching this codebase's existing token-reading
 * convention.
 */
function trustedOrigin(): string {
  return process.env.WEB_CONSOLE_TRUSTED_ORIGIN ?? "http://127.0.0.1:3101";
}

/**
 * Origin/CSRF guard for this console's three browser-facing mutation
 * Route Handlers (start investigation, resume, remediation decision).
 * Call this FIRST, before any other request parsing or backend call.
 *
 * A real browser's `fetch()` always attaches a real `Origin` header on
 * a same-origin POST (and JavaScript cannot override or spoof it --
 * `Origin` is a forbidden request header for page script), so a
 * genuine same-origin click from this console's own UI always carries
 * the exact trusted origin. A cross-origin page's browser-issued POST
 * carries its OWN origin instead (never the trusted one), and a
 * non-browser caller that omits the header entirely is rejected too --
 * this fails CLOSED on missing, mismatched, or absent Origin, never
 * open by default.
 *
 * Returns a safe, bounded 403 NextResponse (never a raw header value,
 * stack trace, or backend detail) when the request must be rejected,
 * or `null` when it may proceed.
 *
 * IMPORTANT -- THIS IS NOT AUTHENTICATION. It is a defense-in-depth
 * CSRF/cross-origin mitigation layered on top of a console that
 * currently has NO user login/RBAC system (see
 * docs/architecture/phase-9-web-console.md's security-boundary
 * section). It proves a request originated from a browser tab that
 * believes it is talking to this console's own origin, never that the
 * person driving that browser is an authorized operator. This console
 * must never be deployed anywhere an untrusted party can reach it
 * without first adding real authentication, authorization, and CSRF
 * controls on top of this guard, not instead of them.
 */
export function rejectCrossOriginMutation(request: Request): NextResponse | null {
  const origin = request.headers.get("origin");
  if (!origin || origin !== trustedOrigin()) {
    return NextResponse.json({ error: "forbidden", message: "This request was rejected." }, { status: 403 });
  }
  return null;
}

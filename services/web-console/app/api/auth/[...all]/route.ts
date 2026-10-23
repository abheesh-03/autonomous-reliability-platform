/**
 * Phase 14 Gate 2: Better Auth's own Next.js route handler --
 * handles every /api/auth/* request (sign-up, sign-in, sign-out,
 * session, organization management, CSRF/trusted-origin checks) via
 * Better Auth's real, maintained implementation. No custom
 * auth-protocol code lives in this file or anywhere else in this
 * console -- every one of Gate 2's listed mechanisms (CSRF, trusted
 * origins, rate limiting, secure cookies) is Better Auth's own,
 * verified-real implementation, configured in lib/auth/auth.ts.
 */
import { toNextJsHandler } from "better-auth/next-js";

import { auth } from "@/lib/auth/auth";

export const { GET, POST } = toNextJsHandler(auth);

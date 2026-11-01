import { NextResponse, type NextRequest } from "next/server";

/**
 * Phase 18: the ONLY job of this middleware is to tell `RootShell`
 * (a Server Component with no other way to see the current pathname)
 * which request path is being rendered, so it can deliberately give
 * `/demo` and everything under it its own dedicated, session-independent
 * chrome instead of the normal three-branch (anonymous / unresolved
 * actor / full actor) shell selection -- see
 * `components/shell/root-shell.tsx`'s own header comment for why that
 * matters (a signed-in visitor must never see their real organization's
 * sidebar/nav wrapped around recorded-demo content).
 *
 * This performs NO authentication, NO redirect, and NO authorization
 * decision of any kind -- every existing protected route's own real
 * check (`requireActorOrRedirect()`, the backend's own assertion
 * verification) is completely unchanged and still the only real
 * security boundary, exactly as RootShell's own comment already
 * states. This file must stay that narrow.
 */
export function middleware(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set("x-pathname", request.nextUrl.pathname);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: [
    // Every normal page request, excluding Next's own internals and
    // static assets -- this header is only ever consumed by a Server
    // Component layout, never meaningful on an asset/API response.
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};

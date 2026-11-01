import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "../middleware";

// Phase 18: proves the one real security-relevant property of
// middleware.ts -- it ALWAYS recomputes `x-pathname` from the real,
// trusted `request.nextUrl.pathname`, never trusting (or forwarding
// unexamined) any `x-pathname` value a client already sent. This is
// what makes "visit a live, protected route while sending a spoofed
// x-pathname: /demo header" harmless: root-shell.tsx can never be
// tricked into treating a live route as the public demo via a
// client-supplied header.
describe("demo middleware", () => {
  it("overwrites a client-supplied x-pathname header with the real request path", () => {
    const request = new NextRequest("http://127.0.0.1:3101/incidents/11111111-1111-1111-1111-111111111111", {
      headers: { "x-pathname": "/demo" },
    });

    const response = middleware(request);

    expect(response.headers.get("x-middleware-request-x-pathname")).toBe(
      "/incidents/11111111-1111-1111-1111-111111111111",
    );
  });

  it("sets the real pathname for a genuine /demo request", () => {
    const request = new NextRequest("http://127.0.0.1:3101/demo/incident/abc");

    const response = middleware(request);

    expect(response.headers.get("x-middleware-request-x-pathname")).toBe("/demo/incident/abc");
  });
});

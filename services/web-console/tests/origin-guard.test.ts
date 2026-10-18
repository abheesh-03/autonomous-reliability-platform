import { afterEach, describe, expect, it, vi } from "vitest";
import { rejectCrossOriginMutation } from "../lib/server/origin-guard";

afterEach(() => {
  vi.unstubAllEnvs();
});

function requestWith(headers: Record<string, string>): Request {
  return new Request("http://localhost/api/test", { method: "POST", headers });
}

describe("rejectCrossOriginMutation", () => {
  it("defaults the trusted origin to http://127.0.0.1:3101 when WEB_CONSOLE_TRUSTED_ORIGIN is unset", () => {
    vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", undefined);
    const result = rejectCrossOriginMutation(requestWith({ Origin: "http://127.0.0.1:3101" }));
    expect(result).toBeNull();
  });

  it("allows a request whose Origin exactly matches the configured trusted origin", () => {
    vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", "http://127.0.0.1:3101");
    const result = rejectCrossOriginMutation(requestWith({ Origin: "http://127.0.0.1:3101" }));
    expect(result).toBeNull();
  });

  it("rejects a request with no Origin header at all (fails closed, never open)", async () => {
    vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", "http://127.0.0.1:3101");
    const result = rejectCrossOriginMutation(requestWith({}));
    expect(result).not.toBeNull();
    expect(result!.status).toBe(403);
    const body = await result!.json();
    expect(body.error).toBe("forbidden");
  });

  it("rejects a request with an empty Origin header", () => {
    vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", "http://127.0.0.1:3101");
    const result = rejectCrossOriginMutation(requestWith({ Origin: "" }));
    expect(result).not.toBeNull();
    expect(result!.status).toBe(403);
  });

  it("rejects a cross-origin Origin header", () => {
    vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", "http://127.0.0.1:3101");
    const result = rejectCrossOriginMutation(requestWith({ Origin: "http://evil.example.com" }));
    expect(result).not.toBeNull();
    expect(result!.status).toBe(403);
  });

  it("rejects an origin that differs only by scheme or port (no loose/substring matching)", () => {
    vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", "http://127.0.0.1:3101");
    expect(rejectCrossOriginMutation(requestWith({ Origin: "https://127.0.0.1:3101" }))).not.toBeNull();
    expect(rejectCrossOriginMutation(requestWith({ Origin: "http://127.0.0.1:3101.evil.com" }))).not.toBeNull();
    expect(rejectCrossOriginMutation(requestWith({ Origin: "http://127.0.0.1:9999" }))).not.toBeNull();
  });

  it("never derives trust from the request's own Host or X-Forwarded-Host headers", () => {
    vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", "http://127.0.0.1:3101");
    // An attacker fully controls Host/X-Forwarded-Host on their own
    // request; only the real, browser-set Origin header may ever be
    // trusted. A spoofed forwarded-host claiming to be this console
    // must not launder a genuinely cross-origin Origin.
    const result = rejectCrossOriginMutation(
      requestWith({ Origin: "http://evil.example.com", Host: "127.0.0.1:3101", "X-Forwarded-Host": "127.0.0.1:3101" }),
    );
    expect(result).not.toBeNull();
    expect(result!.status).toBe(403);
  });

  it("the rejection response never echoes the untrusted Origin value or any header back to the caller", async () => {
    vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", "http://127.0.0.1:3101");
    const result = rejectCrossOriginMutation(requestWith({ Origin: "http://evil.example.com" }));
    const text = await result!.text();
    expect(text).not.toMatch(/evil\.example\.com/);
  });

  it("respects a non-default configured trusted origin", () => {
    vi.stubEnv("WEB_CONSOLE_TRUSTED_ORIGIN", "http://127.0.0.1:4000");
    expect(rejectCrossOriginMutation(requestWith({ Origin: "http://127.0.0.1:4000" }))).toBeNull();
    expect(rejectCrossOriginMutation(requestWith({ Origin: "http://127.0.0.1:3101" }))).not.toBeNull();
  });
});

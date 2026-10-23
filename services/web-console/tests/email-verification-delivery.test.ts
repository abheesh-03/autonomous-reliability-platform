import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deliverVerificationEmail,
  VerificationEmailNotConfiguredError,
} from "../lib/auth/email-verification-delivery";

/**
 * Phase 14 correction round, BLOCKER 3: "Test the production/secure-
 * mode behavior explicitly." These tests exercise the real
 * `deliverVerificationEmail` function `auth.ts`'s
 * `emailVerification.sendVerificationEmail` hook calls -- no
 * Better Auth/Postgres instance needed to prove this boundary.
 */

const ENV_VAR = "CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT";
const ORIGINAL = process.env[ENV_VAR];

afterEach(() => {
  if (ORIGINAL === undefined) {
    delete process.env[ENV_VAR];
  } else {
    process.env[ENV_VAR] = ORIGINAL;
  }
  vi.restoreAllMocks();
});

describe("deliverVerificationEmail", () => {
  it("fails closed in a secure deployment and never logs the live token", async () => {
    process.env[ENV_VAR] = "true";
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await expect(
      deliverVerificationEmail(
        { email: "victim@example.com" },
        "http://127.0.0.1:3101/verify?token=live-secret-token",
      ),
    ).rejects.toThrow(VerificationEmailNotConfiguredError);

    expect(logSpy).not.toHaveBeenCalled();
  });

  it("treats every truthy spelling of the secure-mode flag identically", async () => {
    for (const value of ["1", "true", "TRUE", "yes", "On"]) {
      process.env[ENV_VAR] = value;
      const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
      await expect(
        deliverVerificationEmail({ email: "x@example.com" }, "http://127.0.0.1:3101/verify?token=t"),
      ).rejects.toThrow(VerificationEmailNotConfiguredError);
      expect(logSpy).not.toHaveBeenCalled();
      logSpy.mockRestore();
    }
  });

  it("logs the real token as an explicit local-development fixture when secure mode is disabled", async () => {
    delete process.env[ENV_VAR];
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await deliverVerificationEmail(
      { email: "dev@example.com" },
      "http://127.0.0.1:3101/verify?token=local-dev-token",
    );

    expect(logSpy).toHaveBeenCalledTimes(1);
    const [message] = logSpy.mock.calls[0] as [string];
    expect(message).toContain("http://127.0.0.1:3101/verify?token=local-dev-token");
    expect(message).toContain("local-development only");
  });

  it("treats an explicit false the same as unset -- local-development behavior", async () => {
    process.env[ENV_VAR] = "false";
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await deliverVerificationEmail({ email: "dev2@example.com" }, "http://127.0.0.1:3101/verify?token=t2");

    expect(logSpy).toHaveBeenCalledTimes(1);
  });
});

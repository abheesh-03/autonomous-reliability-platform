import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Phase 17A item 4: real proof of lib/auth/mail-transport.ts's own
 * SMTP_SECURITY -> nodemailer transport-option mapping (verified
 * against the installed package's real type definitions -- see that
 * module's own docstring) and its isSmtpConfigured()/sendMail()
 * contract, with nodemailer itself mocked -- a real SMTP round trip
 * is proven separately and for real by
 * deploy/scripts/test-email-flows.py against a live deployment stack
 * and a disposable local test receiver (mailpit), not by this unit
 * test.
 */

const sendMailMock = vi.fn();
const closeMock = vi.fn();
const createTransportMock = vi.fn(() => ({ sendMail: sendMailMock, close: closeMock }));

vi.mock("nodemailer", () => ({
  default: { createTransport: createTransportMock },
}));

const ENV_VARS = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_ADDRESS", "SMTP_SECURITY"] as const;
const ORIGINAL: Record<string, string | undefined> = {};

beforeEach(() => {
  for (const name of ENV_VARS) {
    ORIGINAL[name] = process.env[name];
    delete process.env[name];
  }
  sendMailMock.mockReset();
  closeMock.mockReset();
  createTransportMock.mockClear();
});

afterEach(() => {
  for (const name of ENV_VARS) {
    if (ORIGINAL[name] === undefined) delete process.env[name];
    else process.env[name] = ORIGINAL[name];
  }
  vi.resetModules();
});

describe("isSmtpConfigured", () => {
  it("is false when SMTP_HOST/SMTP_FROM_ADDRESS are unset", async () => {
    const { isSmtpConfigured } = await import("../lib/auth/mail-transport");
    expect(isSmtpConfigured()).toBe(false);
  });

  it("is false when only one of SMTP_HOST/SMTP_FROM_ADDRESS is set", async () => {
    process.env.SMTP_HOST = "smtp.example.com";
    const { isSmtpConfigured } = await import("../lib/auth/mail-transport");
    expect(isSmtpConfigured()).toBe(false);
  });

  it("is true when both SMTP_HOST and SMTP_FROM_ADDRESS are set", async () => {
    process.env.SMTP_HOST = "smtp.example.com";
    process.env.SMTP_FROM_ADDRESS = "noreply@example.com";
    const { isSmtpConfigured } = await import("../lib/auth/mail-transport");
    expect(isSmtpConfigured()).toBe(true);
  });
});

describe("sendMail transport option mapping", () => {
  beforeEach(() => {
    process.env.SMTP_HOST = "smtp.example.com";
    process.env.SMTP_FROM_ADDRESS = "noreply@example.com";
    process.env.SMTP_PORT = "587";
  });

  it("maps starttls to secure:false, requireTLS:true", async () => {
    process.env.SMTP_SECURITY = "starttls";
    const { sendMail } = await import("../lib/auth/mail-transport");
    await sendMail({ to: "a@example.com", subject: "s", text: "t" });
    expect(createTransportMock).toHaveBeenCalledWith(
      expect.objectContaining({ secure: false, requireTLS: true, host: "smtp.example.com", port: 587 }),
    );
  });

  it("maps tls to secure:true", async () => {
    process.env.SMTP_SECURITY = "tls";
    process.env.SMTP_PORT = "465";
    const { sendMail } = await import("../lib/auth/mail-transport");
    await sendMail({ to: "a@example.com", subject: "s", text: "t" });
    expect(createTransportMock).toHaveBeenCalledWith(expect.objectContaining({ secure: true, port: 465 }));
  });

  it("maps none to secure:false, ignoreTLS:true", async () => {
    process.env.SMTP_SECURITY = "none";
    const { sendMail } = await import("../lib/auth/mail-transport");
    await sendMail({ to: "a@example.com", subject: "s", text: "t" });
    expect(createTransportMock).toHaveBeenCalledWith(expect.objectContaining({ secure: false, ignoreTLS: true }));
  });

  it("defaults to starttls when SMTP_SECURITY is unset", async () => {
    const { sendMail } = await import("../lib/auth/mail-transport");
    await sendMail({ to: "a@example.com", subject: "s", text: "t" });
    expect(createTransportMock).toHaveBeenCalledWith(expect.objectContaining({ requireTLS: true }));
  });

  it("sends the real message content through to nodemailer and closes the transport", async () => {
    process.env.SMTP_SECURITY = "starttls";
    const { sendMail } = await import("../lib/auth/mail-transport");
    await sendMail({ to: "a@example.com", subject: "real subject", text: "real body", html: "<p>real body</p>" });
    expect(sendMailMock).toHaveBeenCalledWith(
      expect.objectContaining({
        from: "noreply@example.com",
        to: "a@example.com",
        subject: "real subject",
        text: "real body",
        html: "<p>real body</p>",
      }),
    );
    expect(closeMock).toHaveBeenCalledTimes(1);
  });

  it("propagates a real delivery failure as a thrown error, never swallowing it", async () => {
    process.env.SMTP_SECURITY = "starttls";
    sendMailMock.mockRejectedValueOnce(new Error("Connection refused"));
    const { sendMail } = await import("../lib/auth/mail-transport");
    await expect(sendMail({ to: "a@example.com", subject: "s", text: "t" })).rejects.toThrow(/Connection refused/);
    // The transport is still closed even on failure.
    expect(closeMock).toHaveBeenCalledTimes(1);
  });

  it("throws if called without SMTP configured, never silently sending nothing", async () => {
    delete process.env.SMTP_HOST;
    delete process.env.SMTP_FROM_ADDRESS;
    const { sendMail } = await import("../lib/auth/mail-transport");
    await expect(sendMail({ to: "a@example.com", subject: "s", text: "t" })).rejects.toThrow();
    expect(createTransportMock).not.toHaveBeenCalled();
  });
});

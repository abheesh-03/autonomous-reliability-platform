/**
 * Phase 17A item 4: real, configurable SMTP mail delivery for Better
 * Auth's email-verification and password-reset flows
 * (lib/auth/email-verification-delivery.ts,
 * lib/auth/email-reset-delivery.ts).
 *
 * Configuration (deploy/.env.deploy.example): SMTP_HOST, SMTP_PORT,
 * SMTP_USER, SMTP_PASSWORD, SMTP_FROM_ADDRESS, SMTP_SECURITY
 * ("starttls" | "tls" | "none").
 *
 * Uses `nodemailer` (industry-standard, actively maintained Node SMTP
 * client -- v10.2.1 installed, ships its own TypeScript definitions,
 * no separate @types package needed). The `secure`/`requireTLS`/
 * `ignoreTLS` mapping below is verified directly against the
 * installed package's own real type definitions
 * (node_modules/nodemailer/dist/esm/smtp-connection/index.d.ts):
 *   - "starttls" (the common real-provider default on port 587):
 *     `secure: false, requireTLS: true` -- "Force STARTTLS, fail when
 *     the server does not support it."
 *   - "tls" (implicit TLS, typically port 465): `secure: true`.
 *   - "none" (the local test-SMTP-receiver proof ONLY -- rejected by
 *     deploy/scripts/preflight.sh for a real deployment unless
 *     ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF=true): `secure: false,
 *     ignoreTLS: true` -- "Ignore STARTTLS even when the server
 *     advertises it," so a plaintext-only local test receiver is
 *     never subjected to a TLS upgrade it cannot complete.
 *
 * `isSmtpConfigured()` is the single predicate both delivery modules
 * use to decide "do I have a real send path" -- true only when
 * SMTP_HOST and SMTP_FROM_ADDRESS are both non-empty. `sendMail`
 * throws on any delivery failure (never swallows it, and never
 * includes the message body/token in the thrown error) so the
 * caller's own fail-closed/log-fallback behavior stays correct.
 */
import "server-only";

import nodemailer, { type SMTPTransportOptions } from "nodemailer";

export interface SendMailOptions {
  to: string;
  subject: string;
  text: string;
  html?: string;
}

export function isSmtpConfigured(): boolean {
  return Boolean(process.env.SMTP_HOST?.trim() && process.env.SMTP_FROM_ADDRESS?.trim());
}

function transportOptionsFromEnv(): SMTPTransportOptions {
  const host = process.env.SMTP_HOST ?? "";
  const port = Number(process.env.SMTP_PORT ?? "587");
  const user = process.env.SMTP_USER;
  const pass = process.env.SMTP_PASSWORD;
  const security = (process.env.SMTP_SECURITY ?? "starttls").trim().toLowerCase();

  const base = {
    host,
    port,
    auth: user ? { user, pass } : undefined,
  };

  switch (security) {
    case "tls":
      return { ...base, secure: true };
    case "none":
      return { ...base, secure: false, ignoreTLS: true };
    case "starttls":
    default:
      return { ...base, secure: false, requireTLS: true };
  }
}

export async function sendMail(options: SendMailOptions): Promise<void> {
  if (!isSmtpConfigured()) {
    throw new Error("sendMail() called without SMTP configured -- isSmtpConfigured() should have been checked first");
  }
  const transport = nodemailer.createTransport(transportOptionsFromEnv());
  try {
    await transport.sendMail({
      from: process.env.SMTP_FROM_ADDRESS,
      to: options.to,
      subject: options.subject,
      text: options.text,
      html: options.html,
    });
  } catch (error) {
    // Never include the message body/token in the thrown error --
    // only the failure class/underlying SMTP error message (which
    // nodemailer itself never populates with the message content).
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`SMTP delivery failed: ${reason}`);
  } finally {
    transport.close();
  }
}

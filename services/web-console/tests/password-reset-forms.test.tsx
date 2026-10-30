import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * Phase 17A item 4: component-level coverage for the new password-
 * reset UI. A real, end-to-end round trip (real sign-up, real
 * verification email, real reset email, real token, real new
 * password) is proven separately by
 * deploy/scripts/test-email-flows.py against a live deployment
 * stack -- these tests cover the component's own request/response
 * handling and anti-enumeration behavior in isolation.
 */

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const requestPasswordResetMock = vi.fn();
const resetPasswordMock = vi.fn();
vi.mock("@/lib/auth/client", () => ({
  authClient: {
    requestPasswordReset: (...args: unknown[]) => requestPasswordResetMock(...args),
    resetPassword: (...args: unknown[]) => resetPasswordMock(...args),
  },
}));

import { ForgotPasswordForm } from "../components/auth/ForgotPasswordForm";
import { ResetPasswordForm } from "../components/auth/ResetPasswordForm";

afterEach(() => {
  pushMock.mockClear();
  requestPasswordResetMock.mockReset();
  resetPasswordMock.mockReset();
  vi.useRealTimers();
});

describe("ForgotPasswordForm", () => {
  it("shows the same success message for a real account", async () => {
    requestPasswordResetMock.mockResolvedValue({});
    render(<ForgotPasswordForm />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "real@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));
    await waitFor(() => expect(screen.getByRole("status")).toBeDefined());
    expect(requestPasswordResetMock).toHaveBeenCalledWith({ email: "real@example.com", redirectTo: "/reset-password" });
  });

  it("shows the IDENTICAL success message even when the request throws (never reveals account existence)", async () => {
    requestPasswordResetMock.mockRejectedValue(new Error("network failure"));
    render(<ForgotPasswordForm />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "unknown@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));
    await waitFor(() => expect(screen.getByRole("status")).toBeDefined());
    expect(screen.getByRole("status").textContent).toMatch(/if an account exists/i);
  });
});

describe("ResetPasswordForm", () => {
  it("shows an invalid-link message when no token is present", () => {
    render(<ResetPasswordForm token={null} invalidToken={false} />);
    expect(screen.getByRole("alert").textContent).toMatch(/invalid or has expired/i);
  });

  it("shows an invalid-link message when the backend reports an error token", () => {
    render(<ResetPasswordForm token={null} invalidToken={true} />);
    expect(screen.getByRole("alert").textContent).toMatch(/invalid or has expired/i);
  });

  it("submits the real token and new password, then shows success", async () => {
    resetPasswordMock.mockResolvedValue({ error: null });
    render(<ResetPasswordForm token="real-token-value" invalidToken={false} />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "NewSecurePassword123!" } });
    fireEvent.click(screen.getByRole("button", { name: /reset password/i }));
    await waitFor(() => expect(screen.getByRole("status")).toBeDefined());
    expect(resetPasswordMock).toHaveBeenCalledWith({ newPassword: "NewSecurePassword123!", token: "real-token-value" });
  });

  it("shows a clear error for a rejected (invalid/reused) token without leaking details", async () => {
    resetPasswordMock.mockResolvedValue({ error: { message: "invalid token" } });
    render(<ResetPasswordForm token="reused-token" invalidToken={false} />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "NewSecurePassword123!" } });
    fireEvent.click(screen.getByRole("button", { name: /reset password/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
    expect(screen.getByRole("alert").textContent).toMatch(/invalid or has expired/i);
  });

  it("never leaves the button stuck pending on a thrown network error", async () => {
    resetPasswordMock.mockRejectedValue(new Error("network failure"));
    render(<ResetPasswordForm token="real-token-value" invalidToken={false} />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "NewSecurePassword123!" } });
    fireEvent.click(screen.getByRole("button", { name: /reset password/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeDefined());
    expect(screen.getByRole("button", { name: /reset password/i })).toHaveProperty("disabled", false);
  });
});

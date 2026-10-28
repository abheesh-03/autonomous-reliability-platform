import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Independent-review correction round: regression coverage for a real,
// user-reported bug -- a thrown (not merely resolved-with-error)
// failure from `authClient.signUp.email`/`signIn.email` previously left
// the "Create account"/"Sign in" button disabled and spinning forever,
// with no error shown at all. Root cause: lib/auth/client.ts hardcoded
// a "http://127.0.0.1:3101" baseURL into the client bundle, so a user
// reaching the app via a different hostname ("localhost" vs.
// "127.0.0.1" -- different origins to a browser even on the same
// machine) made every authClient call cross-origin and CORS-blocked,
// which makes the underlying fetch() THROW rather than resolve. These
// tests prove the fix at the COMPONENT level (a rejected promise is
// always caught, pending always resets, a clear message is shown) --
// independent of which specific network condition causes the
// rejection.

const pushMock = vi.fn();
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

const signUpEmailMock = vi.fn();
const signInEmailMock = vi.fn();
vi.mock("@/lib/auth/client", () => ({
  authClient: {
    signUp: { email: (...args: unknown[]) => signUpEmailMock(...args) },
    signIn: { email: (...args: unknown[]) => signInEmailMock(...args) },
  },
}));

import { RegisterForm } from "../components/auth/RegisterForm";
import { SignInForm } from "../components/auth/SignInForm";

afterEach(() => {
  pushMock.mockClear();
  refreshMock.mockClear();
  signUpEmailMock.mockReset();
  signInEmailMock.mockReset();
});

function fillAndSubmitRegister() {
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Smoke Test" } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "smoke@example.com" } });
  fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "SmokeTest!23456" } });
  fireEvent.click(screen.getByRole("button", { name: /create account/i }));
}

function fillAndSubmitSignIn() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "smoke@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "SmokeTest!23456" } });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
}

describe("RegisterForm", () => {
  it("navigates to /organizations on a real successful sign-up", async () => {
    signUpEmailMock.mockResolvedValue({ error: null });
    render(<RegisterForm />);
    fillAndSubmitRegister();

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/organizations"));
    expect(refreshMock).toHaveBeenCalled();
  });

  it("shows the real backend error message and resets the button when sign-up resolves with an error", async () => {
    signUpEmailMock.mockResolvedValue({ error: { message: "Email already registered." } });
    render(<RegisterForm />);
    fillAndSubmitRegister();

    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/already registered/i));
    const button = screen.getByRole("button", { name: /create account/i });
    expect(button).toHaveProperty("disabled", false);
    expect(button.getAttribute("aria-busy")).toBeNull();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("REGRESSION: a thrown/rejected sign-up (e.g. a CORS-blocked cross-origin fetch) shows a clear error and never leaves the button spinning forever", async () => {
    signUpEmailMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<RegisterForm />);
    fillAndSubmitRegister();

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/could not reach the server/i),
    );
    const button = screen.getByRole("button", { name: /create account/i });
    expect(button).toHaveProperty("disabled", false);
    expect(button.getAttribute("aria-busy")).toBeNull();
    expect(pushMock).not.toHaveBeenCalled();
  });
});

describe("SignInForm", () => {
  it("navigates to /organizations on a real successful sign-in", async () => {
    signInEmailMock.mockResolvedValue({ error: null });
    render(<SignInForm />);
    fillAndSubmitSignIn();

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/organizations"));
    expect(refreshMock).toHaveBeenCalled();
  });

  it("shows the one fixed, generic error and resets the button on invalid credentials", async () => {
    signInEmailMock.mockResolvedValue({ error: { message: "anything" } });
    render(<SignInForm />);
    fillAndSubmitSignIn();

    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/invalid email or password/i));
    const button = screen.getByRole("button", { name: /sign in/i });
    expect(button).toHaveProperty("disabled", false);
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("REGRESSION: a thrown/rejected sign-in shows a clear error and never leaves the button spinning forever", async () => {
    signInEmailMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<SignInForm />);
    fillAndSubmitSignIn();

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/could not reach the server/i),
    );
    const button = screen.getByRole("button", { name: /sign in/i });
    expect(button).toHaveProperty("disabled", false);
    expect(button.getAttribute("aria-busy")).toBeNull();
    expect(pushMock).not.toHaveBeenCalled();
  });
});

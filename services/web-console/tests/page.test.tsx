import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HomePage from "../app/page";

describe("HomePage", () => {
  it("renders the product identity and the planned navigation sections", () => {
    render(<HomePage />);
    expect(
      screen.getByRole("heading", { name: "Reliability Console" }),
    ).toBeDefined();
    expect(screen.getByText("Incidents")).toBeDefined();
    expect(screen.getByText("Agent Runs")).toBeDefined();
    expect(screen.getByText("System Health")).toBeDefined();
  });
});

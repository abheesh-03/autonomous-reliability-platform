import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Without this, React Testing Library's render() output from one test
// accumulates in the same jsdom document.body across every other test
// in the same file, since Vitest does not auto-register
// @testing-library/react's own cleanup the way some other runners do.
afterEach(() => {
  cleanup();
});

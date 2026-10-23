import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Without this, React Testing Library's render() output from one test
// accumulates in the same jsdom document.body across every other test
// in the same file, since Vitest does not auto-register
// @testing-library/react's own cleanup the way some other runners do.
afterEach(() => {
  cleanup();
});

// Vitest's jsdom environment runs test code inside a separate VM
// context; the native TextEncoder binding allocates its output
// Uint8Array against the ORIGINAL host context regardless, so the
// bytes it returns fail `instanceof Uint8Array` as checked from code
// running inside that VM context -- jose's webapi key-handling
// (lib/server/actor.ts's signAssertion -> signingSecret, called by
// every Route Handler/Server Component test that reaches a real,
// resolved actor) hits exactly this and throws "Key for the HS256
// algorithm must be ... Received an instance of Uint8Array" even
// though the value visibly IS one. Re-wrapping the output via `new
// Uint8Array(bytes)` constructs a fresh instance using the Uint8Array
// constructor *of the realm `encode()` is called from*, which fixes
// the mismatch. This patches TextEncoder.prototype.encode itself
// (test-environment only -- the real Next.js server runtime this
// code ships under never runs inside a jsdom VM context, so
// production behavior is completely unaffected) rather than touching
// any production signing code.
const originalEncode = TextEncoder.prototype.encode;
TextEncoder.prototype.encode = function (...args: Parameters<typeof originalEncode>) {
  return new Uint8Array(originalEncode.apply(this, args));
};

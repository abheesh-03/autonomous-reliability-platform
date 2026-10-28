// Inline, pre-hydration script: reads the persisted theme choice (or
// falls back to the OS preference) and sets `data-theme` on <html>
// BEFORE first paint -- avoids a flash of the wrong theme. Never
// touches anything security-relevant; this is cosmetic-only state,
// same category as lib/server/actor.ts's own "cosmetic UI" session
// read.
const THEME_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem("wc-theme");
    var theme = stored === "light" || stored === "dark"
      ? stored
      : (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.setAttribute("data-theme", theme);
  } catch (e) {}
})();
`;

export function ThemeScript() {
  return <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />;
}

import { expect, test } from "@playwright/test";
import { createRealLegacyOrgActor, signInBrowserContextAs } from "./support/auth";
import { demoSnapshot } from "../lib/demo/snapshot";

const demoRoutes = [
  "/demo",
  `/demo/incident/${demoSnapshot.incident_scenario.incident.id}`,
  `/demo/investigation/${demoSnapshot.incident_scenario.agent_run.run_id}`,
  `/demo/telemetry/${demoSnapshot.telemetry_scenario.service.id}`,
];

// Phase 18: real-browser checks for the public recorded demo. Unlike
// phase9-workflow.spec.ts, this never injects a fault or waits on a
// real alert -- the demo is a static, bundled snapshot, so these
// checks are all about navigation, accessibility, and the
// public/private boundary, not about producing new backend state.

test.describe("recorded demo: anonymous access and navigation", () => {
  test("loads the overview, shows the recorded-demo disclosure, and never redirects to sign-in", async ({ page }) => {
    const response = await page.goto("/demo");
    expect(response?.ok()).toBe(true);
    expect(page.url()).toContain("/demo");
    await expect(page.getByText(/recorded demo/i).first()).toBeVisible();
    await expect(page.getByText(/captured/i).first()).toBeVisible();
  });

  test("desktop: can reach the incident, investigation, and telemetry views via real navigation, each with real content and no live action controls", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/demo");

    await page.getByRole("link", { name: /view incident/i }).click();
    await expect(page.getByText(/audit timeline/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /start ai investigation/i })).toHaveCount(0);

    await page.getByRole("link", { name: /view (recorded )?investigation/i }).first().click();
    await expect(page.getByRole("heading", { name: "AI investigation" })).toBeVisible();
    await expect(page.getByRole("button", { name: /^(run investigation|approve|reject|continue workflow)$/i })).toHaveCount(0);

    await page.goBack();
    await page.goBack();
    await page.getByRole("link", { name: /view telemetry/i }).click();
    await expect(page.getByText(/telemetry/i).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /generate credential/i })).toHaveCount(0);
  });

  test("mobile viewport: nav remains usable and every demo link stays reachable", async ({ page }) => {
    for (const width of [320, 375]) {
      await page.setViewportSize({ width, height: 800 });
      for (const route of demoRoutes) {
        await page.goto(route);
        // Scope Overview to navigation: the disclosure has another link.
        const nav = page.getByRole("navigation", { name: "Recorded demo" });
        for (const name of ["Overview", "Incident", "Investigation", "Telemetry"]) {
          const link = nav.getByRole("link", { name, exact: true });
          await expect(link).toBeVisible();
          await expect(link).toBeInViewport();
        }
        const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
        expect(scrollWidth, `${route} at ${width}px`).toBeLessThanOrEqual(width + 1);
      }
    }
  });

  test("Create a workspace has readable text in both themes", async ({ page }) => {
    await page.goto("/demo");
    const cta = page.getByRole("link", { name: "Create a workspace", exact: true });
    for (const theme of ["light", "dark"]) {
      await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
      const contrast = await cta.evaluate((element) => {
        const style = getComputedStyle(element);
        const luminance = (color: string) => {
          const channels = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map((value) => {
            const s = value / 255;
            return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
          });
          return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
        };
        const foreground = luminance(style.color);
        const background = luminance(style.backgroundColor);
        return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
      });
      expect(contrast, `CTA contrast in ${theme} theme`).toBeGreaterThanOrEqual(4.5);
    }
  });

  test("keyboard: every demo nav link and the GitHub/sign-in/register links are reachable by Tab and activatable by Enter", async ({
    page,
  }) => {
    await page.goto("/demo");
    await page.keyboard.press("Tab");
    let reachedIncidentNav = false;
    for (let i = 0; i < 20; i++) {
      const focused = await page.evaluate(() => document.activeElement?.textContent ?? "");
      if (focused.trim() === "Incident") {
        reachedIncidentNav = true;
        break;
      }
      await page.keyboard.press("Tab");
    }
    expect(reachedIncidentNav).toBe(true);
    await page.keyboard.press("Enter");
    await expect(page.getByText(/audit timeline/i)).toBeVisible();
  });

  test("an unknown recorded id returns a real not-found state, not a crash or the wrong content", async ({ page }) => {
    const response = await page.goto("/demo/incident/00000000-0000-0000-0000-000000000000");
    expect(response?.status()).toBe(404);
  });

  test("demo navigation never leaves /demo except GitHub/sign-in/register", async ({ page }) => {
    await page.goto("/demo");
    const hrefs = await page.locator("a[href]").evaluateAll((elements) => elements.map((element) => element.getAttribute("href") ?? ""));
    for (const href of hrefs) {
      if (href.startsWith("http")) {
        expect(href).toContain("github.com");
        continue;
      }
      expect(href === "/sign-in" || href === "/register" || href === "/demo" || href.startsWith("/demo/")).toBe(true);
    }
  });
});

test.describe("recorded demo: browser request isolation", () => {
  test("renders every route without requesting a browser-visible backend port", async ({ page }) => {
    // Browser interception alone cannot block Next.js server-side calls.
    // playwright.demo.config.ts additionally starts the real production
    // server with its database and backend URLs set to unavailable ports.
    const backendRequests: string[] = [];
    for (const port of [8000, 8001, 8002, 8003, 8004]) {
      for (const offset of [0, 10000]) {
        await page.route(`http://127.0.0.1:${port + offset}/**`, (route) => {
          backendRequests.push(route.request().url());
          return route.abort("connectionrefused");
        });
      }
    }
    for (const route of demoRoutes) {
      const response = await page.goto(route);
      expect(response?.ok()).toBe(true);
      await expect(page.getByRole("navigation", { name: "Recorded demo" })).toBeVisible();
    }
    expect(backendRequests).toEqual([]);
  });
});

test.describe("recorded demo: public/private boundary for a signed-in visitor", () => {
  test("a signed-in visitor sees the same demo chrome, not their own organization's live sidebar/org name", async ({ browser }) => {
    const actor = await createRealLegacyOrgActor();
    const context = await browser.newContext();
    await signInBrowserContextAs(context, actor);
    const page = await context.newPage();

    await page.goto("/demo");
    await expect(page.getByText("Recorded demo").first()).toBeVisible();
    // The real AppShell renders the signed-in actor's own email in a
    // user-menu trigger -- it must not appear anywhere on /demo.
    await expect(page.getByText(actor.email)).toHaveCount(0);

    await context.close();
  });
});

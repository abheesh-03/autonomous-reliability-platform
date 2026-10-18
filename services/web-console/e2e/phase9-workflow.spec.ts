import { expect, test } from "@playwright/test";
import {
  ALERT_NAME,
  assertCheckoutFailedWithPaymentService,
  doCheckout,
  findFreshActiveIncident,
  getAgentRun,
  getAllIncidentEvents,
  getAllRemediationEvents,
  getIncident,
  isAlertFiring,
  isAlertInactive,
  isAlertRecovered,
  paymentFaultClear,
  paymentFaultEnable,
  paymentFaultGet,
  requiredTestHarnessTokens,
  waitFor,
} from "./support/backend";

// Gate F: ONE real end-to-end acceptance test, driven through the
// real browser UI, against the real live stack -- never a mocked
// backend, never a fabricated alert, never a direct PostgreSQL write.
// This test creates its OWN fresh incident via the EXISTING Phase 8
// controlled payment-authorization fault (the same mechanism
// scripts/verify-remediation.sh already uses), so it never reuses
// historical evidence and its freshness is independently provable.
//
// The browser (this page) never sees any protected token -- every
// fault-injection/clearing call below goes directly from this TEST
// RUNNER'S OWN process to payment-service, exactly like
// scripts/verify-remediation.sh's own curl calls, and is never routed
// through web-console. The workflow steps that web-console itself
// performs (start investigation, run/resume, approve/reject, continue
// workflow) are driven ONLY by real clicks in a real browser against
// the real running web-console -- this is what proves the BFF-only,
// zero-browser-credential design actually works end to end, not just
// in unit tests with mocked fetch.
test.describe("Phase 9 operator workflow (real stack)", () => {
  test("incident -> investigate -> approve -> continue -> remediate -> monitoring-resolved", async ({ page }) => {
    test.setTimeout(25 * 60 * 1000);
    requiredTestHarnessTokens();

    // -- 1. Preconditions: fault off, alert inactive (never reuse a
    // pending/firing/decaying alert from an earlier run). --
    const initialFault = await paymentFaultGet();
    expect(initialFault.status).toBe(200);
    expect(initialFault.active).toBe(false);
    expect(await isAlertInactive(ALERT_NAME)).toBe(true);

    const since = new Date().toISOString();
    console.log(`freshness checkpoint: ${since}`);

    let incidentId: string | null = null;
    // Set true ONLY as the very last statement of the try block, i.e.
    // only when EVERY assertion in the entire workflow (including the
    // later alert-recovery/incident-resolved/audit-trail checks) has
    // passed with no exception. This distinction matters: remediation
    // can succeed and something LATER can still fail (e.g. the alert
    // never naturally recovers) -- that is still a failed/incomplete
    // run and must use the catch block's trusted-clear safety net
    // below, never the finally block's read-only verification (which
    // would otherwise silently replace the catch block's own thrown
    // failure, since a throw from `finally` always overrides whatever
    // was propagating from `try`/`catch`).
    let testSucceeded = false;

    try {
      // -- 2. Baseline checkout succeeds before any fault is induced. --
      const baseline = await doCheckout();
      expect(baseline.status).toBe(200);

      // -- 3. Enable the REAL controlled payment authorization fault
      // (test-harness-only token, never seen by web-console). --
      const enabled = await paymentFaultEnable();
      expect(enabled.status).toBe(200);
      expect(enabled.active).toBe(true);

      // -- 4. Sustain real failing traffic until CheckoutServerErrors
      // genuinely fires in both Prometheus and Alertmanager. --
      const firstFailure = await doCheckout();
      assertCheckoutFailedWithPaymentService(firstFailure);

      await waitFor(`${ALERT_NAME} firing`, 40, 5000, async () => {
        const result = await doCheckout();
        assertCheckoutFailedWithPaymentService(result);
        return (await isAlertFiring(ALERT_NAME)) || false;
      });
      console.log(`confirmed: ${ALERT_NAME} is firing from real sustained traffic`);

      // -- 5. Confirm the real Alertmanager webhook created a fresh,
      // active incident after this run's own freshness checkpoint. --
      const incident = await waitFor("a fresh active incident", 20, 3000, () => findFreshActiveIncident(since));
      incidentId = incident.id;
      console.log(`confirmed fresh incident: ${incidentId}`);

      // -- 6. BROWSER: open the incident, confirm it is real and
      // eligible, start a durable AI investigation. --
      await page.goto(`/incidents/${incidentId}`);
      await expect(page.getByText("checkout-service is returning HTTP 5xx errors")).toBeVisible();

      const startButton = page.getByRole("button", { name: /start ai investigation/i });
      await expect(startButton).toBeVisible();
      await startButton.click();

      await expect(page).toHaveURL(/\/agent-runs\/[0-9a-f-]+$/, { timeout: 30_000 });
      const runUrl = page.url();
      const runId = runUrl.split("/agent-runs/")[1];
      console.log(`durable agent run created: ${runId}`);

      // -- 7. The run is seeded but NOT YET EXECUTED: current_node is
      // "start", no investigation report yet, and the control offers
      // to RUN it (never a resume-styled label on a never-started run). --
      await expect(page.getByText("No investigation report yet.")).toBeVisible();
      const runButton = page.getByRole("button", { name: /^run investigation$/i });
      await expect(runButton).toBeVisible();

      // -- 8. Execute the run: this ONE click triggers ONE real resume
      // call that runs the graph all the way to the REAL approval
      // interrupt (investigation + evaluation + proposal creation). --
      await runButton.click();

      await expect(page.getByRole("status")).toContainText(/waiting for human approval/i, { timeout: 60_000 });
      console.log("confirmed: run reached the real waiting_for_approval interrupt");

      // -- 9. The investigation UI is real and evidence-grounded. --
      await expect(page.getByRole("heading", { name: "Investigation report", exact: true })).toBeVisible();
      await expect(page.getByText(/no investigation report yet/i)).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Remediation", exact: true })).toBeVisible();
      await expect(page.getByText("clear_payment_authorization_fault")).toBeVisible();

      // -- 10. Approve/Reject controls are visible because the real
      // durable proposal is genuinely pending_approval. --
      const approveButton = page.getByRole("button", { name: /^approve$/i });
      const rejectButton = page.getByRole("button", { name: /^reject$/i });
      await expect(approveButton).toBeVisible();
      await expect(rejectButton).toBeVisible();
      // "Continue workflow" must NOT exist yet -- nothing has been
      // decided, so there is nothing to continue.
      await expect(page.getByRole("button", { name: /continue workflow/i })).toHaveCount(0);

      // -- 11. Approve. This is a SEPARATE request from resume: it
      // records the decision and atomically moves the incident
      // investigating -> remediating, but must NOT itself execute
      // anything. --
      await approveButton.click();
      await expect(page.getByRole("button", { name: /continue workflow/i })).toBeVisible({ timeout: 20_000 });

      // -- 12. Independently (via the real control-plane/agent-runtime
      // APIs, not the browser) prove: proposal approved, incident
      // remediating, and -- critically -- remediation has NOT
      // executed yet. --
      const liveIncidentAfterApproval = await getIncident(incidentId);
      expect(liveIncidentAfterApproval.status).toBe("remediating");
      const runAfterApproval = await getAgentRun(runId);
      expect(runAfterApproval.status).toBe("waiting_for_approval");
      const proposalId = runAfterApproval.remediation_proposal_id;
      expect(proposalId).toBeTruthy();

      // -- 13. "Continue workflow" is a SEPARATE, explicit click --
      // this is the one that actually calls resume again, which runs
      // tool-gateway execution, clears the real fault, and
      // independently verifies recovery. --
      await page.getByRole("button", { name: /continue workflow/i }).click();

      await expect(page.locator("p", { hasText: "Execution:" })).toContainText(/succeeded/i, { timeout: 90_000 });
      console.log("confirmed: real tool-gateway execution succeeded");

      // -- 13a. Independently (a direct agent-runtime-service read,
      // never the browser) verify the three real recovery-verification
      // booleans are actually true -- visibility of their LABELS alone
      // would not prove this, since the UI renders the same label text
      // regardless of a true/false value (see RecoveryVerificationCard's
      // CheckRow: only the checkmark glyph/color differ). --
      const runAfterRemediation = await getAgentRun(runId);
      expect(runAfterRemediation.recovery_verification).toEqual({
        proposal_succeeded: true,
        fault_inactive: true,
        target_healthy: true,
      });
      console.log("confirmed independently: recovery_verification is {proposal_succeeded, fault_inactive, target_healthy} = true/true/true");

      // -- 13b. Also prove the BROWSER presents the actual successful
      // state -- the real "✓" glyph on each row -- not merely that the
      // label text happens to be present. --
      await expect(page.locator("li", { hasText: "Proposal succeeded" })).toContainText("✓");
      await expect(page.locator("li", { hasText: "Fault inactive" })).toContainText("✓");
      await expect(page.locator("li", { hasText: "Target healthy" })).toContainText("✓");

      // -- 14. The AgentRun itself is now terminal, but the incident
      // must NOT be reported resolved merely because remediation/
      // recovery verification succeeded -- only monitoring may ever
      // say that. --
      const liveIncidentAfterRemediation = await getIncident(incidentId);
      expect(liveIncidentAfterRemediation.status).not.toBe("resolved");
      await expect(page.getByText("Live incident state")).toBeVisible();

      // -- 15. Issue one real fresh checkout to prime the real
      // recovery signal, then wait for CheckoutServerErrors to
      // naturally recover (its rate() window, never shortened). --
      const recoveredCheckout = await doCheckout();
      expect(recoveredCheckout.status).toBe(200);

      await waitFor(`${ALERT_NAME} recovered`, 90, 5000, () => isAlertRecovered(ALERT_NAME));
      console.log(`confirmed: ${ALERT_NAME} naturally recovered`);

      // -- 16. The SAME incident must naturally transition
      // remediating -> resolved via Alertmanager's own real resolved
      // webhook -- never inferred or forced by this console. --
      await waitFor("incident resolved via the real webhook", 20, 3000, async () => {
        const current = await getIncident(incidentId!);
        return (current.status === "resolved" && current.resolved_at) || false;
      });
      console.log("confirmed: incident naturally resolved via monitoring");

      // -- 17. Reload the browser and confirm the UI now reflects the
      // real resolved state in the live (never durable-snapshot)
      // section. --
      await page.reload();
      await expect(page.getByText("Live incident state").locator("..").getByText(/resolved/i).first()).toBeVisible({
        timeout: 15_000,
      });

      // -- 18. Full audit trail, independently verified. --
      const events = await getAllIncidentEvents(incidentId);
      const statusSequence = events
        .filter((e) => e.event_type === "created" || e.event_type === "status_transition")
        .map((e) => e.new_status);
      expect(statusSequence).toEqual(["open", "investigating", "remediating", "resolved"]);

      const remediationEvents = await getAllRemediationEvents(proposalId as string);
      expect(remediationEvents.map((e) => e.event_type)).toEqual([
        "proposed",
        "approved",
        "execution_started",
        "execution_succeeded",
      ]);

      testSucceeded = true;
    } catch (originalError) {
      // -- Failed/incomplete acceptance: this is the ONLY path that
      // issues another privileged fault-clear mutation -- a genuine
      // safety net, since whatever failed may have left the real
      // fault active (e.g. a failure before tool-gateway ever ran).
      // Verified through a fresh independent read; if that
      // verification itself cannot be confirmed, THIS FAILS THE TEST
      // NONZERO rather than silently logging -- but the original
      // failure is never discarded: it is logged explicitly and
      // chained as the thrown error's `cause`, and is always the error
      // ultimately re-thrown when cleanup itself succeeds. Never fakes
      // incident resolution as part of cleanup. --
      console.error("TEST FAILED -- original error (preserved below):", originalError);
      console.error("cleanup: attempting to clear the controlled payment authorization fault via the trusted test-harness recovery action");
      let cleanupConfirmedInactive = false;
      let cleanupDetail = "";
      try {
        await paymentFaultClear();
        const cleared = await paymentFaultGet();
        cleanupConfirmedInactive = cleared.active === false;
        cleanupDetail = `active=${cleared.active}`;
      } catch (cleanupError) {
        cleanupDetail = cleanupError instanceof Error ? cleanupError.message : String(cleanupError);
      }
      if (!cleanupConfirmedInactive) {
        throw new Error(
          `REQUIRED CLEANUP FAILED: could not independently confirm the payment fault is inactive after this test's own failure (${cleanupDetail}). ` +
            "The original test failure is chained as this error's cause and logged above -- it is not discarded.",
          { cause: originalError },
        );
      }
      console.log(`cleanup confirmed via independent read: the payment fault is inactive (${cleanupDetail})`);
      throw originalError;
    } finally {
      // -- Fully successful path ONLY (testSucceeded === true, i.e.
      // the entire try block ran to completion with no exception):
      // tool-gateway has ALREADY cleared the real fault as part of its
      // own verified-successful execution (independently confirmed at
      // step 13a above) -- never issue a second, redundant privileged
      // clear mutation here. Independently READ and verify instead,
      // via a fresh, independent GET (test-harness-only credential,
      // never routed through web-console). If this verification
      // fails, THIS FAILS THE TEST NONZERO. --
      if (testSucceeded) {
        const finalFaultState = await paymentFaultGet();
        if (finalFaultState.active !== false) {
          throw new Error(
            `the payment fault is still active after an otherwise-successful remediation (active=${finalFaultState.active}) -- tool-gateway's own clear did not take effect`,
          );
        }
        console.log("confirmed via independent read: the payment fault is inactive after successful remediation (no redundant clear issued)");
      }
    }
  });
});

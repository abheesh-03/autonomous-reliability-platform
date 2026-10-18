import type { RecoveryVerification } from "../lib/types/agent-run";

// Renders the three real, independently-re-derived checks exactly as
// agent-runtime-service computed them (Phase 8 verify_recovery).
// Deliberately never translates this into "incident resolved" --
// recovery verification and monitoring-driven incident resolution are
// different concepts; the incident's own status (rendered on
// /incidents/[incidentId]) remains the only authority for that.
export function RecoveryVerificationCard({ verification }: { verification: RecoveryVerification }) {
  return (
    <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.3rem" }}>
      <CheckRow label="Proposal succeeded (control-plane record)" value={verification.proposal_succeeded} />
      <CheckRow label="Fault inactive (fresh tool-gateway read)" value={verification.fault_inactive} />
      <CheckRow label="Target healthy (fresh tool-gateway read)" value={verification.target_healthy} />
    </ul>
  );
}

function CheckRow({ label, value }: { label: string; value: boolean }) {
  return (
    <li>
      <span style={{ color: value ? "#a8f3c0" : "#f3c9c9" }}>{value ? "✓" : "✗"}</span>{" "}
      <span style={{ color: "#9fb3c8" }}>{label}</span>
    </li>
  );
}

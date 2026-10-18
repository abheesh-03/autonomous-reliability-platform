import type { InvestigationReport, ResultQuality } from "../lib/types/agent-run";
import { EvidenceList } from "./EvidenceList";
import { RetrievalContextView } from "./RetrievalContextView";

export function InvestigationReportView({
  report,
  resultQuality,
}: {
  report: InvestigationReport;
  resultQuality: ResultQuality | null;
}) {
  return (
    <div>
      {resultQuality && (
        <p>
          <strong>Result quality:</strong> {resultQuality}
        </p>
      )}
      <p>{report.summary}</p>

      <h4 style={{ margin: "1rem 0 0.5rem", fontSize: "0.95rem", color: "#9fb3c8" }}>
        Observations ({report.observations.length})
      </h4>
      <ul style={{ listStyle: "disc", paddingLeft: "1.5rem", display: "grid", gap: "0.3rem" }}>
        {report.observations.map((observation, index) => (
          <li key={index}>{observation.statement}</li>
        ))}
      </ul>

      <h4 style={{ margin: "1rem 0 0.5rem", fontSize: "0.95rem", color: "#9fb3c8" }}>
        Hypotheses ({report.hypotheses.length})
      </h4>
      <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: "0.5rem" }}>
        {report.hypotheses.map((hypothesis, index) => (
          <li key={index} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.6rem" }}>
            <div>{hypothesis.statement}</div>
            <div style={{ color: "#9fb3c8", fontSize: "0.85rem" }}>confidence: {hypothesis.confidence}</div>
          </li>
        ))}
      </ul>

      {report.missing_evidence.length > 0 && (
        <>
          <h4 style={{ margin: "1rem 0 0.5rem", fontSize: "0.95rem", color: "#9fb3c8" }}>Missing evidence</h4>
          <ul style={{ listStyle: "disc", paddingLeft: "1.5rem" }}>
            {report.missing_evidence.map((item, index) => (
              <li key={index}>{item.description}</li>
            ))}
          </ul>
        </>
      )}

      {report.suggested_checks.length > 0 && (
        <>
          <h4 style={{ margin: "1rem 0 0.5rem", fontSize: "0.95rem", color: "#9fb3c8" }}>Suggested checks</h4>
          <ul style={{ listStyle: "disc", paddingLeft: "1.5rem" }}>
            {report.suggested_checks.map((item, index) => (
              <li key={index}>{item.description}</li>
            ))}
          </ul>
        </>
      )}

      <EvidenceList evidence={report.evidence} sourceOutcomes={report.source_outcomes} />

      <h4 style={{ margin: "1rem 0 0.5rem", fontSize: "0.95rem", color: "#9fb3c8" }}>Retrieval context</h4>
      <RetrievalContextView context={report.retrieval_context} />

      <p style={{ color: "#6b7f93", fontSize: "0.85rem", marginTop: "1rem" }}>
        provider: {report.provider.provider}
        {report.provider.model ? ` (${report.provider.model})` : ""} -- configured:{" "}
        {String(report.provider.configured)}
      </p>

      {report.validation_notes.length > 0 && (
        <ul style={{ color: "#9fb3c8", fontSize: "0.85rem" }}>
          {report.validation_notes.map((note, index) => (
            <li key={index}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

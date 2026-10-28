import { Eye, FlaskConical, Lightbulb, SearchX } from "lucide-react";
import type { InvestigationReport, ResultQuality } from "../lib/types/agent-run";
import { Badge } from "./ui/badge";
import { EvidenceList } from "./EvidenceList";
import { RetrievalContextView } from "./RetrievalContextView";

const CONFIDENCE_TONE: Record<string, "critical" | "warning" | "success"> = {
  low: "warning",
  medium: "warning",
  high: "success",
};

// Gate 6: show the plain-language explanation first; evidence/
// retrieval/provider technical detail is real progressive disclosure
// (native <details>, open by default so nothing is ever hidden from
// an existing query/assistive technology -- just visually
// collapsible) rather than a second, competing wall of text above the
// fold.
export function InvestigationReportView({
  report,
  resultQuality,
}: {
  report: InvestigationReport;
  resultQuality: ResultQuality | null;
}) {
  return (
    <div className="space-y-5">
      {resultQuality && (
        <p className="text-sm">
          <strong className="font-medium text-fg">Result quality:</strong>{" "}
          <span className="text-fg-muted">{resultQuality}</span>
        </p>
      )}
      <p className="text-sm leading-relaxed text-fg">{report.summary}</p>

      <section>
        <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-fg">
          <Eye className="h-3.5 w-3.5 text-info-fg" aria-hidden="true" />
          Observed facts ({report.observations.length})
        </h4>
        <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
          {report.observations.map((observation, index) => (
            <li key={index}>{observation.statement}</li>
          ))}
        </ul>
      </section>

      <section>
        <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-fg">
          <Lightbulb className="h-3.5 w-3.5 text-warning-fg" aria-hidden="true" />
          Hypotheses ({report.hypotheses.length})
        </h4>
        <ul className="grid grid-cols-1 gap-2">
          {report.hypotheses.map((hypothesis, index) => (
            <li key={index} className="rounded-lg border border-border bg-surface p-3 text-sm">
              <p className="text-fg">{hypothesis.statement}</p>
              <p className="mt-1.5">
                <Badge tone={CONFIDENCE_TONE[hypothesis.confidence] ?? "neutral"}>
                  confidence: {hypothesis.confidence}
                </Badge>
              </p>
            </li>
          ))}
        </ul>
      </section>

      {report.missing_evidence.length > 0 && (
        <section>
          <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-fg">
            <SearchX className="h-3.5 w-3.5 text-fg-subtle" aria-hidden="true" />
            Missing evidence
          </h4>
          <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
            {report.missing_evidence.map((item, index) => (
              <li key={index}>{item.description}</li>
            ))}
          </ul>
        </section>
      )}

      {report.suggested_checks.length > 0 && (
        <section>
          <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-fg">
            <FlaskConical className="h-3.5 w-3.5 text-accent-soft-fg" aria-hidden="true" />
            Suggested checks
          </h4>
          <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
            {report.suggested_checks.map((item, index) => (
              <li key={index}>{item.description}</li>
            ))}
          </ul>
        </section>
      )}

      <details open className="rounded-lg border border-border">
        <summary className="cursor-pointer select-none px-3 py-2 text-sm font-semibold text-fg">
          Evidence and retrieval context
        </summary>
        <div className="space-y-4 border-t border-border p-3">
          <EvidenceList evidence={report.evidence} sourceOutcomes={report.source_outcomes} />
          <div>
            <h4 className="mb-2 text-sm font-semibold text-fg">Retrieval context</h4>
            <RetrievalContextView context={report.retrieval_context} />
          </div>
        </div>
      </details>

      <p className="text-xs text-fg-subtle">
        provider: {report.provider.provider}
        {report.provider.model ? ` (${report.provider.model})` : ""} -- configured:{" "}
        {String(report.provider.configured)}
      </p>

      {report.validation_notes.length > 0 && (
        <ul className="space-y-0.5 text-xs text-fg-muted">
          {report.validation_notes.map((note, index) => (
            <li key={index}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

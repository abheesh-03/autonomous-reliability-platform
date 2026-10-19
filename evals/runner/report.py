"""JSON + Markdown report writers. Never writes a credential, token,
or raw sensitive header -- the report contains only case ids,
categories, PASS/FAIL/NOT_EVALUATED results, bounded detail strings
this harness itself constructed, and (in real-model mode) a model
identifier/timestamp the caller explicitly opted into recording."""

import json
import pathlib

from evals.scoring.models import RunReport


def write_json_report(report: RunReport, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n")


def _result_counts_line(report: RunReport) -> str:
    return (
        f"**{report.evaluated_case_count}** evaluated — "
        f"**{report.passed}** passed, **{report.failed}** failed, **{report.not_evaluated}** not evaluated"
    )


def render_markdown_report(report: RunReport) -> str:
    lines: list[str] = []
    lines.append("# Phase 10 evaluation report")
    lines.append("")
    lines.append(f"- Dataset version: `{report.dataset_version}`")
    lines.append(f"- Generated at: {report.generated_at}")
    lines.append(f"- Runtime: {report.runtime_seconds:.2f}s")
    lines.append(f"- {_result_counts_line(report)}")
    if report.real_provider:
        lines.append(
            f"- Real provider invoked: `{report.real_provider.get('provider')}` "
            f"model=`{report.real_provider.get('model')}` at {report.real_provider.get('run_timestamp')}"
        )
    else:
        lines.append("- Real provider invoked: no (deterministic offline mode only)")
    lines.append("")

    if report.safety_violations:
        lines.append("## ⚠ Safety violations")
        lines.append("")
        for case_id in report.safety_violations:
            lines.append(f"- `{case_id}`")
        lines.append("")
    else:
        lines.append("## Safety violations: none")
        lines.append("")

    if report.regression_findings:
        lines.append("## Regression findings")
        lines.append("")
        lines.append("| case_id | baseline | current | hard safety invariant |")
        lines.append("|---|---|---|---|")
        for finding in report.regression_findings:
            lines.append(
                f"| `{finding.case_id}` | {finding.baseline_result.value} | {finding.current_result.value} | "
                f"{'yes' if finding.is_hard_safety_invariant else 'no'} |"
            )
        lines.append("")

    if report.metric_drift:
        lines.append("## Soft metric drift (informational only -- never gates CI)")
        lines.append("")
        lines.append("| case_id | metric | baseline | current | delta |")
        lines.append("|---|---|---|---|---|")
        for drift in report.metric_drift:
            arrow = "▲" if drift.delta > 0 else "▼"
            lines.append(
                f"| `{drift.case_id}` | {drift.metric_name} | {drift.baseline_value:.4f} | "
                f"{drift.current_value:.4f} | {arrow} {drift.delta:+.4f} |"
            )
        lines.append("")

    lines.append("## Case results")
    lines.append("")
    lines.append("| case_id | category | mode | result | hard safety | detail |")
    lines.append("|---|---|---|---|---|---|")
    for cr in report.case_results:
        detail = cr.detail.replace("|", "\\|")
        if len(detail) > 160:
            detail = detail[:157] + "..."
        lines.append(
            f"| `{cr.case_id}` | {cr.category} | {cr.evaluation_mode} | {cr.result.value} | "
            f"{'yes' if cr.is_hard_safety_invariant else 'no'} | {detail} |"
        )
    lines.append("")

    retrieval_metrics = [cr for cr in report.case_results if "reciprocal_rank" in cr.metrics]
    if retrieval_metrics:
        mrr = sum(cr.metrics["reciprocal_rank"] for cr in retrieval_metrics) / len(retrieval_metrics)
        hit_rate = sum(cr.metrics.get("hit_at_k", 0.0) for cr in retrieval_metrics) / len(retrieval_metrics)
        lines.append("## Retrieval metrics")
        lines.append("")
        lines.append(f"- MRR across {len(retrieval_metrics)} retrieval case(s): {mrr:.3f}")
        lines.append(f"- Mean Hit@k across {len(retrieval_metrics)} retrieval case(s): {hit_rate:.3f}")
        lines.append(
            "- Computed via the deterministic LOCAL lexical embedding provider over the real "
            "`knowledge/runbooks/*.md` corpus -- this is a ranking-contract check, not a semantic-quality "
            "measurement (see evals/README.md)."
        )
        lines.append("")

    if report.limitations:
        lines.append("## Score limitations")
        lines.append("")
        for limitation in report.limitations:
            lines.append(f"- {limitation}")
        lines.append("")

    return "\n".join(lines)


def write_markdown_report(report: RunReport, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown_report(report))


def render_terminal_summary(report: RunReport) -> str:
    lines = [
        f"Phase 10 evaluation -- dataset {report.dataset_version}",
        _result_counts_line(report).replace("**", ""),
        f"safety violations: {len(report.safety_violations)}",
        f"regression findings: {len(report.regression_findings)}",
        f"metric drift: {len(report.metric_drift)}",
        f"runtime: {report.runtime_seconds:.2f}s",
        f"exit code: {report.exit_code()}",
    ]
    return "\n".join(lines)

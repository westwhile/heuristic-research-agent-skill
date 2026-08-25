"""The three report forms of a ``comparison-report/v1`` payload
(ADR-0006 decision 10): JSON, Markdown, and HTML are rendered from the
same structured payload, so content cannot drift between forms.

- :func:`render_json` is the canonical byte form of the payload itself —
  the report's machine-readable identity;
- :func:`render_markdown` and :func:`render_html` present the same
  fields for humans; every interpolated value is escaped (HTML) or
  pipe-escaped (Markdown tables), and the HTML form is a single
  self-contained file with no external resources (offline discipline).

Every report binds the suite/candidate/envelope/scorer hashes through
its referenced run records and declares its L0/L1 coverage — the
renderers surface both verbatim from the payload.
"""

from __future__ import annotations

import html
from typing import Any, Mapping

from research_evolution.core import canonical_bytes


def render_json(report: Mapping[str, Any]) -> bytes:
    """The canonical byte form of the report payload."""
    return canonical_bytes(report)


def _md_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the report payload as a Markdown document."""
    if report.get("schema") == "suite-comparison/v1":
        return _render_suite_markdown(report)
    lines = [
        f"# {_md_escape(report['title'])}",
        "",
        f"- Report: `{report['report_id']}`",
        f"- Generated at: {report['generated_at']}",
        f"- Levels covered: {', '.join(report['levels_covered'])} "
        "(L0/L1 only; no L2–L4 claim)",
        f"- Champion: `{report['champion']['evaluation_run_id']}` "
        f"(sha256 `{report['champion']['sha256']}`)",
        f"- Challenger: `{report['challenger']['evaluation_run_id']}` "
        f"(sha256 `{report['challenger']['sha256']}`)",
        f"- Statistics: {', '.join(report['methods']['statistics'])}; "
        f"parameters sha256 `{report['methods']['parameters_sha256']}`; "
        f"seed `{report['methods']['seed']}`",
        "",
        "## Score deltas",
        "",
        "| Dimension | Champion | Challenger |",
        "| --- | --- | --- |",
    ]
    for delta in report["score_deltas"]:
        lines.append(
            f"| {_md_escape(delta['dimension'])} "
            f"| {delta['champion_value']} | {delta['challenger_value']} |"
        )
    lines += ["", "## Gate summary", "", "| Gate | Result |", "| --- | --- |"]
    for gate in report["gate_summary"]:
        lines.append(f"| {gate['gate']} | {gate['result']} |")
    lines += ["", "## Conclusion", "", _md_escape(report["conclusion"]), ""]
    if report["limitations"]:
        lines += ["## Limitations", ""]
        lines += [f"- {_md_escape(item)}" for item in report["limitations"]]
        lines.append("")
    return "\n".join(lines)


def render_html(report: Mapping[str, Any]) -> str:
    """Render the report payload as a self-contained HTML document."""
    if report.get("schema") == "suite-comparison/v1":
        return _render_suite_html(report)
    esc = html.escape

    def rows(items: Any, cells: Any) -> str:
        return "\n".join(
            "<tr>" + "".join(f"<td>{esc(str(cell))}</td>" for cell in cells(item)) + "</tr>"
            for item in items
        )

    champion = report["champion"]
    challenger = report["challenger"]
    limitations = "".join(
        f"<li>{esc(str(item))}</li>" for item in report["limitations"]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc(str(report['title']))}</title>
<style>body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; }} td, th {{ border: 1px solid #999; padding: 0.25rem 0.75rem; }}
code {{ background: #f2f2f2; padding: 0 0.25rem; }}</style>
</head>
<body>
<h1>{esc(str(report['title']))}</h1>
<ul>
<li>Report: <code>{esc(str(report['report_id']))}</code></li>
<li>Generated at: {esc(str(report['generated_at']))}</li>
<li>Levels covered: {esc(', '.join(report['levels_covered']))} (L0/L1 only; no L2–L4 claim)</li>
<li>Champion: <code>{esc(str(champion['evaluation_run_id']))}</code> (sha256 <code>{esc(str(champion['sha256']))}</code>)</li>
<li>Challenger: <code>{esc(str(challenger['evaluation_run_id']))}</code> (sha256 <code>{esc(str(challenger['sha256']))}</code>)</li>
<li>Statistics: {esc(', '.join(report['methods']['statistics']))}; parameters sha256 <code>{esc(str(report['methods']['parameters_sha256']))}</code>; seed <code>{esc(str(report['methods']['seed']))}</code></li>
</ul>
<h2>Score deltas</h2>
<table>
<tr><th>Dimension</th><th>Champion</th><th>Challenger</th></tr>
{rows(report['score_deltas'], lambda d: (d['dimension'], d['champion_value'], d['challenger_value']))}
</table>
<h2>Gate summary</h2>
<table>
<tr><th>Gate</th><th>Result</th></tr>
{rows(report['gate_summary'], lambda g: (g['gate'], g['result']))}
</table>
<h2>Conclusion</h2>
<p>{esc(str(report['conclusion']))}</p>
<h2>Limitations</h2>
<ul>
{limitations}
</ul>
</body>
</html>
"""


def _render_suite_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        f"# {_md_escape(report['title'])}",
        "",
        f"- Suite comparison: `{report['suite_comparison_id']}`",
        f"- Suite: `{report['suite']['suite_id']}` (sha256 `{report['suite']['sha256']}`)",
        f"- Observation unit: `{report['observation_unit']}`",
        f"- Expected seeds: {', '.join(str(seed) for seed in report['expected_seeds'])}",
        f"- Champion: `{report['champion']['candidate_id']}` "
        f"(sha256 `{report['champion']['sha256']}`)",
        f"- Challenger: `{report['challenger']['candidate_id']}` "
        f"(sha256 `{report['challenger']['sha256']}`)",
        f"- Statistics: {', '.join(report['methods']['statistics'])}; "
        f"Holm adjustment; parameters sha256 "
        f"`{report['methods']['parameters_sha256']}`",
        "",
        "## Metric analyses",
        "",
        "| Dimension | Role | Direction | n_pairs | Mean difference | CI | p | "
        "Holm p | rank_biserial | Status |",
        "| --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for metric in report["metrics"]:
        lines.append(
            f"| {_md_escape(metric['dimension'])} | {metric['role']} | "
            f"{metric['direction']} | {metric['n_pairs']} | {metric['mean_difference']} | "
            f"[{metric['ci_low']}, {metric['ci_high']}] | {metric['p_value']} | "
            f"{metric['adjusted_p_value']} | {metric['rank_biserial']} | "
            f"{metric['inference_status']} |"
        )
    lines += ["", "## Conclusion", "", _md_escape(report["conclusion"]), ""]
    if report["limitations"]:
        lines += ["## Limitations", ""]
        lines += [f"- {_md_escape(item)}" for item in report["limitations"]]
        lines.append("")
    return "\n".join(lines)


def _render_suite_html(report: Mapping[str, Any]) -> str:
    esc = html.escape
    metric_rows = "\n".join(
        "<tr>"
        + "".join(
            f"<td>{esc(str(value))}</td>"
            for value in (
                metric["dimension"],
                metric["role"],
                metric["direction"],
                metric["n_pairs"],
                metric["mean_difference"],
                f"[{metric['ci_low']}, {metric['ci_high']}]",
                metric["p_value"],
                metric["adjusted_p_value"],
                metric["rank_biserial"],
                metric["inference_status"],
            )
        )
        + "</tr>"
        for metric in report["metrics"]
    )
    limitations = "".join(
        f"<li>{esc(str(item))}</li>" for item in report["limitations"]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{esc(str(report['title']))}</title>
<style>body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; }} td, th {{ border: 1px solid #999; padding: 0.25rem; }}
code {{ background: #f2f2f2; padding: 0 0.25rem; }}</style></head>
<body>
<h1>{esc(str(report['title']))}</h1>
<ul>
<li>Suite comparison: <code>{esc(str(report['suite_comparison_id']))}</code></li>
<li>Observation unit: <code>{esc(str(report['observation_unit']))}</code></li>
<li>Statistics: {esc(', '.join(report['methods']['statistics']))}; Holm adjustment; parameters sha256 <code>{esc(str(report['methods']['parameters_sha256']))}</code></li>
</ul>
<h2>Metric analyses</h2>
<table><tr><th>Dimension</th><th>Role</th><th>Direction</th><th>n_pairs</th><th>Mean difference</th><th>CI</th><th>p</th><th>Holm p</th><th>rank_biserial</th><th>Status</th></tr>
{metric_rows}</table>
<h2>Conclusion</h2><p>{esc(str(report['conclusion']))}</p>
<h2>Limitations</h2><ul>{limitations}</ul>
</body></html>
"""

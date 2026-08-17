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

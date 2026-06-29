"""Self-contained, single-file HTML renderer for the verdict report.

Produces an issuable client deliverable: one ``.html`` file with all CSS
inlined and no external assets, so it can be emailed, archived, or opened
offline. Pure-Python string templating only -- ``jinja2`` is an optional extra
and is intentionally *not* imported here, so the renderer works with the
stdlib alone.

The layout mirrors the design doc's "Generate report" deliverable:

* a header band (project name, generated_at, engine_version, units),
* a summary band of color chips (total / pass / flag / absent / type_mismatch),
* a per-device verdict table with verdict badges, confidence, position /
  mounting-height / orientation deltas (with units), an approximate flag, the
  matched shot, and notes,
* a short "scope & honesty" footer restating the v1 limitations.

All dynamic text is escaped with :func:`html.escape`. Device rows are sorted so
problems (flag / absent / type_mismatch) surface above passing devices.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from ..models import Verdict

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import (
        CapturePackage,
        DeviceResult,
        SpecManifest,
        VerdictReport,
    )

# Verdict -> (human label, chip/badge color). Green/orange/red/purple per spec.
_VERDICT_COLORS: dict[str, str] = {
    Verdict.PASS.value: "#2e7d32",  # green
    Verdict.FLAG.value: "#ef6c00",  # orange
    Verdict.ABSENT.value: "#c62828",  # red
    Verdict.TYPE_MISMATCH.value: "#6a1b9a",  # purple
}

_VERDICT_LABELS: dict[str, str] = {
    Verdict.PASS.value: "PASS",
    Verdict.FLAG.value: "FLAG",
    Verdict.ABSENT.value: "ABSENT",
    Verdict.TYPE_MISMATCH.value: "TYPE MISMATCH",
}

# Sort key: problems first (flag/absent/type_mismatch), then pass. Within a
# bucket, stable by device id for deterministic output.
_VERDICT_SORT_RANK: dict[str, int] = {
    Verdict.FLAG.value: 0,
    Verdict.ABSENT.value: 1,
    Verdict.TYPE_MISMATCH.value: 2,
    Verdict.PASS.value: 3,
}

_PROBLEM_VERDICTS = frozenset(
    {Verdict.FLAG.value, Verdict.ABSENT.value, Verdict.TYPE_MISMATCH.value}
)


def _esc(value: object) -> str:
    """Escape any value to safe HTML text (None -> empty string)."""
    if value is None:
        return ""
    return escape(str(value), quote=True)


def _sorted_results(report: VerdictReport) -> list[DeviceResult]:
    """Device results with problems surfaced first, then by device id."""
    return sorted(
        report.device_results,
        key=lambda r: (_VERDICT_SORT_RANK.get(r.verdict.value, 99), r.device_id),
    )


def _fmt_delta(value: float | None, units: str | None, *, angular: bool = False) -> str:
    """Format a delta with its unit suffix; em-dash when not measurable."""
    if value is None:
        return '<span class="na">&mdash;</span>'
    if angular:
        return f"{value:.1f}&deg;"
    suffix = ""
    if units == "feet":
        suffix = "&nbsp;ft"
    elif units == "meters":
        suffix = "&nbsp;m"
    elif units:
        # Unknown but non-empty units: show the raw value rather than silently
        # dropping it, so a vocabulary change is visible instead of misleading.
        suffix = "&nbsp;" + escape(units)
    return f"{value:.3f}{suffix}"


def _verdict_badge(verdict_value: str) -> str:
    color = _VERDICT_COLORS.get(verdict_value, "#455a64")
    label = _VERDICT_LABELS.get(verdict_value, verdict_value.upper())
    return f'<span class="badge" style="background:{color}">{_esc(label)}</span>'


def _summary_chip(label: str, count: int, color: str) -> str:
    return (
        f'<div class="chip" style="border-color:{color}">'
        f'<div class="chip-count" style="color:{color}">{count}</div>'
        f'<div class="chip-label">{_esc(label)}</div>'
        "</div>"
    )


def _device_label(result: DeviceResult, manifest: SpecManifest | None) -> tuple[str, str]:
    """Resolve (family, type) for a device, preferring the result then manifest."""
    family = result.family
    type_ = result.type
    if (family is None or type_ is None) and manifest is not None:
        dev = next((d for d in manifest.devices if d.id == result.device_id), None)
        if dev is not None:
            family = family if family is not None else dev.family
            type_ = type_ if type_ is not None else dev.type
    return (family or "", type_ or "")


def render_html(
    report: VerdictReport,
    manifest: SpecManifest,
    capture: CapturePackage,
) -> str:
    """Build the full self-contained HTML document as a string."""
    units = report.units or (manifest.project.units if manifest is not None else None)
    project_name = manifest.project.name if manifest is not None else report.project_id

    summary = report.summary
    chips = "".join(
        [
            _summary_chip("Total", summary["total"], "#455a64"),
            _summary_chip("Pass", summary["pass"], _VERDICT_COLORS[Verdict.PASS.value]),
            _summary_chip("Flag", summary["flag"], _VERDICT_COLORS[Verdict.FLAG.value]),
            _summary_chip("Absent", summary["absent"], _VERDICT_COLORS[Verdict.ABSENT.value]),
            _summary_chip(
                "Type mismatch",
                summary["type_mismatch"],
                _VERDICT_COLORS[Verdict.TYPE_MISMATCH.value],
            ),
        ]
    )

    rows: list[str] = []
    for r in _sorted_results(report):
        family, type_ = _device_label(r, manifest)
        is_problem = r.verdict.value in _PROBLEM_VERDICTS
        row_cls = "problem" if is_problem else "ok"
        approx = (
            '<span class="approx" title="Geometry approximate (no metric LiDAR or '
            'protruding/occluded device)">approx.</span>'
            if r.approximate
            else '<span class="na">&mdash;</span>'
        )
        notes = (
            "<br>".join(_esc(n) for n in r.notes) if r.notes else '<span class="na">&mdash;</span>'
        )
        ident = "yes" if r.identity_confirmed else "no"
        rows.append(
            "<tr class='{cls}'>"
            "<td class='mono'>{did}</td>"
            "<td>{fam}<span class='sub'>{typ}</span></td>"
            "<td>{badge}</td>"
            "<td class='num'>{conf:.0%}</td>"
            "<td class='num'>{dpos}</td>"
            "<td class='num'>{dmh}</td>"
            "<td class='num'>{dori}</td>"
            "<td class='center'>{approx}</td>"
            "<td class='mono center'>{ident}</td>"
            "<td class='mono'>{shot}</td>"
            "<td class='notes'>{notes}</td>"
            "</tr>".format(
                cls=row_cls,
                did=_esc(r.device_id),
                fam=_esc(family) or '<span class="na">&mdash;</span>',
                typ=("<br>" + _esc(type_)) if type_ else "",
                badge=_verdict_badge(r.verdict.value),
                conf=max(0.0, min(1.0, r.confidence)),
                dpos=_fmt_delta(r.deltas.position, units),
                dmh=_fmt_delta(r.deltas.mounting_height, units),
                dori=_fmt_delta(r.deltas.orientation, units, angular=True),
                approx=approx,
                ident=_esc(ident),
                shot=(_esc(r.matched_shot_id) or '<span class="na">&mdash;</span>'),
                notes=notes,
            )
        )
    rows_html = (
        "\n".join(rows)
        if rows
        else ("<tr><td colspan='11' class='center na'>No devices in this report.</td></tr>")
    )

    units_label = _esc(units) if units else "&mdash;"
    n_shots = len(capture.shots) if capture is not None else 0

    return _DOCUMENT.format(
        title=_esc(f"Elevation Verification Report — {project_name}"),
        project_name=_esc(project_name),
        project_id=_esc(report.project_id),
        generated_at=_esc(report.generated_at) or "&mdash;",
        engine_version=_esc(report.engine_version) or "&mdash;",
        units_label=units_label,
        n_shots=n_shots,
        chips=chips,
        rows=rows_html,
    )


# --------------------------------------------------------------------------- #
# Template (str.format). Literal CSS braces are doubled.
# --------------------------------------------------------------------------- #
_DOCUMENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --ink: #1a1d21;
    --muted: #66707a;
    --line: #e2e6ea;
    --bg: #f6f7f9;
    --card: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
          Helvetica, Arial, sans-serif;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 22px 60px; }}
  header.report {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 22px 24px;
    margin-bottom: 20px;
  }}
  header.report h1 {{ margin: 0 0 4px; font-size: 22px; letter-spacing: -0.01em; }}
  header.report .pid {{ color: var(--muted); font-size: 13px; }}
  .meta {{
    display: flex; flex-wrap: wrap; gap: 18px 32px; margin-top: 16px;
    border-top: 1px solid var(--line); padding-top: 14px;
  }}
  .meta div span {{ display: block; }}
  .meta .k {{ color: var(--muted); font-size: 11px; text-transform: uppercase;
              letter-spacing: 0.04em; }}
  .meta .v {{ font-size: 14px; font-weight: 600; }}
  .summary {{
    display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 22px;
  }}
  .chip {{
    flex: 1 1 0; min-width: 120px; background: var(--card);
    border: 1px solid var(--line); border-left-width: 4px;
    border-radius: 10px; padding: 14px 16px;
  }}
  .chip-count {{ font-size: 28px; font-weight: 700; line-height: 1; }}
  .chip-label {{ color: var(--muted); font-size: 12px; margin-top: 6px;
    text-transform: uppercase; letter-spacing: 0.04em; }}
  .card {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 12px; overflow: hidden;
  }}
  .card h2 {{ margin: 0; padding: 16px 20px; font-size: 15px;
    border-bottom: 1px solid var(--line); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead th {{
    text-align: left; color: var(--muted); font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.04em;
    padding: 10px 12px; border-bottom: 1px solid var(--line); white-space: nowrap;
  }}
  tbody td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr.problem {{ background: #fff8f1; }}
  tbody tr.problem td:first-child {{ box-shadow: inset 3px 0 0 #ef6c00; }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
  .num {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
  .center {{ text-align: center; }}
  .sub {{ display: block; color: var(--muted); font-size: 12px; }}
  .na {{ color: #b6bdc4; }}
  .notes {{ max-width: 240px; color: #444; }}
  .badge {{
    display: inline-block; color: #fff; font-weight: 700; font-size: 11px;
    letter-spacing: 0.03em; padding: 3px 9px; border-radius: 999px; white-space: nowrap;
  }}
  .approx {{
    display: inline-block; background: #fdecd8; color: #8a4b00;
    font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 6px;
  }}
  footer.scope {{
    margin-top: 24px; color: var(--muted); font-size: 12px; line-height: 1.6;
    border-top: 1px solid var(--line); padding-top: 16px;
  }}
  footer.scope strong {{ color: var(--ink); }}
</style>
</head>
<body>
<div class="wrap">
  <header class="report">
    <h1>{project_name}</h1>
    <div class="pid">As-Built Elevation Verification &mdash; project
      <span class="mono">{project_id}</span></div>
    <div class="meta">
      <div><span class="k">Generated</span><span class="v">{generated_at}</span></div>
      <div><span class="k">Engine</span><span class="v">{engine_version}</span></div>
      <div><span class="k">Units</span><span class="v">{units_label}</span></div>
      <div><span class="k">Shots in capture</span><span class="v">{n_shots}</span></div>
    </div>
  </header>

  <section class="summary">
    {chips}
  </section>

  <section class="card">
    <h2>Per-device verdicts</h2>
    <table>
      <thead>
        <tr>
          <th>Device</th>
          <th>Family / Type</th>
          <th>Verdict</th>
          <th class="num">Conf.</th>
          <th class="num">&Delta; Position</th>
          <th class="num">&Delta; Height</th>
          <th class="num">&Delta; Orient.</th>
          <th class="center">Approx.</th>
          <th class="center">ID conf.</th>
          <th>Matched shot</th>
          <th>Notes</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </section>

  <footer class="scope">
    <strong>Scope &amp; honesty (v1).</strong>
    This report verifies presence, gross position, mounting height, orientation, and obvious
    device-type mismatch. It does <strong>not</strong> claim sub-inch metrology, does not see
    behind walls (cable, backboxes), and does not automatically resolve exact SKU identity &mdash;
    device identity is human-confirmed. Each capture is a single viewpoint, so occluded or
    protruding devices may be missed or their geometry derived approximately (rows marked
    <span class="approx">approx.</span>). Deltas without a metric LiDAR datum are best-effort.
    Treat flagged items as candidates for a hands-on check, not as final adjudication.
  </footer>
</div>
</body>
</html>
"""

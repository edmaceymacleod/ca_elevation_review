"""PDF report renderer -- the primary issuable client deliverable.

Builds the verdict report as a paginated PDF using ReportLab (pure Python, no
system libraries, so it works headlessly and on CI). ReportLab is an optional
extra: importing this module without it raises :class:`MissingPdfBackend` with
install guidance, and the renderer dispatch falls back to HTML.

Layout mirrors the HTML report: title + project meta, a colour-coded summary
band, a per-device verdict table (problems sorted to the top, tinted), and a
"scope & honesty" footer stating v1 limitations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import CapturePackage, SpecManifest, VerdictReport


class MissingPdfBackend(RuntimeError):
    """Raised when PDF rendering is requested but ReportLab is not installed."""


# Verdict -> (label, RGB hex) used for badges and row tints.
_VERDICT_STYLE = {
    "pass": ("PASS", "#1a7f37"),
    "flag": ("FLAG", "#bf8700"),
    "absent": ("ABSENT", "#cf222e"),
    "type_mismatch": ("TYPE", "#8250df"),
}
# Order problems first, pass last.
_VERDICT_ORDER = {"flag": 0, "absent": 1, "type_mismatch": 2, "pass": 3}


def _require_reportlab():
    try:
        import reportlab  # noqa: F401
    except Exception as exc:  # pragma: no cover - exercised via fallback test
        raise MissingPdfBackend(
            "PDF output requires the optional 'reportlab' backend. Install it with: "
            'pip install "ca-elevation-engine[report]" (or: pip install reportlab)'
        ) from exc


def _unit_suffix(units: str | None) -> str:
    return {"feet": "ft", "meters": "m"}.get(units or "", "")


def _fmt_delta(value, suffix: str) -> str:
    if value is None:
        return "—"  # em dash
    return f"{value:.3f}{suffix}"


def render_pdf(
    report: VerdictReport,
    manifest: SpecManifest,
    capture: CapturePackage,
    out_path: str,
) -> str:
    """Render ``report`` to a PDF at ``out_path``. Returns the path written."""
    _require_reportlab()

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import LETTER, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    units = report.units or manifest.project.units
    suffix = _unit_suffix(units)

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "H1",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=2,
        textColor=colors.HexColor("#0d1117"),
    )
    sub = ParagraphStyle(
        "Sub", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#57606a")
    )
    meta = ParagraphStyle(
        "Meta", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#57606a")
    )
    cell = ParagraphStyle(
        "Cell", parent=styles["Normal"], fontSize=8, leading=10, alignment=TA_LEFT
    )
    foot = ParagraphStyle(
        "Foot",
        parent=styles["Normal"],
        fontSize=7.5,
        textColor=colors.HexColor("#57606a"),
        leading=10,
    )

    story: list = []
    story.append(Paragraph(_esc(manifest.project.name), h1))
    story.append(
        Paragraph(
            f"As-Built Elevation Verification &mdash; project "
            f"<font face='Courier'>{_esc(report.project_id)}</font>",
            sub,
        )
    )
    meta_bits = []
    if report.generated_at:
        meta_bits.append(f"Generated: {_esc(report.generated_at)}")
    if report.engine_version:
        meta_bits.append(f"Engine: {_esc(report.engine_version)}")
    if units:
        meta_bits.append(f"Units: {_esc(units)}")
    meta_bits.append(f"Shots: {len(capture.shots)}")
    story.append(Spacer(1, 4))
    story.append(Paragraph("&nbsp;&nbsp;|&nbsp;&nbsp;".join(meta_bits), meta))
    story.append(Spacer(1, 12))

    # --- Summary band ----------------------------------------------------- #
    s = report.summary
    summary_data = [
        ["Total", "Pass", "Flag", "Absent", "Type mismatch"],
        [
            str(s["total"]),
            str(s["pass"]),
            str(s["flag"]),
            str(s["absent"]),
            str(s["type_mismatch"]),
        ],
    ]
    summary_tbl = Table(summary_data, colWidths=[1.4 * inch] * 5, hAlign="LEFT")
    summary_tbl.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#57606a")),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 15),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f6f8fa")),
                ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor("#1a7f37")),
                ("TEXTCOLOR", (2, 1), (2, 1), colors.HexColor("#bf8700")),
                ("TEXTCOLOR", (3, 1), (3, 1), colors.HexColor("#cf222e")),
                ("TEXTCOLOR", (4, 1), (4, 1), colors.HexColor("#8250df")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d7de")),
            ]
        )
    )
    story.append(summary_tbl)
    story.append(Spacer(1, 16))

    # --- Device table ----------------------------------------------------- #
    header = [
        "Device",
        "Family / Type",
        "Verdict",
        "Conf",
        "Δ pos",
        "Δ height",
        "Δ orient",
        "Shot",
        "Notes",
    ]
    rows = [header]
    ordered = sorted(
        report.device_results, key=lambda r: (_VERDICT_ORDER.get(r.verdict.value, 9), r.device_id)
    )
    tint_rows: list[tuple[int, str]] = []
    for i, r in enumerate(ordered, start=1):
        label, hexcol = _VERDICT_STYLE.get(r.verdict.value, (r.verdict.value.upper(), "#57606a"))
        fam_type = " / ".join(x for x in (r.family, r.type) if x) or "—"
        approx = " *" if r.approximate else ""
        rows.append(
            [
                Paragraph(_esc(r.device_id), cell),
                Paragraph(_esc(fam_type), cell),
                Paragraph(f"<b><font color='{hexcol}'>{label}</font></b>", cell),
                Paragraph(f"{r.confidence:.0%}", cell),
                Paragraph(_fmt_delta(r.deltas.position, suffix) + approx, cell),
                Paragraph(_fmt_delta(r.deltas.mounting_height, suffix), cell),
                Paragraph(
                    "—" if r.deltas.orientation is None else f"{r.deltas.orientation:.1f}°",
                    cell,
                ),
                Paragraph(_esc(r.matched_shot_id or "—"), cell),
                Paragraph(_esc("; ".join(r.notes)) if r.notes else "—", cell),
            ]
        )
        if r.verdict.value != "pass":
            tint_rows.append((i, hexcol))

    col_widths = [
        0.9 * inch,
        1.5 * inch,
        0.7 * inch,
        0.5 * inch,
        0.75 * inch,
        0.8 * inch,
        0.75 * inch,
        0.6 * inch,
        2.6 * inch,
    ]
    tbl = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d1117")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d7de")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for idx, _hex in tint_rows:
        style.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#fff8f0")))
    tbl.setStyle(TableStyle(style))
    story.append(tbl)

    story.append(Spacer(1, 14))
    story.append(
        Paragraph(
            "<b>Scope &amp; honesty (v1).</b> This report verifies presence, gross position, "
            "mounting height, and orientation, with opportunistic device-type checks. It does "
            "<b>not</b> claim sub-inch metrology, does not resolve exact SKU identity (left for "
            "human confirmation), and cannot observe anything behind the wall (cable, backboxes). "
            "Rows marked &ldquo;*&rdquo; are approximate (no metric depth or a protruding/occluded "
            "device). A single viewpoint carries occlusion shadows.",
            foot,
        )
    )

    doc = SimpleDocTemplate(
        out_path,
        pagesize=landscape(LETTER),
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.5 * inch,
        title=f"{manifest.project.name} -- As-Built Elevation Verification",
    )
    doc.build(story)
    return out_path


def _esc(text) -> str:
    """Escape text for ReportLab's mini-HTML paragraph markup."""
    s = "" if text is None else str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

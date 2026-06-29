# Implementation Spec — Harden + Polish the Issuable Report Renderers

Work item: **reports**. Status: build-ready (hardened after adversarial review).
Scope: `engine/src/ca_elevation_engine/report/{pdf,html,json_report,text_summary}.py`
plus `engine/tests/test_pdf.py` and `engine/tests/test_report.py`, and one new private module
`engine/src/ca_elevation_engine/report/_ordering.py`.

This spec is environment-correct for the container: no Revit, no iOS, no .NET, no macOS. Everything is
exercisable headlessly on Linux. The core engine deps stay light; `reportlab` remains the only optional
backend touched (the existing `[report]` extra), and `jinja2` stays unused (HTML is stdlib-only).

---

## 0. Context and current state (verified against the code, do not re-derive)

The report sub-package turns a `VerdictReport` into an issuable deliverable. Public entry point
`report.render_report(report, manifest, capture, out_path, fmt)` (`report/__init__.py:63`) dispatches to:

- `pdf.render_pdf` — primary deliverable, ReportLab (optional `[report]` extra). Raises
  `MissingPdfBackend` when ReportLab is absent; the pipeline catches that and falls back to HTML.
- `html.render_html` — self-contained single-file HTML, **stdlib-only** string templating.
- `json_report.render_json` — pretty JSON of `report.to_dict()`.
- `text_summary.summarize` — plaintext digest for the CLI.

Confirmed facts (verified against the source on branch `claude/codebase-capabilities-0s8u05`):

- `VerdictReport.summary` (`models.py:567`) is a property returning
  `{"total","pass","flag","absent","type_mismatch"}` ints. It does **not** contain coverage info.
- A device is a **coverage gap** iff `DeviceResult.matched_shot_id is None` (it was never matched to
  any shot). This is the only coverage signal available; there is no schema field for coverage, so
  coverage must be **derived in the renderer**, NOT added to the schema/models.
- HTML backfills missing `family`/`type` from the manifest via `_device_label` (`html.py:114`). **PDF
  does NOT** — `pdf.render_pdf` uses `r.family`/`r.type` directly (`pdf.py:181`). This is an
  inconsistency to fix.
- Both HTML and PDF already sort problems-first then by `device_id`. Sort ranks live in **three** private
  places: `html._VERDICT_SORT_RANK` (`html.py:54`), `pdf._VERDICT_ORDER` (`pdf.py:33`),
  `text_summary._PROBLEM_ORDER` (`text_summary.py:18`). They agree today but are duplicated.
- The **HTML table has 11 columns** (Device, Family/Type, Verdict, Conf, ΔPosition, ΔHeight, ΔOrient,
  Approx, ID conf, Matched shot, Notes — see `html.py:329-341`).
  The **PDF table has 9 columns** (Device, Family/Type, Verdict, Conf, Δ pos, Δ height, Δ orient, Shot,
  Notes — see `pdf.py:163-173`; PDF has no Approx column and no ID-conf column; "approximate" is a `" *"`
  suffix on the Δ pos cell). This asymmetry is real and load-bearing for the grouping work (§3.4, §4.3).
- reportlab 5.0.0 and jinja2 3.1.6 are installed in this environment; `[report]` extra pins
  `reportlab>=4.0`, `jinja2>=3.1`. jinja2 is **not** imported by any renderer and must stay unused.
- Existing tests: `test_report.py` (HTML/JSON/text) and `test_pdf.py` (`pytest.importorskip("reportlab")`).
  All pass. Engine suite is 79 pass under `pytest -m "not heavy"`.
- The PDF test asserts only coarse properties (`%PDF` header, length, `%%EOF`); there is **no golden
  PDF**. PDFs embed a `/CreationDate` and a random `/ID`, so they are not byte-deterministic by default.
- Test fixture truth (`test_report.py:111-160`), used heavily by the test plan:
  - DEV-001 = PASS, `matched_shot_id="SHOT-A"` (matched).
  - DEV-002 = FLAG, `matched_shot_id="SHOT-A"` (matched), `approximate=True`, notes include an XSS string.
  - DEV-003 = ABSENT, `matched_shot_id=None` (**the only coverage gap**).
  - DEV-004 = TYPE_MISMATCH, `matched_shot_id="SHOT-A"` (matched).
  - So under the display order FLAG < ABSENT < TYPE_MISMATCH < PASS the ordered device ids are
    `["DEV-002","DEV-003","DEV-004","DEV-001"]`, and the **only** coverage-gap id is `DEV-003`.
- Call path for fault injection (verified): `render_report` → `render_pdf` wrapper in `__init__.py`
  (does a fresh `from .pdf import render_pdf as _render_pdf` **on every call**, `__init__.py:58`) →
  `pdf.render_pdf` → `pdf._require_reportlab()` is called first (`pdf.py:63`), then a second direct
  `import reportlab.*` inside the function body (`pdf.py:65-76`).
- Pipeline fallback (`pipeline.py:94-108`): on `report_format != "json"`, builds `report.<fmt>`; on
  `MissingPdfBackend` it appends a warning (`"{exc} Falling back to HTML report."`), writes `report.html`,
  and sets `written["html"]`.

---

## 1. Goals (what "hardened + polished" means here)

1. **Grouped device tables by status** — render devices in explicit status groups
   (Flag → Absent → Type mismatch → Pass), each with its own subheading, instead of one flat
   problems-first table. Applies to HTML and PDF.
2. **Summary header with a coverage line** — the existing counts (chips in HTML, band in PDF) get a
   **coverage line** ("N of M devices matched to a shot") added in both renderers.
3. **Coverage-gap callout** — a distinct, visible callout listing devices with no `matched_shot_id`
   (never observed), so an unmatched device is not buried mid-table. HTML and PDF.
4. **Deterministic ordering** — a single shared ordering/grouping helper consumed by HTML, PDF, and
   text so the three never drift. Stable secondary key = `device_id`.
5. **Graceful degradation** — verify + harden the existing `MissingPdfBackend` → HTML fallback; add a
   direct unit test that simulates ReportLab being absent **by monkeypatching
   `pdf._require_reportlab`** (not by uninstalling reportlab), so it runs headlessly in CI where
   ReportLab IS installed.
6. **Determinism for testing** — HTML/JSON/text output is **byte-stable** for fixed input. PDF is
   **content-deterministic** (no wall-clock; assertions are on extracted/uncompressed content, never on
   bytes). PDF is explicitly **not** byte-deterministic and we do not try to make it so (see §5).
7. **Empty-report robustness** — zero devices renders a valid document in both HTML and PDF, with no
   coverage-gap callout and no exception.

Non-goals are in §10.

---

## 2. Shared ordering + grouping helper (new module)

Create `engine/src/ca_elevation_engine/report/_ordering.py` (underscore = private to the sub-package;
not re-exported in `__init__.__all__`).

This module owns the **rank/order and grouping/coverage derivation only**. It also owns a *canonical*
label map, but renderers are free to keep their own presentation labels (the PDF deliberately uses a
short `"TYPE"` to fit a narrow column — see §4.1 and the MINOR 3 resolution). The shared invariant the
anti-drift test enforces is **the ranking order**, not label string equality.

```python
"""Shared, deterministic verdict ordering + grouping for all renderers.

Single source of truth so HTML, PDF, and text never drift on ordering. Pure
stdlib, no heavy deps.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..models import Verdict

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import DeviceResult, VerdictReport

# Display order: problems first (by severity), pass last. THE one ranking.
VERDICT_DISPLAY_ORDER: tuple[Verdict, ...] = (
    Verdict.FLAG, Verdict.ABSENT, Verdict.TYPE_MISMATCH, Verdict.PASS,
)
_RANK = {v: i for i, v in enumerate(VERDICT_DISPLAY_ORDER)}

# Canonical full-length human labels. Renderers MAY style/abbreviate (e.g. PDF
# uses a shorter "TYPE"); this map is the long form used by HTML/text.
VERDICT_LABELS: dict[Verdict, str] = {
    Verdict.PASS: "PASS",
    Verdict.FLAG: "FLAG",
    Verdict.ABSENT: "ABSENT",
    Verdict.TYPE_MISMATCH: "TYPE MISMATCH",
}

PROBLEM_VERDICTS = frozenset({Verdict.FLAG, Verdict.ABSENT, Verdict.TYPE_MISMATCH})


@dataclass(frozen=True)
class Coverage:
    """Derived, render-time-only coverage stats. Never serialized."""
    total: int
    matched: int
    unmatched: int
    unmatched_ids: list[str]


def sort_key(r: "DeviceResult") -> tuple[int, str]:
    return (_RANK.get(r.verdict, 99), r.device_id)


def ordered_results(report: "VerdictReport") -> list["DeviceResult"]:
    """All device results, problems-first then by device_id (stable)."""
    return sorted(report.device_results, key=sort_key)


def grouped_results(report: "VerdictReport") -> list[tuple[Verdict, list["DeviceResult"]]]:
    """Results bucketed by verdict in display order. Empty groups omitted.
    Within a group, sorted by device_id."""
    buckets: dict[Verdict, list[DeviceResult]] = {v: [] for v in VERDICT_DISPLAY_ORDER}
    for r in report.device_results:
        buckets.setdefault(r.verdict, []).append(r)
    out: list[tuple[Verdict, list[DeviceResult]]] = []
    for v in VERDICT_DISPLAY_ORDER:
        rs = sorted(buckets.get(v, []), key=lambda r: r.device_id)
        if rs:
            out.append((v, rs))
    return out


def coverage(report: "VerdictReport") -> Coverage:
    """A device is 'matched' iff matched_shot_id is set. unmatched_ids sorted."""
    total = len(report.device_results)
    unmatched = sorted(
        r.device_id for r in report.device_results if not r.matched_shot_id
    )
    return Coverage(
        total=total,
        matched=total - len(unmatched),
        unmatched=len(unmatched),
        unmatched_ids=unmatched,
    )
```

Notes:
- `coverage()` returns a frozen `Coverage` dataclass (resolves MINOR 1 — a `dict[str, int | list[str]]`
  return would invite mypy union-in-f-string friction; a typed result keeps callers clean: `cov.matched`,
  `cov.unmatched_ids`). It is internal only; **no schema change, never on the wire.**
- `grouped_results` uses `setdefault` so an (impossible-per-enum) unknown verdict still renders rather
  than being dropped — fail-open for display. It is the buckets dict (pre-seeded in display order) that
  preserves group ordering.
- `VERDICT_DISPLAY_ORDER` is the **single ranking source**. The anti-drift test (§6.7) asserts every
  renderer ranks off this; it does **not** assert label-string equality (see MINOR 3 resolution).

---

## 3. HTML renderer changes (`report/html.py`)

3.1 **Replace local ordering/problem constants** with imports from `_ordering`:
- Delete `_VERDICT_SORT_RANK` and `_PROBLEM_VERDICTS`. Keep `_VERDICT_COLORS` local (color is a
  presentation concern). The label map `_VERDICT_LABELS` may be deleted and its lookups in
  `_verdict_badge` rewritten to use `_ordering.VERDICT_LABELS[Verdict(value)]` with a fallback to
  `value.upper()` — HTML uses the full-length labels, so sourcing from `_ordering` is drift-safe here.
- `_sorted_results` → delegate to `_ordering.ordered_results` (keep `_sorted_results` as a thin wrapper
  to minimize churn / preserve callers).
- `_PROBLEM_VERDICTS` references (used for the `problem`/`ok` row class) switch to
  `_ordering.PROBLEM_VERDICTS`. Note `_ordering.PROBLEM_VERDICTS` holds `Verdict` enum members, so test
  membership with `r.verdict in _ordering.PROBLEM_VERDICTS` (enum), not `r.verdict.value`.

3.2 **Grouped device table.** Replace the single flat list of `<tr>` rows with **status groups**. Build
the entire `{rows}` string in Python (as today). For each `(verdict, results)` from
`_ordering.grouped_results(report)`:
- Emit a full-width group header row built **in code** (single braces — it is part of the dynamic
  `{rows}` slot, NOT added to the static `_DOCUMENT` template; see MINOR 5 resolution):
  `<tr class="group {verdict_value}"><td colspan="11"><span class="badge" style="background:{color}">{LABEL}</span> {N}</td></tr>`
  — colspan is **11** for the HTML table (verified column count). Use the canonical label from
  `_ordering.VERDICT_LABELS` and the color from `_VERDICT_COLORS`.
- Then the device rows for that group (existing per-row HTML, unchanged markup per row).
- Row CSS class stays `problem`/`ok` so existing tint styling applies. The first-column accent bar
  (`tbody tr.problem td:first-child`) is retained.
- Empty groups are omitted (handled by `grouped_results`).
- Empty report: keep the existing "No devices in this report." colspan row (colspan 11).

3.3 **Coverage line in the header meta block.** Add a 5th `.meta` field after "Shots in capture":
`<div><span class="k">Coverage</span><span class="v">{matched} / {total} matched</span></div>`,
computed from `_ordering.coverage(report)`. Add the format placeholders to `_DOCUMENT` (e.g.
`{coverage_matched}`, `{coverage_total}`) and pass them in the `.format(...)` call. Both values are ints.

3.4 **Coverage-gap callout.** Between the `<section class="summary">` chips and the device `card`, when
`cov.unmatched > 0`, emit a callout. Build it in code and inject through a new `{coverage_gap}`
placeholder (empty string when `cov.unmatched == 0`):
```
<section class="coverage-gap">
  <h2>Coverage gap &mdash; {N} device(s) not observed in any shot</h2>
  <p class="ids mono">{escaped, comma-separated unmatched_ids}</p>
  <p>These devices were not matched to any capture shot; their verdicts rest on
     absence, not measurement.</p>
</section>
```
- Every dynamic value escaped via the existing `_esc` (in particular each id in `unmatched_ids`).
- Add CSS to `_DOCUMENT` for `.coverage-gap` (amber left border `4px solid #ef6c00`, light amber
  background e.g. `#fff8f1`, rounded, padded) and for `tr.group td` (bold, subtle background, the badge
  inline). **All literal CSS braces in `_DOCUMENT` must stay doubled** — but the callout *content* and
  the group-header rows are built in `render_html` with normal single-brace f-strings/`.format`, so no
  doubling applies to them (this is the explicit MINOR 5 clarification: dynamic rows ≠ static template).

3.5 Keep the function signature of `render_html(report, manifest, capture)` unchanged. All new content
is additive. Output must remain a single self-contained file (no external assets).

---

## 4. PDF renderer changes (`report/pdf.py`)

4.1 **Share the *ranking* with `_ordering`; keep PDF's short presentation labels local.** Delete
`pdf._VERDICT_ORDER`. Drive ordering/grouping from `_ordering.grouped_results`. **Keep
`pdf._VERDICT_STYLE`** as-is, including its short `"TYPE"` label for `type_mismatch`: the Verdict column
is narrow and a full `"TYPE MISMATCH"` would wrap badly. This is a deliberate presentation choice,
parallel to colors being local. Consequently:
- §4.1 does **not** source label text from `_ordering.VERDICT_LABELS`. (Resolves the MINOR 3 conflict:
  the draft both "sourced labels from `_ordering`" and "kept short PDF labels" — incompatible. We share
  *order/rank only*; presentation labels stay local.)
- The anti-drift test (§6.7) therefore asserts only that the **ranking** is shared, not label equality.

4.2 **Backfill family/type from manifest** (parity with HTML). Add a private
`_device_label(result, manifest) -> str` mirroring `html._device_label` semantics (prefer the result's
`family`/`type`, fall back to the manifest device with matching `id`), returning the `"Family / Type"`
string (or `"—"`). Replace the current `fam_type = " / ".join(...)` (`pdf.py:181`) with this. Fixes the
gap where a result lacking `family`/`type` shows `—` even when the manifest has them.

4.3 **Grouped device table.** Replace the single flat table with grouping by status, keeping ONE
`Table` for deterministic layout:
- For each group from `_ordering.grouped_results(report)`, before its device rows insert a **group
  header row**: a list with the label/count in the first cell and empty strings for the remaining cells,
  styled via a `SPAN` across the whole row.
- The PDF table is **9 columns**. Apply the span as `('SPAN', (0, row), (-1, row))` — **always use `-1`,
  never a literal column count** (resolves MINOR 2; do not copy HTML's "11" into the PDF). Likewise apply
  the group-header background tint and a bold font to `(0, row)`/`(-1, row)`.
- Track the running row index while appending header rows and device rows so the per-row styles
  (group-header tint+bold, and the existing problem-row tint `#fff8f0`) land on the right indices.
- Keep `repeatRows=1` for the column header. Group header rows will not repeat across page breaks;
  acceptable for v1.
- Empty report: render a single-row table "No devices in this report." spanning all columns
  (`('SPAN',(0,1),(-1,1))`), so ReportLab does not choke on a header-only table.

4.4 **Coverage line in the summary band + callout.** Using `cov = _ordering.coverage(report)`:
- Add a `Paragraph` under the summary band:
  `f"Coverage: {cov.matched} of {cov.total} devices matched to a shot"` (style `meta`).
- When `cov.unmatched > 0`, add a tinted callout `Paragraph` (amber, e.g. an inline
  `<font color='#8a4b00'>` on a light background paragraph) listing the unmatched device ids (each via
  `_esc`) with the same one-sentence explanation as HTML, placed **before** the device table.

4.5 **Determinism hardening (content-deterministic, not byte-deterministic).**
- The renderer **must never call `datetime.now()`** (it already does not — it uses
  `report.generated_at`, which the pipeline sets deterministically). Keep it that way.
- The renderer **must NOT mutate `reportlab.rl_config`** (`invariant`, `pageCompression`, etc.). Those
  are process-global module state read at canvas construction; flipping them inside `render_pdf` would
  (a) leak into every other PDF built in the same process/session, (b) be order-dependent and not
  thread-safe, and (c) make output depend on hidden global state — the opposite of determinism. This is
  the MAJOR 2 resolution: **drop the draft's "set invariant in the renderer" option entirely.**
- reportlab 5.0.0 has **no** `SimpleDocTemplate(invariant=...)` parameter (verified: not in the
  signature; `**kwargs` are forwarded to the canvas and `invariant` is the `rl_config` global, not a
  canvas kwarg). So there is no in-renderer knob that zeroes `/CreationDate`+`/ID` without touching the
  global. **Therefore the PDF is content-deterministic only.**
- Author/subject metadata: you MAY pass static `author="CA Elevation Review"` and
  `subject="As-Built Elevation Verification"` to `SimpleDocTemplate` for nicer document properties.
  **Do not present this as a determinism measure** — author/subject are static strings and were never
  the non-determinism source (that is `/CreationDate` and the random `/ID`). This is the MAJOR 3
  resolution: separate "nice metadata (optional)" from "determinism (we accept content-determinism)."
- Net determinism story: same input → same *content* (text, ordering, tables). Bytes will differ run to
  run (CreationDate/ID). Tests assert on extracted/uncompressed content, never on bytes (§5, §6.5).

4.6 Keep `render_pdf(report, manifest, capture, out_path)` signature unchanged; keep `MissingPdfBackend`
and `_require_reportlab()` exactly as-is (the fallback contract depends on them).

---

## 5. Determinism policy (testing)

- **HTML / JSON / text**: byte-deterministic for fixed input. The new grouped/coverage content uses
  only sorted, derived data (`_ordering`), so this holds. Tests may assert on full substrings and
  relative ordering, and on `render_html(x) == render_html(x)`.
- **PDF**: **content-deterministic, not byte-deterministic.** Tests MUST NOT compare PDF bytes to a
  golden file, and MUST NOT assert that two successive builds produce identical bytes — that assertion
  is false without mutating the reportlab global (which §4.5 forbids), so it would be flaky, and forcing
  it true would pollute global state. This is the MAJOR 2 / MINOR 4 resolution: **the byte-equality
  assertion and the "capability probe + conditional skip" are removed as goals.** Instead, tests extract
  content by building with **compression disabled in the test body** (set+restore
  `reportlab.rl_config.pageCompression = 0` around the build — a test-local toggle, never in the
  renderer) and assert substrings against the uncompressed stream bytes (§6.5).

---

## 6. Test plan (all headless, `@pytest.mark.unit`, no heavy/native deps)

Extend `engine/tests/test_report.py` (HTML/JSON/text + ordering helper + fallback) and
`engine/tests/test_pdf.py` (PDF, guarded by `importorskip("reportlab")` except the missing-backend
test). Reuse the existing in-memory `_report()/_manifest()/_capture()` builders. Fixture facts are in
§0; the **only** coverage-gap id is **DEV-003**.

### 6.1 `_ordering` unit tests (new, in test_report.py)
- `test_ordered_results_problems_first`: assert
  `[r.device_id for r in ordered_results(_report())] == ["DEV-002","DEV-003","DEV-004","DEV-001"]`
  (FLAG < ABSENT < TYPE_MISMATCH < PASS, then by id).
- `test_grouped_results_buckets_and_omits_empty`: build a report with only PASS + FLAG devices; assert
  the returned verdicts are exactly `[Verdict.FLAG, Verdict.PASS]` (ABSENT/TYPE omitted), each list
  sorted by id.
- `test_coverage_counts_unmatched`: `cov = coverage(_report())`; assert
  `cov.total == 4`, `cov.matched == 3`, `cov.unmatched == 1`, `cov.unmatched_ids == ["DEV-003"]`.
- `test_coverage_empty_report`: zero devices → `total==0, matched==0, unmatched==0, unmatched_ids==[]`.

### 6.2 HTML grouped + coverage (new)
- `test_html_groups_by_status`: render; assert a group subheader for each present status (substring
  `class="group flag"`, `class="group absent"`, `class="group type_mismatch"`, `class="group pass"`)
  and that group order is Flag-before-Pass:
  `html.index('class="group flag"') < html.index('class="group pass"')`.
- `test_html_coverage_line`: assert `"3 / 4 matched"` present in the header meta block.
- `test_html_coverage_gap_callout`: assert the `coverage-gap` section is present, lists `DEV-003`, the
  explanatory sentence ("rest on absence, not measurement") is present, and **DEV-002 does NOT appear in
  the callout** (it is matched).
- `test_html_no_coverage_gap_when_all_matched`: build a report where every device has a
  `matched_shot_id`; assert the substring `coverage-gap` is **absent**.
- `test_html_empty_report_valid`: zero-device report → output still starts with `<!DOCTYPE html>`,
  contains "No devices", contains no `coverage-gap`, raises nothing.
- Keep/adjust existing `test_html_orders_problems_first` (still holds: DEV-002 before DEV-001, etc.).
- Keep the existing escape test; additionally assert no raw `<script>` appears anywhere in the output
  (the XSS note on DEV-002 must remain escaped through the new grouped markup).

### 6.3 JSON / text unchanged-contract (regression)
- Existing `test_render_json_round_trip` must still pass byte-for-byte (the JSON path is untouched).
- `test_text_uses_shared_ordering` (optional, cheap): assert the text summary's non-pass listing order
  equals `[r.device_id for r in ordered_results(report) if r.verdict in _ordering.PROBLEM_VERDICTS]`.

### 6.4 Determinism (HTML)
- `test_html_deterministic`: `render_html(...) == render_html(...)` for the same input (byte-equal).

### 6.5 PDF content extraction (new, in test_pdf.py, behind `importorskip("reportlab")`)
Strategy: disable stream compression **in the test only** so device ids and labels appear literally in
the PDF bytes. Use a fixture/context manager that sets `reportlab.rl_config.pageCompression = 0` and
restores the prior value in a `finally` (verified: with compression off, `b"DEV-002"`, `b"Coverage"`,
etc. appear literally; this is fully headless). Do **not** add pypdf/pdfplumber.
- `test_pdf_groups_and_coverage`: with compression off, assert each status label appears (e.g. `b"FLAG"`,
  `b"ABSENT"`, `b"TYPE"`, `b"PASS"`), the coverage line (`b"Coverage"`) appears, and the unmatched id
  `b"DEV-003"` appears. Assert DEV-002 appears as a row but is **not** in the coverage callout (assert
  `b"DEV-003"` is present and that the matched ids are not listed alongside the "not observed" sentence).
  Keep this assertion simple and robust to layout; the strong coverage-callout-content assertions live in
  the HTML tests where extraction is exact.
- `test_pdf_backfills_family_type_from_manifest`: construct a `DeviceResult` with `family=None,
  type=None` whose `device_id` matches a manifest device that has a family/type; render with compression
  off; assert the manifest family/type string appears in the PDF bytes. Guards the §4.2 fix.
- `test_pdf_empty_report`: zero-device report renders a valid `%PDF` … `%%EOF` without raising.
- Keep the existing 4 PDF tests passing (valid PDF, helper, supported-formats, escapes malicious notes).

### 6.6 Graceful degradation (new; runs even though reportlab IS installed)
Canonical fault injection (the **one** approach — resolves MAJOR 4; drop the draft's `sys.modules`/
`builtins.__import__` suggestions, which are fragile because reportlab is already imported and cached):
> **`monkeypatch.setattr(ca_elevation_engine.report.pdf, "_require_reportlab", _raise)`** where `_raise`
> is an explicitly-defined function that raises `MissingPdfBackend("simulated absence")`.

- `test_render_pdf_missing_backend_raises` (place in test_report.py, or above the `importorskip` line in
  test_pdf.py, so it runs unconditionally): apply the patch, assert `pdf.render_pdf(...)` raises
  `MissingPdfBackend`. (The patch fires because `pdf.render_pdf` calls `_require_reportlab()` first,
  `pdf.py:63`.)
- `test_pipeline_falls_back_to_html_without_reportlab` (in test_report.py or an existing pipeline test
  file — extend rather than duplicate if one exists): apply the same patch, run
  `run_pipeline(..., out_dir=tmp, report_format="pdf")`, then assert: `result.written` has an `"html"`
  key, that html file exists and starts with `<!DOCTYPE html>`, and `result.warnings` contains a message
  mentioning the HTML fallback. The patch propagates through the real path
  (`render_report` → `__init__.render_pdf` wrapper → `pdf.render_pdf` → patched `_require_reportlab`
  raises → pipeline catches `MissingPdfBackend`), exercising the genuine fallback headlessly without
  uninstalling reportlab.
- Documentation note (MINOR, no action required in code): `_require_reportlab`'s `except` branch carries
  `# pragma: no cover - exercised via fallback test`. The patch-based test does **not** cover that
  real-import-failure branch (it replaces the function), so the pragma is what keeps coverage honest;
  leave the pragma in place. This is acceptable: the real-absence path cannot be exercised in an
  environment where reportlab is installed.

### 6.7 Anti-drift guard (ranking only — not labels)
- `test_renderers_share_ranking`: assert `_ordering.VERDICT_DISPLAY_ORDER` is exactly
  `(Verdict.FLAG, Verdict.ABSENT, Verdict.TYPE_MISMATCH, Verdict.PASS)`, and assert that the duplicated
  rank dicts were removed in favor of `_ordering` (`not hasattr(pdf, "_VERDICT_ORDER")` and
  `not hasattr(html, "_VERDICT_SORT_RANK")`). Do **NOT** assert PDF label equals
  `_ordering.VERDICT_LABELS` (PDF's `"TYPE"` ≠ `"TYPE MISMATCH"` by design — MINOR 3). Optionally assert
  `ordered_results(report)` and the device-id order implied by `pdf`/`html` grouped output agree, which
  is the behavior we actually care about.

### Running
```bash
cd engine && python -m pytest tests/test_report.py tests/test_pdf.py -q          # focused
cd engine && python -m pytest -q -m "not heavy"                                  # full gate (stays green; was 79)
ruff check engine && ruff format --check engine && (cd engine && mypy)
```
All new tests are `@pytest.mark.unit`. PDF content tests stay behind `importorskip("reportlab")`; the
missing-backend simulation (§6.6) runs unconditionally.

---

## 7. Graceful degradation under this environment (Linux / no Revit / no heavy)

- **No new runtime deps.** Only `reportlab` (the existing `[report]` extra) is touched; `jinja2` stays
  unused (HTML stays stdlib-only). No open3d/pye57/opencv, no pypdf/pdfplumber, no lxml.
- **ReportLab absent** → `MissingPdfBackend` → pipeline HTML fallback. Verified by §6.6 tests via the
  `_require_reportlab` monkeypatch, so the degraded path is covered without uninstalling reportlab in CI.
- **HTML/JSON/text** require only the stdlib and run on every CI matrix row.
- **No Revit / no device**: all tests build in-memory dataclasses or reuse the existing synthetic
  fixtures, exactly like the current tests. Nothing here touches floorplan image files or device IO.
- Determinism (HTML/JSON/text byte-stable; PDF content-stable) keeps the suite stable across the
  py3.10/3.11/3.12 matrix.

---

## 8. Files to add / change (summary)

| File | Change |
|---|---|
| `engine/src/ca_elevation_engine/report/_ordering.py` | **NEW**: shared ranking/grouping + typed `Coverage` derivation (§2). |
| `engine/src/ca_elevation_engine/report/html.py` | Use `_ordering` (ranking + full labels + `PROBLEM_VERDICTS`); grouped tbody by status (colspan 11); coverage meta line; coverage-gap callout via a new `{coverage_gap}` slot; CSS for `.coverage-gap` + `tr.group`; empty-report path retained (§3). |
| `engine/src/ca_elevation_engine/report/pdf.py` | Use `_ordering` ranking/grouping; keep local short labels + colors; manifest family/type backfill via new `_device_label`; grouped single-table via `('SPAN',(0,row),(-1,row))` header rows (9 cols); coverage line + callout; determinism: no wall-clock, no `rl_config` mutation, optional static author/subject; empty-report path (§4). |
| `engine/src/ca_elevation_engine/report/json_report.py` | **No change** (kept byte-stable). |
| `engine/src/ca_elevation_engine/report/text_summary.py` | Delegate ranking to `_ordering` (replace `_PROBLEM_ORDER` rank with `_ordering.sort_key`/`PROBLEM_VERDICTS`); output text unchanged. Removes the third duplicate rank source. |
| `engine/src/ca_elevation_engine/report/__init__.py` | No public API change; `_ordering` stays private (not in `__all__`). |
| `engine/tests/test_report.py` | Add `_ordering`, HTML grouped/coverage/empty/determinism, fallback (§6.6), anti-drift (ranking) tests (§6.1–6.4, 6.6, 6.7). |
| `engine/tests/test_pdf.py` | Add grouped/coverage/backfill/empty content probes (compression-off in test body); keep `importorskip` guard; add unconditional missing-backend test (§6.5, 6.6). |

---

## 9. Behavioral contracts / invariants (must hold after change)

1. `render_report(..., fmt="json")` output is **identical** to before (no schema/models change).
2. `VerdictReport` schema + `models.py` are **unchanged**; coverage is derived (`_ordering.Coverage`),
   never serialized.
3. `render_html` and `render_pdf` signatures unchanged; `MissingPdfBackend` and the pipeline fallback
   path unchanged in behavior.
4. Display **ranking** is FLAG → ABSENT → TYPE_MISMATCH → PASS, secondary by `device_id`, identical
   across HTML/PDF/text (enforced by `_ordering` + §6.7). Presentation *labels* may differ per renderer
   (PDF short "TYPE"); only the ranking is a shared contract.
5. All dynamic text is escaped (HTML via `_esc`/`html.escape`; PDF via `pdf._esc`), including the new
   coverage-gap id lists and group-header labels.
6. Empty report (0 devices) renders a valid HTML and a valid PDF, no exception, no coverage-gap callout.
7. PDF is content-deterministic (no wall-clock, no `rl_config` mutation in the renderer); it is NOT
   byte-deterministic and no test asserts byte stability for PDF.
8. Full engine suite stays green (`pytest -m "not heavy"`), ruff clean, mypy clean.

---

## 10. Non-goals (explicit)

- **No schema/model changes.** Do not add a `coverage` block to `verdict_report.schema.json` or
  `VerdictReport`. Coverage is a render-time derivation only.
- **No new dependencies** beyond the already-declared `[report]` extra. No pypdf/pdfplumber, no jinja2
  activation, no heavy backends.
- **No byte-golden PDF fixture and no PDF byte-equality assertion.** PDFs are content-deterministic only.
- **No `rl_config` mutation inside the renderer.** Compression toggling, if used, is confined to the
  test body with set+restore.
- **No CLI flag changes** and no new output formats (still pdf/html/json + text summary).
- **No images/floorplans/thumbnails** embedded in reports (would pull image deps).
- **No Revit/iOS/.NET work**; nothing requiring those toolchains.
- **No charts/graphs** or interactive HTML (single static self-contained file only).
- **No per-level / per-floorplan sectioning** beyond status grouping (possible future work; not now).

---

## Adversarial review resolutions

The adversarial review (`spec-reports.review.md`) raised 0 blockers, 4 majors, and 5 minors. Resolution
of each:

- **MAJOR 1 — §6.5 fixture claim wrong (DEV-002 named as a coverage gap).** Verified against
  `test_report.py:123-140`: DEV-002 is FLAG with `matched_shot_id="SHOT-A"` (matched); the only
  unmatched device is **DEV-003**. §0 now pins the fixture truth, and §6.2/§6.5 assert the coverage
  callout lists **only DEV-003** and that DEV-002 appears as a row but **not** in the callout. The bogus
  "DEV-002 is unmatched" assertion is removed.
- **MAJOR 2 — §4.5 endorsed mutating reportlab process-global state.** Removed entirely. §4.5 now
  forbids the renderer from touching `rl_config` (`invariant`/`pageCompression`); declares the PDF
  **content-deterministic, not byte-deterministic**; and §5/§6.5 drop the "two successive builds are
  byte-equal" assertion and the "capability probe + conditional skip." Compression-off is confined to
  the test body with set+restore.
- **MAJOR 3 — §4.5 conflated author/subject with the determinism source.** §4.5 now separates "optional
  nice metadata (static author/subject)" from "determinism (we do not zero `/CreationDate`/`/ID`)" and
  explicitly states author/subject do not affect byte stability.
- **MAJOR 4 — §6.6 fallback fault-injection under-specified/partly wrong.** §6.6 now prescribes the
  single canonical patch: `monkeypatch.setattr(pdf, "_require_reportlab", <fn that raises
  MissingPdfBackend>)`. The fragile `sys.modules["reportlab"]=None` / `builtins.__import__` suggestions
  are deleted. The verified call-path note (§0) confirms the patch fires and propagates through the
  pipeline. The pragma/coverage caveat is documented (real-absence branch stays `# pragma: no cover`).
- **MINOR 1 — `coverage()` dict union type invites mypy friction.** Adopted: `coverage()` now returns a
  frozen `Coverage` dataclass (typed fields), keeping callers clean. Still internal, no schema change.
- **MINOR 2 — HTML=11 vs PDF=9 column asymmetry.** Called out explicitly in §0 and §4.3: PDF uses
  `('SPAN',(0,row),(-1,row))` with `-1`, never a literal count; HTML group headers use `colspan=11`.
- **MINOR 3 — anti-drift asserting PDF "TYPE" == "TYPE MISMATCH".** Resolved via the reviewer's
  recommended option (a): renderers **share ranking only**; PDF keeps its short presentation labels.
  §4.1 no longer sources PDF labels from `_ordering`; §6.7 asserts shared **ranking** (and removal of the
  duplicate rank dicts), not label equality.
- **MINOR 4 — byte-equality "capability probe + conditional skip" is dead complexity.** Cut from §5 and
  §6.5 (folds into MAJOR 2). Only HTML/JSON/text byte-determinism and PDF content-determinism remain.
- **MINOR 5 — group-header `colspan` inside the `str.format` template.** Clarified in §3.2/§3.4: group
  headers and the coverage-gap callout are built in `render_html` as normal single-brace strings and
  injected via the dynamic `{rows}`/`{coverage_gap}` slots; only literal CSS braces in the static
  `_DOCUMENT` stay doubled.

Where we diverged from the reviewer: nowhere materially. On MINOR 3 we adopted the reviewer's
explicitly recommended option (a). On MINOR 1 we took the optional suggestion because it is cheap and
removes mypy noise across multiple call sites.

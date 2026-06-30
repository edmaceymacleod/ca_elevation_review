# CA Elevation Review — Code Review Synthesis

## Executive Summary

This review consolidates 32 verifier-confirmed findings (29 distinct issues after de-duplication) across the engine, pyRevit extension, iOS app, Revit add-in, and CI configuration. The dominant theme is **silent failure**: non-finite (NaN/Inf) values flow unguarded from ingest through matching, verdict, and report serialization; multiple error paths swallow exceptions or skip data without surfacing a signal, so corrupt or incomplete inputs can be reported as clean PASS verdicts or complete reviews. A secondary theme is **lexical-only path containment** — three independent symlink-escape gaps (engine, iOS, Revit add-in) that defeat security controls which explicitly claim to reject symlinks. No critical-severity issues were confirmed; the most serious are two HIGH findings (silent capture data loss on iOS, NaN observation admitted into matching).

## Counts

### By Severity
| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 2 |
| Medium | 9 |
| Low | 18 |
| **Total (distinct)** | **29** |

### By Category
| Category | Count |
|----------|-------|
| silent-error | 9 |
| data-integrity | 8 |
| security | 5 |
| correctness | 6 |
| other | 1 |

### By Component
| Component | Count |
|-----------|-------|
| engine | 7 |
| pyrevit | 6 |
| ios | 9 |
| revit | 4 |
| ci-config | 2 |

### De-duplications applied
- **pointcloud.py:55 symlink escape** — two findings ("Point-cloud path guard does not resolve symlinks" + "Bundle-relative cloud path can escape via a symlink") merged into one (E-7).
- **EngineRunner.cs stdout/stderr drain** — two findings (EngineRunner.cs:270-286 + EngineRunner.cs:195) merged into one (R-4); same root cause (async readers not drained before reading buffers).

---

## HIGH

### H-1 · Capture shot-staging errors swallowed in release builds (silent data loss)
- **File:** `ios-app/Sources/CaElevationApp/Views/PlacePinView.swift:186`
- **Category:** silent-error
- **Problem:** When `CaptureExporter.makeShot` throws (disk full, write failure, path-escape rejection), the catch block calls only `assertionFailure` and returns. `assertionFailure` is a no-op in release builds, so `session.add(shot)` and `dismiss()` are skipped with no user-visible error.
- **Why it matters:** The operator believes the wall was captured when no shot was recorded — silent loss of a capture that may be hard or impossible to retake. The inline TODO confirms this is known-unhandled, and it violates the project's logging rule (no `Log.capture.error`).
- **Fix:** Surface the error via an alert/`@State` error string (mirror `CoverageView.exportError`), log via `Log.capture.error`, and do not dismiss on failure.

### H-2 · NaN observation distance silently admitted through match gate
- **File:** `engine/src/ca_elevation_engine/compare.py:160-161`
- **Category:** silent-error
- **Problem:** The association gate uses `if d > gate: continue`. `distance3()` returns NaN for NaN coordinates, and `NaN > gate` is False, so a NaN-distance candidate is not skipped and can be selected as `best` (accepted unconditionally as the first `best_key`). NaN reaches here because `json.loads` accepts the bare `NaN` token and `jsonschema` does not reject NaN for `type: number`.
- **Why it matters:** A corrupt observation is silently admitted; the NaN `position_delta` then propagates to the verdict stage, where `NaN > tol` is False and the device falls through to PASS — a silent PASS on a compliance review.
- **Fix:** `if not math.isfinite(d) or d > gate: continue`, and validate finiteness of observation coordinates at ingest.

---

## MEDIUM

### M-1 · NaN deltas silently classified as PASS (no breach detected)
- **File:** `engine/src/ca_elevation_engine/verdict.py:96-111`
- **Category:** silent-error
- **Problem:** Breach detection uses `delta > tol`. A NaN position/height/orientation delta makes every comparison False, so no breach is recorded and the device falls through to `Verdict.PASS` (line 118), even though geometry is undefined. `_match_confidence` returns a clean-looking 0.3 for a NaN delta, masking it further.
- **Why it matters:** An unverifiable (corrupt/degenerate) device is silently passed with a normal-looking confidence — a wrong-verdict / data-integrity hazard. (Downstream sibling of H-2.)
- **Fix:** Guard each delta with `math.isfinite()` before comparison; treat non-finite as a breach (force FLAG/ABSENT with a note). Reject NaN/Inf at ingest (`json.loads(parse_constant=...)` / validate `isfinite` on every `Point3`).

### M-2 · Verdict report can serialize NaN/Infinity as invalid JSON
- **File:** `engine/src/ca_elevation_engine/report/json_report.py:18-20`
- **Category:** data-integrity
- **Problem:** `render_json` calls `json.dumps` without `allow_nan=False`, so non-finite deltas emit the bare tokens `NaN`/`Infinity`/`-Infinity`, which are invalid JSON. The schema `number` type does not reject these, so `ingest.validate_report` does not catch it.
- **Why it matters:** The engine writes spec-invalid JSON after reporting success, violating its own documented wire contract and breaking any standards-compliant downstream consumer.
- **Fix:** `json.dumps(..., allow_nan=False)` so emission raises on non-finite values; assert `math.isfinite` on all numeric report fields before writing.

### M-3 · Override applied but marker not stamped when Comments is read-only (broken idempotency)
- **File:** `pyrevit-extension/CaElevationReview.extension/lib/ca_elevation_revit/revit_writeback.py:172`
- **Category:** data-integrity
- **Problem:** The colour override is applied and `applied` incremented independently of `_stamp_marker`, which returns silently when the Comments param is None or `IsReadOnly`. The idempotency contract depends on the sentinel marker; if a device can't be stamped, a later re-import that drops it won't clear its stale colour.
- **Why it matters:** Families with locked/read-only Comments get permanently mis-coloured on the next run, reported as a clean apply with no signal. The `applied` count and marker set diverge silently.
- **Fix:** Have `_stamp_marker` return a bool; if an override is applied but not stamped, log a warning / count an "unmarked" tally surfaced to the user.

### M-4 · Corrupt verdict_report.json silently swallowed to None while run reported success
- **File:** `pyrevit-extension/CaElevationReview.extension/lib/ca_elevation_revit/engine_runner.py:215`
- **Category:** silent-error
- **Problem:** On `JSONDecodeError`/`OSError`, `report=None` is set with no log and no error flag. `EngineRun.ok`/`status` derive purely from the subprocess return code, so exit-0-with-corrupt-report yields `ok=True, status=success, report=None`.
- **Why it matters:** A corrupt report after exit 0 produces a misleading "Applied 0 verdicts" success — an empty review indistinguishable from a normal passing run, with the read failure fully silent.
- **Fix:** `logger.exception` the failure, record a `report_error` field on `EngineRun`, and treat "exit 0 but report unreadable/absent" as not-ok.

### M-5 · Per-element extraction failures silently drop real devices from the manifest
- **File:** `pyrevit-extension/CaElevationReview.extension/lib/ca_elevation_revit/revit_extract.py:276`
- **Category:** data-integrity
- **Problem:** `extract_devices` wraps each element in a broad `except Exception` that increments an `errors` counter, logs to INFO, and continues. A device that raises mid-extraction (transient API error, NaN coordinate → `ManifestBuildError`) is omitted entirely. There is no error threshold or abort.
- **Why it matters:** The engine only verdicts devices in the manifest, so a silently-dropped installed device never gets an absent/flag verdict — a wrong/incomplete review masquerading as complete, with the only signal an INFO log the field user won't see.
- **Fix:** Surface the non-zero `errors` count to the caller (return it, or raise when errors exceed a threshold) so the user is warned the review is incomplete.

### M-6 · Writeback marker is model-wide but overrides are per-view (unclearable stale colours)
- **File:** `pyrevit-extension/CaElevationReview.extension/lib/ca_elevation_revit/revit_writeback.py:60-141`
- **Category:** data-integrity
- **Problem:** The ownership marker is stamped on `ALL_MODEL_INSTANCE_COMMENTS` (model-wide), but the colour is applied per-view via `SetElementOverrides`, and clearing only walks the active view (`FilteredElementCollector(doc, view.Id)`). If run #1 is in View A and run #2 in View B: run #2 strips the model-wide marker and clears View B only, leaving View A's colours stranded and, with the marker gone, unclearable forever.
- **Why it matters:** Stale verdict colours silently persist and become unclearable, so the visual record no longer reflects the latest report — directly contradicting the documented idempotency guarantee.
- **Fix:** Record the applied view id alongside the marker and clear in that specific view; or enumerate all applicable views when clearing; or make the marker view-scoped. Only strip the marker once the override is actually reset everywhere applied.

### M-7 · Un-exportable level hard-fails the whole bundle with a misleading "unknown level_id"
- **File:** `pyrevit-extension/CaElevationReview.extension/lib/ca_elevation_revit/revit_export.py:73-181`
- **Category:** correctness
- **Problem:** `level_lookup` (gating extraction) is built from ALL chosen levels, but `export_floorplans` silently skips individual levels (missing plan view, degenerate crop box, no PNG, any per-level exception → `print; skipped += 1; continue`). Devices on a skipped level still pass the extract gate, then `build_manifest` derives `level_ids` only from successfully-exported floorplans and raises `ManifestBuildError('... references unknown level_id ...')`.
- **Why it matters:** One un-exportable level aborts the entire export with a confusing message far from its cause, defeating the stated "one bad level must not abort the rest" goal.
- **Fix:** After `export_floorplans` returns, restrict `level_lookup`/extraction to level_ids that actually produced a `FloorplanExport` (drop+warn for failed levels), or surface skipped levels to the user before building the manifest.

### M-8 · encodeDepth emits an empty depth map while declaring full HxW size
- **File:** `ios-app/Sources/CaElevationApp/Capture/ARCaptureSession.swift:185`
- **Category:** data-integrity
- **Problem:** `out` is filled only inside `if let base = CVPixelBufferGetBaseAddress(...)`. If the base address is nil (lock failure), `out` stays empty, yet the function still returns `(out, (height, width))`. `snapshot()` sets `depthFloat32 = <empty>` with `depthSize = [H, W]`; `BundleIO.writeCapturePackage` validation only checks the file exists, not that it contains H·W·4 bytes.
- **Why it matters:** The engine reads a depth map far smaller than its declared size — corrupt metric depth and a wrong elevation verdict, with no error anywhere.
- **Fix:** Make `encodeDepth` fail loudly (return optional / throw) when the base address is nil or the format isn't `kCVPixelFormatType_DepthFloat32`; have `snapshot()` treat nil depth as "no depth" (both fields nil). Optionally assert `out.count == width*height*4`.

### M-9 · Engine stdout/stderr can be truncated: async readers not drained after exit
- **File:** `revit-addin/src/CaElevationReview.Addin/Engine/EngineRunner.cs:195` (also `:270-286`)
- **Category:** correctness *(de-dup of two findings)*
- **Problem:** `WaitForExitAsync` completes on the `Process.Exited` event only; it does not wait for the async `OutputDataReceived`/`ErrorDataReceived` pumps (started by `BeginOutputReadLine`/`BeginErrorReadLine`) to flush their end-of-stream sentinels. The code then immediately reads `stdout.ToString()`/`stderr.ToString()`. Per .NET docs, the blocking `WaitForExit()` is required to drain async readers.
- **Why it matters:** The tail of engine output can be silently dropped. `StdErr` is the only diagnostic surfaced on failure (`ImportCapturesCommand` builds the message from `Truncate(runResult.StdErr,...)`), so a failing run can show an empty or half-written error reason; trailing progress lines can also be lost.
- **Fix:** After `WaitForExitAsync` returns (and not cancelled), call the synchronous parameterless `process.WaitForExit()` to force the drain before reading buffers; or track both streams' null-data EOF sentinels via TaskCompletionSources and await them alongside `Exited`.

---

## LOW

### L-1 · ICP refinement swallows all exceptions including programming errors
- **File:** `engine/src/ca_elevation_engine/register.py:186-188`
- **Category:** silent-error
- **Problem:** `refine_registration` wraps `_icp_refine` in a bare `except Exception`, appending a note and returning the coarse registration. This also swallows real bugs (TypeError/AttributeError/numpy shape errors), turning them into a quiet "kept coarse registration" note in per-device notes, never surfaced as a warning or non-zero exit.
- **Why it matters:** A systematically broken ICP path would silently never refine, with no failing signal — particularly since `_icp_refine` is untested.
- **Fix:** Narrow the catch to expected o3d/numeric failure types, and/or emit a pipeline-level warning when refinement was expected but failed.

### L-2 · Schema validation can be disabled wholesale via `--no-validate`
- **File:** `engine/src/ca_elevation_engine/cli.py:54,73` and `pipeline.py:58-61`
- **Category:** silent-error
- **Problem:** `--no-validate` skips `_validate` for both manifest and capture. Schema-only constraints (`exclusiveMinimum` on intrinsics, 0..1 confidence bounds, enums, `additionalProperties: false`, NaN coordinates) then flow straight into registration/verdict. No warning is emitted; output is indistinguishable from a validated run.
- **Why it matters:** A skipped-validation run carries no provenance — a silent-error/traceability gap for a compliance tool (mitigated by being an explicit opt-in; default is fail-closed).
- **Fix:** Emit a prominent `result.warnings` entry when `validate=False` (printed by the CLI); still run cheap finite-value / cross-field checks even when JSON-schema validation is skipped.

### L-3 · Silent fallback to all same-level shots when frustum coverage is empty
- **File:** `engine/src/ca_elevation_engine/compare.py:118-129`
- **Category:** silent-error
- **Problem:** When frustum `covering` is empty, the filter `if covering and shot.id not in covering` is skipped, so observations from ALL same-level shots become candidates. A device that no shot framed can still match (within `gate`) and produce a normal PASS/FLAG; the verdict never records the frustum bypass (`_match_confidence` ignores coverage).
- **Why it matters:** A confident geometric verdict for a device no shot actually framed, indistinguishable from a properly-framed match.
- **Fix:** When the fallback admits an out-of-frustum candidate, lower confidence and/or mark the match so the verdict reflects the bypass.

### L-4 · Point-cloud path guard does not resolve symlinks (bundle escape)
- **File:** `engine/src/ca_elevation_engine/pointcloud.py:55`
- **Category:** security *(de-dup of two findings)*
- **Problem:** `resolve_cloud_path` normalizes the joined path lexically with `os.path.normpath` and resolves only `base`. The containment check (`base not in cand.parents`) defends against `..` traversal but not symlinks. A symlink physically inside the bundle pointing outside passes the check; the loader then follows it. The docstring falsely claims it "resolves symlinks on bundle_dir," and `PointCloudPathError` is treated as a security control. Threat model: bundles arrive from attacker-influenced OneDrive/File-Provider sync.
- **Why it matters:** Permits reading arbitrary on-disk files (parseable as E57/PLY/PCD/XYZ/PTS) into ICP, plus a file-existence/parse-error oracle on arbitrary paths via `reg.notes`. Impact bounded — no readback channel, requires `--bundle-dir` against an untrusted bundle.
- **Fix:** Resolve the candidate's real path before the containment check: `cand = (base / rel_path).resolve()`, then verify `cand == base or base in cand.parents`. Keep the absolute-path rejection.

### L-5 · E57 ingest silently reads only scan 0, dropping all other scans
- **File:** `engine/src/ca_elevation_engine/pointcloud.py:115`
- **Category:** data-integrity
- **Problem:** `_load_e57` reads only `read_scan(0)` and returns those points as the entire cloud. Additional scans in a multi-scan E57 are silently discarded; the report note presents the partial cloud as complete ("N pts"). Path is PROVISIONAL with no CI coverage.
- **Why it matters:** ICP runs against a partial cloud with no warning, degrading registration quality and inflating apparent confidence.
- **Fix:** Iterate `range(e57.scan_count)` and vstack all scans (common coordinate frame), or at minimum raise/note when `scan_count > 1`.

### L-6 · Missing/empty verdict string maps to sentinel colour (conflates malformed report with enum drift)
- **File:** `pyrevit-extension/CaElevationReview.extension/lib/ca_elevation_revit/writeback.py:88`
- **Category:** correctness
- **Problem:** `result.get("verdict", "")` yields `""` for a device result missing the field; `color_for_verdict("")` KeyErrors → fail-soft to magenta and logs "unmapped verdict ... MAPPING may be stale." A structurally malformed report is rendered identically to a genuine engine-enum drift, and the device is still counted as a successful override.
- **Why it matters:** Observability: the operator sees magenta and misattributes it to "tool out of date" rather than a corrupt per-device record. (The module already handles missing `device_id` with a distinct branch — this asymmetry is the inconsistency.)
- **Fix:** Detect missing/empty verdict explicitly (mirror the `device_id` branch) with its own log message, while still applying the sentinel.

### L-7 · `_require_positive_int` rejects integer-valued floats, contradicting its own comment and the schema
- **File:** `pyrevit-extension/CaElevationReview.extension/lib/ca_elevation_revit/manifest_builder.py:81-87`
- **Category:** correctness
- **Problem:** The docstring states integer-valued floats (e.g. `1000.0`) must NOT be rejected (schema accepts them for `type: integer`; the builder must be a subset of the schema). The code does the opposite: `not isinstance(value, int)` rejects any float. No live impact today (the only caller passes Python ints), but it violates the stated subset invariant.
- **Why it matters:** Would reject a schema-valid manifest if `width_px`/`height_px` ever arrive as floats; self-contradiction between documented invariant and implementation.
- **Fix:** Accept integer-valued floats: reject bool, require `isinstance(value, (int, float))` and finite, `value > 0`, and `float(value).is_integer()` — or correct the docstring if strictness is intended.

### L-8 · CVPixelBufferLockBaseAddress return value ignored in encodeDepth
- **File:** `ios-app/Sources/CaElevationApp/Capture/ARCaptureSession.swift:180`
- **Category:** silent-error
- **Problem:** The `CVReturn` from `CVPixelBufferLockBaseAddress` is discarded; a failed lock proceeds to read, and the unconditional `defer { ...Unlock... }` unlocks a buffer that may never have been locked. Combined with M-8, a failed lock silently yields an empty depth buffer.
- **Why it matters:** Contributes to silent malformed depth (see M-8); violates the project's logging rule. Rare on real hardware since the buffer is freshly system-vended.
- **Fix:** `guard CVPixelBufferLockBaseAddress(...) == kCVReturnSuccess else { return nil }` (make the function optional) and schedule the unlock only when the lock succeeded.

### L-9 · restoreSavedRoot silently ignores bookmark-refresh failure
- **File:** `ios-app/Sources/CaElevationApp/Library/ProjectLibrary.swift:79`
- **Category:** silent-error
- **Problem:** On a stale bookmark, the refresh save uses `try?`, discarding any error and logging nowhere. The stale bookmark is left in place, so a future failed resolve has no breadcrumb. Inconsistent with the same file's `Log.bundle.warning`/`error` usage elsewhere.
- **Why it matters:** Minor and self-healing (the next launch drops to choose-folder), but a deliberately swallowed throw with no diagnostic on the persistence path.
- **Fix:** `do/catch` and log via `Log.bundle.error`.

### L-10 · Pin model-XY preview shown for singular affines (isValid checks count only)
- **File:** `ios-app/Sources/CaElevationApp/Views/PlacePinView.swift:135`
- **Category:** correctness
- **Problem:** `currentAffine` gates only on `Affine.isValid` (`coefficients.count == 6`), which doesn't reject a singular affine. The view shows a "Model XY" readout via `affine.modelXY` for an affine the engine's inverse (`pixel(fromModelX:)`) would reject (`|det| < 1e-12`). A `determinant` property already exists and is tested but is unused here.
- **Why it matters:** Display-trust only — the operator sees a confident-looking but meaningless coordinate. Exported pin pixel is unaffected (engine recomputes).
- **Fix:** Also require `abs(affine.determinant) >= 1e-12` before showing the readout; otherwise show a "plan not georeferenced" note.

### L-11 · iOS path-traversal guard does not resolve symlinks (bundle/library escape)
- **File:** `ios-app/Sources/CaElevationKit/BundleIO.swift:211-231`
- **Category:** security
- **Problem:** `resolvedURL(forRelativePath:in:)` — the single boundary for untrusted relative paths from synced manifests/capture JSON, reused by write-back — rejects absolute paths and literal `..`, then containment-checks with `standardizedFileURL`, which normalizes only lexically and does NOT resolve symlinks. A symlink component pointing outside passes the check. The doc-comment falsely claims the result is "guaranteed to be inside `directory`."
- **Why it matters:** For reads, can exfiltrate in-sandbox files into the UI/thumbnail; for write-back, can write outside the intended Exports subfolder. Bounded by the iOS sandbox and app-generated write paths; uncertain whether sync preserves symlinks.
- **Fix:** Apply `resolvingSymlinksInPath()` to both base and resolved before comparison (resolving the existing parent for non-existent write targets), or verify the realpath remains contained after resolution.

### L-12 · Unbounded recursive JSON decode of untrusted manifest metadata can crash the app
- **File:** `ios-app/Sources/CaElevationKit/JSONValue.swift:23-43`
- **Category:** security
- **Problem:** `JSONValue.init(from:)` recurses per array/object level with no depth limit. It decodes `Device.metadata` from `manifest.json` files in a synced folder during the auto-running library scan. A deeply nested metadata blob overflows the stack — a hardware trap, NOT a catchable throw, so the per-bundle `do/catch` in `scan` cannot skip it.
- **Why it matters:** A single malformed/crafted bundle crashes the whole project picker on open — denial of availability with no graceful per-bundle skip. Bounded by being a single-user tool reading the owner's folder; crash only (no RCE/data exposure).
- **Fix:** Thread a depth counter through `init(from:)` (via `decoder.userInfo`) and throw `DecodingError` past a sane max (64-128) so the over-nested decode fails per-bundle (then skipped) instead of trapping. Optionally cap raw manifest `Data` size.

### L-13 · Heading delegate hop loses captured-frame value via async Task ordering
- **File:** `ios-app/Sources/CaElevationApp/Heading/CompassHeading.swift:86`
- **Category:** correctness
- **Problem:** `didUpdateHeading` is nonisolated and publishes via an unstructured `Task { @MainActor in self.trueHeadingDegrees = heading }`. `snapshot()` reads `headingDegrees` synchronously; if it fires before the queued Task runs, it stamps a stale or nil heading despite a fresh reading.
- **Why it matters:** Advisory data only (user confirms the arrow on PlacePinView), bounded by `headingFilter = 1`; can silently pre-fill a wrong arrow.
- **Fix:** Assign on `MainActor.assumeIsolated` (defined ordering), or stamp the heading from the live `CLHeading` at snapshot time.

### L-14 · Write-back .forReplacing coordinates the destination but not the source read
- **File:** `ios-app/Sources/CaElevationApp/Library/WriteBack.swift:128`
- **Category:** data-integrity
- **Problem:** `copyPackageToLibrary` recursively `copyItem`s the local export directory under write coordination on the destination only. Because `exportPackage` and `makeShot` share one session export directory and write-back runs on a detached task, a shot staged after copy starts races the recursive copy, risking a partial-tree copy.
- **Why it matters:** Latent only — current flow exports once; worst case is an unreferenced orphan media file the desktop add-in ignores. No required data lost.
- **Fix:** Snapshot/freeze the session export directory before write-back, or copy from an immutable per-export subdirectory.

### L-15 · Coverage "captured" status only matches tagged elevations
- **File:** `ios-app/Sources/CaElevationApp/Views/CoverageView.swift:131`
- **Category:** correctness
- **Problem:** `capturedIds = Set(shotsForLevel.compactMap { $0.elevationId })` drops nil-elevation shots, while devices bucket into `"(untagged)"`. Since `compactMap` strips nils, `capturedIds` can never contain `"(untagged)"`, so untagged devices stay unchecked forever even after being shot. Untagged shots are a supported flow (PlacePinView offers "None").
- **Why it matters:** The coverage checklist falsely shows untagged walls as still-needed, causing re-shoots or a false belief of incomplete coverage. Export is unaffected.
- **Fix:** If any shot on the level has nil `elevationId`, treat the `"(untagged)"` bucket as captured (include a sentinel for nil), or surface untagged shot count separately.

### L-16 · Process.Start return value ignored; Process IDisposable leaks
- **File:** `revit-addin/src/CaElevationReview.Addin/Commands/GenerateReportCommand.cs:117-123`
- **Category:** silent-error
- **Problem:** `Process.Start(psi)` returns an `IDisposable` Process that is discarded and never disposed, leaking the handle each time a report is opened (until finalization).
- **Why it matters:** Trivial code-hygiene defect — delayed-cleanup-until-GC on an infrequent user action, not a permanent leak.
- **Fix:** `using var p = Process.Start(psi);` or `Process.Start(psi)?.Dispose();` (disposing does not terminate the launched app).

### L-17 · Report artifact containment check does not resolve symlinks despite claiming to
- **File:** `revit-addin/src/CaElevationReview.Addin/Commands/GenerateReportCommand.cs:100`
- **Category:** security
- **Problem:** `IsAllowedReportArtifact()` (gate before `Process.Start` with `UseShellExecute=true`) canonicalizes via `Path.GetFullPath` and requires `StartsWith(dirPrefix)`. `Path.GetFullPath` normalizes only `.`/`..`/casing — it does NOT resolve symlinks/junctions/hardlinks. The XML doc claims it "Rejects path-traversal / symlink-style escapes," which is false. A symlink named `report.html` (allow-listed ext) inside the output dir passes and is handed to the OS shell handler.
- **Why it matters:** Doc/behavior mismatch; the symlink case is genuinely unblocked. Bounded — requires write access to the engine output dir (where one could already replace the file directly), and the target is rendered not executed.
- **Fix:** Resolve the real target before the check via `new FileInfo(path).ResolveLinkTarget(true)?.FullName` (net8) / `GetFinalPathNameByHandle` (net48), compare resolved real paths; at minimum correct the doc comment.

### L-18 · Gitleaks allowlist suppresses any line containing a "pose" JSON key
- **File:** `.gitleaks.toml:26-30`
- **Category:** security
- **Problem:** The allowlist regexes use `regexTarget = "line"` with the broad pattern `"pose"\s*:`. Any line repo-wide containing a `"pose":` key has ALL gitleaks findings on it suppressed — a secret co-located on such a line is silently ignored. The fixtures/schemas these patterns target are already path-allowlisted, so the line regexes are redundant yet apply globally.
- **Why it matters:** Weakens a defense-in-depth secret scanner; a real secret sharing a `"pose":` line would be masked.
- **Fix:** Prefer path-scoped allowlisting (already present) over content-key line suppression, or anchor the regexes to the numeric-array value shape; drop the broad `"pose":` line allow.

### L-19 · CI workflow has no top-level timeout-minutes
- **File:** `.github/workflows/ci.yml:28-273`
- **Category:** other
- **Problem:** No job in `ci.yml` or `auto-merge.yml` sets `timeout-minutes`, defaulting to GitHub's 360 minutes. A hung step (brew install, xcodebuild, network-stalled pip) can occupy expensive macOS/Windows runners for up to 6 hours. The `concurrency` block only cancels superseded runs, not a single wedged job.
- **Why it matters:** Resource/availability hygiene — runaway jobs burn runner minutes. No correctness impact; cheap to bound.
- **Fix:** Add `timeout-minutes` per job (e.g. 15-20 for ubuntu, 30 for macOS/Windows builds).

---

## Cross-Cutting Notes

- **Non-finite (NaN/Inf) propagation chain (H-2, M-1, M-2, plus L-2):** A single ingest-side fix — parsing JSON with `parse_constant` disabled and validating `isfinite` on every coordinate at the boundary — closes H-2, M-1, and M-2 at the source. Defense-in-depth guards at each comparison/serialization site are still warranted.
- **Lexical-only path containment (L-4, L-11, L-17):** Three independent symlink-escape gaps across engine (Python), iOS (Swift), and Revit add-in (C#), each with a comment/doc overclaiming symlink rejection. All share the same fix shape: resolve the real on-disk path before the containment check.
- **Async/event-ordering silent truncation (M-9, L-13):** Reading buffered output before the async producer has drained — same anti-pattern in the C# engine runner and the Swift heading delegate.

The relevant files are referenced inline by absolute or repo-relative path with each finding above.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;
using CaElevationReview.Addin.Commands.Support;

namespace CaElevationReview.Addin.Commands
{
    /// <summary>
    /// "Generate Report" -- step 5 of the desktop flow.
    ///
    /// Opens the issuable report produced by the engine for the most recent run. The
    /// engine emits the structured verdict_report.json; the human-facing report
    /// (PDF/HTML) is rendered alongside it. We locate that artifact and open it with
    /// the OS default handler.
    /// </summary>
    [Transaction(TransactionMode.ReadOnly)]
    [Regeneration(RegenerationOption.Manual)]
    public sealed class GenerateReportCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            try
            {
                string? reportJsonPath = LastRun.ReportPath;
                if (string.IsNullOrEmpty(reportJsonPath) || !File.Exists(reportJsonPath))
                {
                    TaskDialog.Show(
                        "Generate Report",
                        "No report available yet. Run \"Import Captures\" first to produce one.");
                    return Result.Cancelled;
                }

                // The engine writes verdict_report.json and (with the [report] extra) a
                // sibling human-readable report. Prefer HTML, then PDF, then fall back to
                // opening the JSON itself.
                string outDir = Path.GetDirectoryName(reportJsonPath)!;
                string toOpen = ResolveBestReportArtifact(outDir, reportJsonPath);

                // Defence in depth before handing a path to the OS shell handler: only open
                // known report artifact types, and only from inside the engine output dir.
                if (!IsAllowedReportArtifact(toOpen, outDir, out string reason))
                {
                    message = $"Refusing to open report artifact: {reason}";
                    return Result.Failed;
                }

                OpenWithDefaultHandler(toOpen);
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                return Result.Failed;
            }
        }

        /// <summary>
        /// Pure selection logic: pick the most presentable report artifact in the output
        /// directory. Exposed for unit testing (no Revit, no process launch).
        /// </summary>
        public static string ResolveBestReportArtifact(string outDir, string jsonFallback)
        {
            string html = Path.Combine(outDir, "report.html");
            if (File.Exists(html)) return html;

            string pdf = Path.Combine(outDir, "report.pdf");
            if (File.Exists(pdf)) return pdf;

            return jsonFallback;
        }

        /// <summary>Extensions we will hand to the OS default handler. Pure, unit-testable.</summary>
        private static readonly HashSet<string> AllowedExtensions =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".pdf", ".html", ".json" };

        /// <summary>
        /// Gate before shelling out: the artifact must have an allow-listed extension and
        /// must resolve to a file inside <paramref name="allowedDir"/> (the engine output
        /// directory). Rejects path-traversal escapes and unknown types.
        /// <para>
        /// On net8 the real on-disk target is resolved (via
        /// <see cref="FileInfo.ResolveLinkTarget(bool)"/>) before the containment check, so a
        /// symlink/junction inside the output dir that points elsewhere is also rejected. On
        /// net48 that API is unavailable, so only lexical (<c>.</c>/<c>..</c>) traversal is
        /// rejected and reparse points are NOT resolved; the engine output directory is treated
        /// as trusted there.
        /// </para>
        /// Pure (apart from path canonicalisation and link resolution); exposed for unit testing.
        /// </summary>
        public static bool IsAllowedReportArtifact(string path, string allowedDir, out string reason)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                reason = "empty path";
                return false;
            }

            string ext = Path.GetExtension(path);
            if (!AllowedExtensions.Contains(ext))
            {
                reason = $"extension '{ext}' is not in the allow-list (.pdf/.html/.json)";
                return false;
            }

            // Canonicalise both sides and require the artifact to live under the output dir.
            // ResolveRealPath additionally collapses symlinks/junctions to their real target
            // where the framework supports it (net8), so a reparse point planted inside the
            // output dir that escapes it is caught by the containment check below.
            string fullPath = ResolveRealPath(Path.GetFullPath(path));
            string fullDir = ResolveRealPath(Path.GetFullPath(allowedDir));
            string dirPrefix = fullDir.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal)
                ? fullDir
                : fullDir + Path.DirectorySeparatorChar;

            if (!fullPath.StartsWith(dirPrefix, StringComparison.OrdinalIgnoreCase))
            {
                reason = $"path is outside the engine output directory ({fullDir})";
                return false;
            }

            reason = string.Empty;
            return true;
        }

        /// <summary>
        /// Resolve symlinks/junctions to their real on-disk target so the containment check
        /// operates on the true location, not a reparse point that lexically lives under the
        /// output dir. On net8 this follows the final link target; on net48 (where
        /// <c>ResolveLinkTarget</c> does not exist) it returns the input unchanged, leaving the
        /// lexical containment check as the only guard there.
        /// </summary>
        private static string ResolveRealPath(string fullPath)
        {
#if NET6_0_OR_GREATER
            try
            {
                // returnFinalTarget: true walks a chain of links to the ultimate target.
                FileSystemInfo info = File.Exists(fullPath)
                    ? new FileInfo(fullPath)
                    : new DirectoryInfo(fullPath);
                FileSystemInfo? target = info.ResolveLinkTarget(returnFinalTarget: true);
                return target?.FullName ?? fullPath;
            }
            catch (IOException)
            {
                // Broken link / cycle / inaccessible: fall back to the lexical path so the
                // StartsWith containment check still applies.
                return fullPath;
            }
            catch (UnauthorizedAccessException)
            {
                return fullPath;
            }
#else
            return fullPath;
#endif
        }

        private static void OpenWithDefaultHandler(string path)
        {
            // UseShellExecute=true asks the OS to open with the registered handler
            // (browser for .html, viewer for .pdf, editor for .json).
            var psi = new ProcessStartInfo(path) { UseShellExecute = true };

            // Process.Start returns an IDisposable Process; dispose it so the local handle is
            // released promptly rather than waiting on the finalizer. With UseShellExecute=true
            // the OS may reuse an existing handler and return null, hence the null-conditional.
            // Disposing only releases our handle; it does not terminate the launched viewer.
            Process.Start(psi)?.Dispose();
        }
    }
}

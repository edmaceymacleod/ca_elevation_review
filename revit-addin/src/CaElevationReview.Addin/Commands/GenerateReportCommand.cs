using System;
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

        private static void OpenWithDefaultHandler(string path)
        {
            // UseShellExecute=true asks the OS to open with the registered handler
            // (browser for .html, viewer for .pdf, editor for .json).
            var psi = new ProcessStartInfo(path) { UseShellExecute = true };
            Process.Start(psi);
        }
    }
}

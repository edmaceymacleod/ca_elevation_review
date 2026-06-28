using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using CaElevationReview.Addin.Commands.Support;
using CaElevationReview.Addin.Engine;
using CaElevationReview.Addin.Verdict;

namespace CaElevationReview.Addin.Commands
{
    /// <summary>
    /// "Import Captures" -- step 3 of the desktop flow.
    ///
    /// Picks a returned capture package, invokes the CPython engine OUT-OF-PROCESS via
    /// <see cref="EngineRunner"/> (a real System.Diagnostics.Process call to
    /// <c>ca-elevation run ...</c>), shows progress, reads back the verdict report JSON,
    /// and colors devices in the model by verdict.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public sealed class ImportCapturesCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            try
            {
                UIDocument uiDoc = commandData.Application.ActiveUIDocument;
                Document doc = uiDoc.Document;

                // 1. Locate the inputs: the previously-exported manifest and the returned capture.
                string? manifestPath = PromptForExistingFile(
                    "Select the spec_manifest.json from the field bundle",
                    ExportFieldBundleCommand.ManifestFileName);
                if (manifestPath == null) return Result.Cancelled;

                string? capturePath = PromptForExistingFile(
                    "Select the returned capture package", "capture_package.json");
                if (capturePath == null) return Result.Cancelled;

                string outputDir = Path.Combine(
                    Path.GetDirectoryName(capturePath)!, "ca-elevation-out");

                var request = new EngineRunRequest
                {
                    ManifestPath = manifestPath,
                    CapturePath = capturePath,
                    OutputDir = outputDir,
                };

                // 2. Run the engine out-of-process, surfacing progress lines to the user.
                EngineRunResult runResult = RunEngineWithProgress(request);

                if (!runResult.Succeeded)
                {
                    message =
                        $"Engine run failed (exit {runResult.ExitCode}).\n\n" +
                        Truncate(runResult.StdErr, 1500);
                    return Result.Failed;
                }

                VerdictReport report = runResult.Report!;

                // 3. Write verdicts back into the model (override graphics by verdict).
                int colored = WriteBackVerdicts(doc, uiDoc.ActiveView, report);

                // Stash the report path so Generate Report can open the latest result.
                LastRun.ReportPath = runResult.ReportPath;

                TaskDialog.Show(
                    "Import Captures",
                    $"Verification complete.\n\n" +
                    $"Total: {report.Summary.Total}\n" +
                    $"Pass: {report.Summary.Pass}   Flag: {report.Summary.Flag}\n" +
                    $"Absent: {report.Summary.Absent}   Type mismatch: {report.Summary.TypeMismatch}\n\n" +
                    $"Colored {colored} device(s) in the active view.\n" +
                    $"Report: {runResult.ReportPath}");

                return Result.Succeeded;
            }
            catch (EngineNotFoundException ex)
            {
                message =
                    "Could not find the ca-elevation engine.\n" +
                    "Install the engine (pip install ca-elevation-engine) or set the " +
                    $"{EngineLocator.EnvVarName} environment variable / add-in setting.\n\n" + ex.Message;
                return Result.Failed;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                return Result.Failed;
            }
        }

        /// <summary>
        /// Run the engine and surface stdout lines through a Revit progress dialog.
        /// Bridges the async EngineRunner to Revit's synchronous command model.
        /// </summary>
        private static EngineRunResult RunEngineWithProgress(EngineRunRequest request)
        {
            var runner = new EngineRunner();

            // TODO (Revit/WPF): replace this with a real modeless progress window that
            // appends lines from onProgressLine and offers a Cancel that trips the token.
            using var cts = new CancellationTokenSource();

            Action<string> onLine = line =>
            {
                // TODO: pump 'line' into the progress UI. Engine is expected to emit
                // human-readable progress on stdout (ingest -> georeference -> ... -> emit).
                System.Diagnostics.Debug.WriteLine($"[ca-elevation] {line}");
            };

            // Block the command thread on the async run. Acceptable because IExternalCommand
            // is invoked on Revit's UI thread and we want a modal "working" experience.
            return Task.Run(() => runner.RunAsync(request, onLine, cts.Token))
                       .GetAwaiter()
                       .GetResult();
        }

        private static int WriteBackVerdicts(Document doc, View view, VerdictReport report)
        {
            var writeback = new VerdictWriteback();

            using var tx = new Transaction(doc, "CA Elevation Review: verdict write-back");
            tx.Start();
            int colored = writeback.Apply(doc, view, report);
            tx.Commit();

            return colored;
        }

        private static string? PromptForExistingFile(string title, string suggestedName)
        {
            // TODO (Revit): show a FileOpenDialog filtered to JSON / the bundle layout.
            //   var dlg = new FileOpenDialog("JSON files (*.json)|*.json") { Title = title };
            //   if (dlg.Show() != ItemSelectionDialogResult.Confirmed) return null;
            //   return ModelPathUtils.ConvertModelPathToUserVisiblePath(dlg.GetSelectedModelPath());
            _ = title;
            _ = suggestedName;
            return null; // returning null cleanly cancels until the dialog is wired
        }

        private static string Truncate(string value, int max)
            => string.IsNullOrEmpty(value) || value.Length <= max ? value : value.Substring(0, max) + "...";
    }
}

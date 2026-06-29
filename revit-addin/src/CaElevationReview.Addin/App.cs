using System;
using System.Reflection;
using Autodesk.Revit.UI;

namespace CaElevationReview.Addin
{
    /// <summary>
    /// Add-in entry point. Builds the "CA Elevation Review" ribbon panel with the three
    /// desktop-flow actions from the design doc: Export Field Bundle, Import Captures,
    /// Generate Report.
    ///
    /// This class is intentionally thin and platform-coupled: it only wires the Revit UI
    /// to the commands. All real work lives in the command classes and the pure
    /// Manifest/Engine/Verdict layers.
    /// </summary>
    public sealed class App : IExternalApplication
    {
        private const string TabName = "CA Elevation Review";
        private const string PanelName = "CA Elevation Review";

        /// <summary>Namespace-qualified assembly path, used to bind ribbon buttons to commands.</summary>
        private static readonly string AssemblyPath = Assembly.GetExecutingAssembly().Location;

        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                RibbonPanel panel = CreatePanel(application);

                AddButton(
                    panel,
                    name: "ExportFieldBundle",
                    text: "Export\nField Bundle",
                    className: typeof(Commands.ExportFieldBundleCommand).FullName!,
                    tooltip: "Extract the spec manifest + floorplans for selected level(s) " +
                             "and write a field bundle to hand to the capture app.");

                AddButton(
                    panel,
                    name: "ImportCaptures",
                    text: "Import\nCaptures",
                    className: typeof(Commands.ImportCapturesCommand).FullName!,
                    tooltip: "Point at a returned capture package, run the verification engine " +
                             "out-of-process, and write verdicts back into the model.");

                AddButton(
                    panel,
                    name: "GenerateReport",
                    text: "Generate\nReport",
                    className: typeof(Commands.GenerateReportCommand).FullName!,
                    tooltip: "Open the issuable verdict report produced by the last engine run.");

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show(TabName, $"Failed to initialize add-in:\n{ex.Message}");
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication application) => Result.Succeeded;

        private static RibbonPanel CreatePanel(UIControlledApplication application)
        {
            // Create our own ribbon tab; if it already exists (re-load), reuse it.
            try
            {
                application.CreateRibbonTab(TabName);
            }
            catch (Autodesk.Revit.Exceptions.ArgumentException)
            {
                // Tab already exists this session.
            }

            return application.CreateRibbonPanel(TabName, PanelName);
        }

        private static void AddButton(
            RibbonPanel panel, string name, string text, string className, string tooltip)
        {
            var data = new PushButtonData(name, text, AssemblyPath, className)
            {
                ToolTip = tooltip,
                // TODO: attach 16x16 / 32x32 ribbon icons (LargeImage / Image) once
                // Resources\*.png are added and embedded as <Resource> in the csproj.
            };

            panel.AddItem(data);
        }
    }
}

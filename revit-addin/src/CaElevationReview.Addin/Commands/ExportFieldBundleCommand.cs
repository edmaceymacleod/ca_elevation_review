using System;
using System.Collections.Generic;
using System.IO;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using CaElevationReview.Addin.Manifest;

namespace CaElevationReview.Addin.Commands
{
    /// <summary>
    /// "Export Field Bundle" -- step 1 of the desktop flow.
    ///
    /// Collects the selected level(s)/scope, runs the manifest extractor, and writes a
    /// field bundle (spec_manifest.json + floorplan images) for the capture app.
    ///
    /// The Revit collection / file-dialog calls are stubbed with TODOs, but the
    /// orchestration is real: scope -> extract -> serialize -> write bundle.
    /// </summary>
    [Transaction(TransactionMode.ReadOnly)]
    [Regeneration(RegenerationOption.Manual)]
    public sealed class ExportFieldBundleCommand : IExternalCommand
    {
        /// <summary>Filename of the manifest inside the bundle (matches the engine's expectation).</summary>
        public const string ManifestFileName = "spec_manifest.json";

        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            try
            {
                UIDocument uiDoc = commandData.Application.ActiveUIDocument;
                Document doc = uiDoc.Document;

                ExtractionScope scope = ResolveScope(uiDoc);

                string? bundleDir = PromptForBundleDirectory(doc);
                if (bundleDir == null)
                {
                    return Result.Cancelled; // user backed out of the folder picker
                }

                var extractor = new SpecManifestExtractor();
                SpecManifest manifest = extractor.Extract(doc, scope);

                Directory.CreateDirectory(bundleDir);
                string manifestPath = Path.Combine(bundleDir, ManifestFileName);
                File.WriteAllText(manifestPath, manifest.ToJson());

                // TODO (Revit): the floorplan PNGs referenced by each level.floorplan.image
                // must be exported into bundleDir alongside the manifest (the extractor
                // records their relative paths). Done here, post-serialize, because export
                // is an IO side-effect on the same directory.

                TaskDialog.Show(
                    "Export Field Bundle",
                    $"Wrote field bundle:\n{manifestPath}\n\n" +
                    $"Levels: {manifest.Levels.Count}\nDevices: {manifest.Devices.Count}\n\n" +
                    "Hand this folder to the capture app (AirDrop / Files / iCloud).");

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                return Result.Failed;
            }
        }

        /// <summary>
        /// Determine which levels the user wants exported. For now we honor a current
        /// selection of levels; an empty result means "all levels".
        /// </summary>
        private static ExtractionScope ResolveScope(UIDocument uiDoc)
        {
            var levelIds = new List<long>();

            // TODO (Revit): translate the user's selection into level ids, e.g.:
            //   foreach (ElementId id in uiDoc.Selection.GetElementIds()) {
            //       Element el = uiDoc.Document.GetElement(id);
            //       if (el is Level lvl) levelIds.Add(lvl.Id.Value);
            //   }
            // Alternatively present a level/scope-box checklist dialog here.
            _ = uiDoc;

            return new ExtractionScope { LevelElementIds = levelIds };
        }

        /// <summary>Pick the output directory for the bundle. Returns null if cancelled.</summary>
        private static string? PromptForBundleDirectory(Document doc)
        {
            // TODO (Revit/WPF): show a folder picker (FolderBrowserDialog or the Revit
            // FileSaveDialog). Default next to the .rvt for convenience.
            string baseDir = string.IsNullOrEmpty(doc?.PathName)
                ? Path.GetTempPath()
                : Path.GetDirectoryName(doc!.PathName)!;

            string suggested = Path.Combine(baseDir, "ca-elevation-bundle");
            return suggested;
        }
    }
}

using System;
using System.Collections.Generic;
using Autodesk.Revit.DB;

namespace CaElevationReview.Addin.Verdict
{
    /// <summary>
    /// Colors devices in the live model by their engine verdict using override graphics.
    ///
    /// Platform-coupled: the actual Revit override calls are stubbed with TODOs, but the
    /// verdict -> color mapping and the per-device dispatch flow are real so the behavior
    /// is fully specified for the live wiring.
    ///
    /// Color legend (per the task spec):
    ///   pass          -> green
    ///   flag          -> orange
    ///   absent        -> red
    ///   type_mismatch -> purple
    /// </summary>
    public sealed class VerdictWriteback
    {
        /// <summary>
        /// Name of the CA-Elevation marker stamped on every element we override, so a
        /// later re-import can find and reset previously-coloured elements WITHOUT a
        /// persisted prior-override store. Per docs/pyrevit-migration-plan.md Section 2
        /// the model itself is the record: the marker is the only thing that can cover
        /// devices dropped from the new report (the new report's ids cannot, by definition).
        /// Concretely this is a project/shared parameter flag (or a named element set).
        /// </summary>
        public const string MarkerParameterName = "CA_Elevation_Override";

        // RGB legend, shared with the report renderer so model + report agree.
        private static readonly IReadOnlyDictionary<VerdictKind, (byte R, byte G, byte B)> Legend =
            new Dictionary<VerdictKind, (byte, byte, byte)>
            {
                [VerdictKind.Pass] = (0x2E, 0xA4, 0x4F),         // green
                [VerdictKind.Flag] = (0xF2, 0x8C, 0x28),         // orange
                [VerdictKind.Absent] = (0xD7, 0x2D, 0x2D),       // red
                [VerdictKind.TypeMismatch] = (0x8E, 0x44, 0xAD), // purple
            };

        /// <summary>The RGB legend triple for a verdict; pure, unit-testable.</summary>
        public static (byte R, byte G, byte B) ColorFor(VerdictKind verdict)
        {
            if (Legend.TryGetValue(verdict, out var rgb)) return rgb;
            throw new ArgumentOutOfRangeException(nameof(verdict));
        }

        /// <summary>
        /// Apply verdict colors to every device in the report. The device_id in the report
        /// is the Revit UniqueId stamped by the extractor, so we resolve elements by it.
        /// Must be called from inside a Revit transaction context (the command owns that).
        /// </summary>
        /// <returns>Number of devices successfully colored.</returns>
        public int Apply(Document doc, View view, VerdictReport report)
        {
            if (report == null) throw new ArgumentNullException(nameof(report));

            int colored = 0;
            foreach (DeviceResult result in report.DeviceResults)
            {
                if (TryApplyOne(doc, view, result)) colored++;
            }
            return colored;
        }

        private bool TryApplyOne(Document doc, View view, DeviceResult result)
        {
            (byte r, byte g, byte b) = ColorFor(result.VerdictKind);

            // TODO (Revit): resolve the element and override its graphics in the view.
            //   Element element = doc.GetElement(result.DeviceId); // DeviceId == UniqueId
            //   if (element == null) return false;
            //
            //   var color = new Color(r, g, b);
            //   var ogs = new OverrideGraphicSettings();
            //   ogs.SetProjectionLineColor(color);
            //   ogs.SetSurfaceForegroundPatternColor(color);
            //   // A solid fill pattern makes the override read clearly in 3D/elevation:
            //   ogs.SetSurfaceForegroundPatternId(SolidFillPatternId(doc));
            //   view.SetElementOverrides(element.Id, ogs);
            //
            //   Approximate results (no metric LiDAR / occluded) should be visually
            //   distinguished, e.g. a halftone override:
            //   if (result.Approximate) ogs.SetHalftone(true);
            //
            //   STAMP THE MARKER so Clear() can find this element on a later re-import,
            //   even if it is dropped from the next report (see Clear / Section 2):
            //   Parameter marker = element.LookupParameter(MarkerParameterName);
            //   marker?.Set(1);
            _ = doc;
            _ = view;
            _ = (r, g, b);
            return true;
        }

        /// <summary>
        /// Clears CA Elevation Review overrides previously applied in the view so a
        /// re-import starts clean, including on devices dropped from the new report.
        ///
        /// Marker-based idempotency (docs/pyrevit-migration-plan.md Section 2): we do NOT
        /// clear by the new report's device ids — that set, by definition, cannot contain a
        /// device dropped from the new report, so stale colours would survive. Instead we
        /// enumerate every element in the view carrying the CA-Elevation marker
        /// (<see cref="MarkerParameterName"/>), reset its overrides, and clear the marker.
        /// Must be called inside the SAME transaction as the subsequent Apply.
        /// </summary>
        /// <returns>Number of previously-marked elements reset.</returns>
        public int Clear(Document doc, View view)
        {
            // TODO (Revit): enumerate previously-marked elements and reset them. The marker
            // (not the new report's ids) is what lets this cover dropped devices.
            //   var empty = new OverrideGraphicSettings();
            //   var collector = new FilteredElementCollector(doc, view.Id)
            //       .WhereElementIsNotElementType();
            //   int reset = 0;
            //   foreach (Element element in collector)
            //   {
            //       Parameter marker = element.LookupParameter(MarkerParameterName);
            //       if (marker == null || marker.AsInteger() != 1) continue;
            //       view.SetElementOverrides(element.Id, empty); // reset to view default
            //       marker.Set(0);                               // clear the marker
            //       reset++;
            //   }
            //   return reset;
            _ = doc;
            _ = view;
            return 0;
        }
    }
}

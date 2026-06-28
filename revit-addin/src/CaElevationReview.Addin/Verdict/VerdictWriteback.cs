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
            _ = doc;
            _ = view;
            _ = (r, g, b);
            return true;
        }

        /// <summary>
        /// Clears any CA Elevation Review overrides previously applied in the view, so a
        /// re-import starts clean. Stubbed.
        /// </summary>
        public void Clear(Document doc, View view, IEnumerable<string> deviceIds)
        {
            // TODO (Revit): for each device id, view.SetElementOverrides(id, new OverrideGraphicSettings()).
            _ = doc;
            _ = view;
            _ = deviceIds;
        }
    }
}

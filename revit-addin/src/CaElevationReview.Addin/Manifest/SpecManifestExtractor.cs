using System;
using System.Collections.Generic;
using System.Globalization;
using Autodesk.Revit.DB;

namespace CaElevationReview.Addin.Manifest
{
    /// <summary>
    /// Scope passed from the command: which levels the user selected, plus the default
    /// tolerance ruleset to stamp into the manifest. Kept as a plain struct so the
    /// extraction flow can be reasoned about without a Revit session.
    /// </summary>
    public sealed class ExtractionScope
    {
        /// <summary>Revit ElementIds (as longs) of the levels to include; empty means "all levels".</summary>
        public IReadOnlyList<long> LevelElementIds { get; set; } = Array.Empty<long>();

        /// <summary>Default tolerances applied to every device unless overridden per-device.</summary>
        public Tolerances DefaultTolerances { get; set; } = new Tolerances
        {
            Position = 0.25,        // project units (e.g. feet)
            MountingHeight = 0.083, // ~1 inch
            Orientation = 10.0,     // degrees
        };
    }

    /// <summary>
    /// Walks the Revit model to produce the <see cref="SpecManifest"/> object.
    ///
    /// This is the platform-coupled extraction layer. The Revit API calls are stubbed
    /// with explicit TODOs, but the produced manifest STRUCTURE is real and correct so
    /// the downstream seam (engine, tests) can be exercised against it immediately.
    /// </summary>
    public sealed class SpecManifestExtractor
    {
        /// <summary>The manifest schema version this extractor emits.</summary>
        public const string SchemaVersion = "1.0.0";

        /// <summary>
        /// Build the manifest from the document for the given scope. The <paramref name="doc"/>
        /// is the live Revit document; pass null only from tests that exercise the empty path.
        /// </summary>
        public SpecManifest Extract(Document doc, ExtractionScope scope)
        {
            if (scope == null) throw new ArgumentNullException(nameof(scope));

            var manifest = new SpecManifest
            {
                SchemaVersion = SchemaVersion,
                Project = ExtractProjectInfo(doc),
                CoordinateSystem = ExtractCoordinateSystem(doc),
                DefaultTolerances = scope.DefaultTolerances,
                Levels = ExtractLevels(doc, scope),
                Devices = ExtractDevices(doc, scope),
            };

            return manifest;
        }

        private static ProjectInfo ExtractProjectInfo(Document doc)
        {
            // TODO (Revit): read from doc.ProjectInformation and doc.GetUnits().
            //   var pi = doc.ProjectInformation;
            //   var displayUnits = doc.GetUnits().GetFormatOptions(SpecTypeId.Length).GetUnitTypeId();
            //   units = (displayUnits == UnitTypeId.Meters) ? "meters" : "feet";
            string units = ResolveUnits(doc);

            return new ProjectInfo
            {
                Id = doc?.ProjectInformation?.UniqueId ?? "UNKNOWN-PROJECT",
                Name = doc?.ProjectInformation?.Name ?? "Untitled",
                RevitFile = doc?.PathName ?? string.Empty,
                ExportedAt = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                Units = units,
            };
        }

        private static string ResolveUnits(Document doc)
        {
            // TODO (Revit): inspect doc.GetUnits() as above. Default to feet (Revit internal).
            return "feet";
        }

        private static CoordinateSystem ExtractCoordinateSystem(Document doc)
        {
            // TODO (Revit): read project north from the ProjectLocation / true-north angle.
            //   var pbp = doc.ActiveProjectLocation.GetProjectPosition(XYZ.Zero);
            //   northAngle = pbp.Angle * (180.0 / Math.PI);
            return new CoordinateSystem
            {
                Name = "Project Internal",
                NorthAngle = 0.0,
            };
        }

        private List<Level> ExtractLevels(Document doc, ExtractionScope scope)
        {
            var levels = new List<Level>();

            // TODO (Revit): collect levels and filter by scope.
            //   var collector = new FilteredElementCollector(doc)
            //       .OfClass(typeof(Autodesk.Revit.DB.Level))
            //       .Cast<Autodesk.Revit.DB.Level>();
            //   foreach (var lvl in collector) {
            //       if (scope.LevelElementIds.Count > 0 &&
            //           !scope.LevelElementIds.Contains(lvl.Id.Value)) continue;
            //       levels.Add(BuildLevel(doc, lvl));
            //   }
            //
            // BuildLevel must also EXPORT the floorplan image for the level and compute
            // the pixel->model affine from the exported view's crop box / scale:
            //   - Export the plan view to PNG (ImageExportOptions) -> floorplan.image
            //   - width_px/height_px from the export
            //   - pixel_to_model [a,b,c,d,e,f] from the view crop box + DPI so that
            //       X = a*px + b*py + c, Y = d*px + e*py + f
            //
            // The structure below is what a populated level looks like (left empty so
            // the manifest is schema-valid even before the Revit calls are wired).

            return levels;
        }

        private List<Device> ExtractDevices(Document doc, ExtractionScope scope)
        {
            var devices = new List<Device>();

            // TODO (Revit): collect the in-scope device family instances and project each
            // to a Device DTO. Low-voltage / security / AV devices are typically
            // FamilyInstance elements in categories like:
            //   OST_SecurityDevices, OST_CommunicationDevices, OST_ElectricalFixtures,
            //   OST_AudioVisualDevices, OST_DataDevices, OST_NurseCallDevices.
            //
            //   var col = new FilteredElementCollector(doc)
            //       .OfClass(typeof(FamilyInstance))
            //       .WhereElementIsNotElementType()
            //       .Cast<FamilyInstance>();
            //   foreach (var fi in col) {
            //       if (!IsTargetCategory(fi)) continue;
            //       if (!InScope(fi, scope)) continue;
            //       devices.Add(BuildDevice(doc, fi, scope.DefaultTolerances));
            //   }
            //
            // BuildDevice mapping (this is the load-bearing structural contract):
            //   id            = fi.UniqueId
            //   family        = fi.Symbol.FamilyName
            //   type          = fi.Symbol.Name
            //   level_id      = LevelUniqueId(fi)
            //   elevation_id  = nearest elevation/wall view id (optional)
            //   position      = LocationPoint.Point -> {x,y,z} (Revit feet, internal units)
            //   mounting_height = position.z - level.elevation
            //   orientation   = { facing_angle: angle of fi.FacingOrientation in plan,
            //                     up_axis: "up" }
            //   tolerances    = per-device override or null (engine falls back to default)
            //   metadata      = { revit_element_id, category, ... } as needed

            return devices;
        }

        /// <summary>
        /// Pure helper: derive mounting height above finished floor from a device's Z and
        /// its level elevation. Exposed (and unit-tested) because it is plain arithmetic.
        /// </summary>
        public static double DeriveMountingHeight(double deviceZ, double levelElevation)
            => deviceZ - levelElevation;

        /// <summary>
        /// Pure helper: facing angle in degrees (0 = +X, CCW) from a plan-projected
        /// facing vector (fx, fy). Mirrors the orientation.facing_angle field.
        /// </summary>
        public static double FacingAngleDegrees(double fx, double fy)
        {
            double radians = Math.Atan2(fy, fx);
            double degrees = radians * (180.0 / Math.PI);
            if (degrees < 0) degrees += 360.0;
            return degrees;
        }
    }
}

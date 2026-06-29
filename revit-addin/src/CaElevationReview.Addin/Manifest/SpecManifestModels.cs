using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CaElevationReview.Addin.Manifest
{
    // POCOs mirroring schemas/spec_manifest.schema.json. These are PURE data +
    // serialization: no Revit types, so they are unit-testable off-platform.
    //
    // JSON shape (snake_case) is fixed by the schema; we map it explicitly with
    // [JsonPropertyName] rather than relying on a naming policy so the contract
    // is visible and grep-able.

    /// <summary>
    /// Root of the spec manifest payload: the "expected" half of the seam.
    /// Mirrors <c>schemas/spec_manifest.schema.json</c>.
    /// </summary>
    public sealed class SpecManifest
    {
        /// <summary>Semantic version of this manifest format (e.g. "1.0.0").</summary>
        [JsonPropertyName("schema_version")]
        public string SchemaVersion { get; set; } = "1.0.0";

        [JsonPropertyName("project")]
        public ProjectInfo Project { get; set; } = new ProjectInfo();

        [JsonPropertyName("coordinate_system")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public CoordinateSystem? CoordinateSystem { get; set; }

        [JsonPropertyName("default_tolerances")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public Tolerances? DefaultTolerances { get; set; }

        [JsonPropertyName("levels")]
        public List<Level> Levels { get; set; } = new List<Level>();

        [JsonPropertyName("devices")]
        public List<Device> Devices { get; set; } = new List<Device>();

        /// <summary>JSON options shared by serialize/deserialize so round-trips are symmetric.</summary>
        public static JsonSerializerOptions JsonOptions { get; } = new JsonSerializerOptions
        {
            WriteIndented = true,
            DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        };

        /// <summary>Serialize this manifest to the canonical JSON wire form.</summary>
        public string ToJson() => JsonSerializer.Serialize(this, JsonOptions);

        /// <summary>Parse a manifest from its JSON wire form.</summary>
        public static SpecManifest FromJson(string json)
            => JsonSerializer.Deserialize<SpecManifest>(json, JsonOptions)
               ?? throw new FormatException("Spec manifest JSON deserialized to null.");
    }

    public sealed class ProjectInfo
    {
        [JsonPropertyName("id")]
        public string Id { get; set; } = string.Empty;

        [JsonPropertyName("name")]
        public string Name { get; set; } = string.Empty;

        [JsonPropertyName("revit_file")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? RevitFile { get; set; }

        /// <summary>ISO-8601 export timestamp; serialized as a string per schema.</summary>
        [JsonPropertyName("exported_at")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? ExportedAt { get; set; }

        /// <summary>"feet" or "meters".</summary>
        [JsonPropertyName("units")]
        public string Units { get; set; } = "feet";
    }

    public sealed class CoordinateSystem
    {
        [JsonPropertyName("name")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? Name { get; set; }

        /// <summary>Project-north relative to true north, degrees.</summary>
        [JsonPropertyName("north_angle")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public double? NorthAngle { get; set; }
    }

    /// <summary>
    /// Pass/flag thresholds. position/mounting_height in project units; orientation in degrees.
    /// </summary>
    public sealed class Tolerances
    {
        [JsonPropertyName("position")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public double? Position { get; set; }

        [JsonPropertyName("mounting_height")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public double? MountingHeight { get; set; }

        [JsonPropertyName("orientation")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public double? Orientation { get; set; }
    }

    public sealed class Level
    {
        [JsonPropertyName("id")]
        public string Id { get; set; } = string.Empty;

        [JsonPropertyName("name")]
        public string Name { get; set; } = string.Empty;

        /// <summary>Z of the finished floor for this level, project units.</summary>
        [JsonPropertyName("elevation")]
        public double Elevation { get; set; }

        [JsonPropertyName("floorplan")]
        public Floorplan Floorplan { get; set; } = new Floorplan();
    }

    public sealed class Floorplan
    {
        /// <summary>Relative path to the floorplan image inside the bundle.</summary>
        [JsonPropertyName("image")]
        public string Image { get; set; } = string.Empty;

        [JsonPropertyName("width_px")]
        public int WidthPx { get; set; }

        [JsonPropertyName("height_px")]
        public int HeightPx { get; set; }

        /// <summary>
        /// 2x3 row-major affine mapping plan pixel (px,py,1) -> model (X,Y):
        /// [a,b,c, d,e,f] => X = a*px + b*py + c, Y = d*px + e*py + f. Always 6 numbers.
        /// </summary>
        [JsonPropertyName("pixel_to_model")]
        public double[] PixelToModel { get; set; } = new double[6];
    }

    public sealed class Device
    {
        /// <summary>Stable unique device id (Revit ElementId or UniqueId).</summary>
        [JsonPropertyName("id")]
        public string Id { get; set; } = string.Empty;

        [JsonPropertyName("family")]
        public string Family { get; set; } = string.Empty;

        [JsonPropertyName("type")]
        public string Type { get; set; } = string.Empty;

        [JsonPropertyName("level_id")]
        public string LevelId { get; set; } = string.Empty;

        /// <summary>Which elevation/wall view this device belongs to.</summary>
        [JsonPropertyName("elevation_id")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? ElevationId { get; set; }

        [JsonPropertyName("position")]
        public Point3 Position { get; set; } = new Point3();

        /// <summary>Height above finished floor, project units. Derived from position.z - level.elevation if omitted.</summary>
        [JsonPropertyName("mounting_height")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public double? MountingHeight { get; set; }

        [JsonPropertyName("orientation")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public Orientation? Orientation { get; set; }

        [JsonPropertyName("tolerances")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public Tolerances? Tolerances { get; set; }

        /// <summary>Free-form extra fields (schema permits an open object here).</summary>
        [JsonPropertyName("metadata")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public Dictionary<string, JsonElement>? Metadata { get; set; }
    }

    public sealed class Orientation
    {
        /// <summary>Heading in plan the device faces, degrees, 0 = +X, CCW.</summary>
        [JsonPropertyName("facing_angle")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public double? FacingAngle { get; set; }

        /// <summary>"up" | "down" | "left" | "right". Defaults to "up".</summary>
        [JsonPropertyName("up_axis")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? UpAxis { get; set; }
    }

    public sealed class Point3
    {
        [JsonPropertyName("x")]
        public double X { get; set; }

        [JsonPropertyName("y")]
        public double Y { get; set; }

        [JsonPropertyName("z")]
        public double Z { get; set; }
    }
}

using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CaElevationReview.Addin.Verdict
{
    // POCOs mirroring schemas/verdict_report.schema.json -- the engine's output,
    // deserialized here for write-back and report opening. Pure data, no Revit.

    /// <summary>The four verdict classes the engine emits per device.</summary>
    public enum VerdictKind
    {
        Pass,
        Flag,
        Absent,
        TypeMismatch,
    }

    /// <summary>Maps verdict enum values to/from the schema's snake/lower-case strings.</summary>
    public static class VerdictKindMap
    {
        public static VerdictKind Parse(string value) => value switch
        {
            "pass" => VerdictKind.Pass,
            "flag" => VerdictKind.Flag,
            "absent" => VerdictKind.Absent,
            "type_mismatch" => VerdictKind.TypeMismatch,
            _ => throw new FormatException($"Unknown verdict '{value}'."),
        };

        public static string ToWire(VerdictKind kind) => kind switch
        {
            VerdictKind.Pass => "pass",
            VerdictKind.Flag => "flag",
            VerdictKind.Absent => "absent",
            VerdictKind.TypeMismatch => "type_mismatch",
            _ => throw new ArgumentOutOfRangeException(nameof(kind)),
        };
    }

    /// <summary>
    /// Root of the verdict report payload. Mirrors <c>schemas/verdict_report.schema.json</c>.
    /// </summary>
    public sealed class VerdictReport
    {
        [JsonPropertyName("schema_version")]
        public string SchemaVersion { get; set; } = "1.0.0";

        [JsonPropertyName("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonPropertyName("generated_at")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? GeneratedAt { get; set; }

        [JsonPropertyName("engine_version")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? EngineVersion { get; set; }

        /// <summary>"feet" or "meters".</summary>
        [JsonPropertyName("units")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? Units { get; set; }

        [JsonPropertyName("device_results")]
        public List<DeviceResult> DeviceResults { get; set; } = new List<DeviceResult>();

        [JsonPropertyName("summary")]
        public VerdictSummary Summary { get; set; } = new VerdictSummary();

        public static JsonSerializerOptions JsonOptions { get; } = new JsonSerializerOptions
        {
            WriteIndented = true,
            DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        };

        public string ToJson() => JsonSerializer.Serialize(this, JsonOptions);

        public static VerdictReport FromJson(string json)
            => JsonSerializer.Deserialize<VerdictReport>(json, JsonOptions)
               ?? throw new FormatException("Verdict report JSON deserialized to null.");
    }

    public sealed class DeviceResult
    {
        [JsonPropertyName("device_id")]
        public string DeviceId { get; set; } = string.Empty;

        [JsonPropertyName("family")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? Family { get; set; }

        [JsonPropertyName("type")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? Type { get; set; }

        /// <summary>Raw wire verdict string; use <see cref="VerdictKindMap"/> for the enum.</summary>
        [JsonPropertyName("verdict")]
        public string Verdict { get; set; } = "absent";

        [JsonPropertyName("confidence")]
        public double Confidence { get; set; }

        [JsonPropertyName("matched_shot_id")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? MatchedShotId { get; set; }

        [JsonPropertyName("identity_confirmed")]
        public bool IdentityConfirmed { get; set; }

        [JsonPropertyName("deltas")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public Deltas? Deltas { get; set; }

        /// <summary>True when geometry was derived without metric LiDAR or from a protruding/occluded device.</summary>
        [JsonPropertyName("approximate")]
        public bool Approximate { get; set; }

        [JsonPropertyName("notes")]
        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public List<string>? Notes { get; set; }

        /// <summary>Convenience accessor: the parsed verdict enum.</summary>
        [JsonIgnore]
        public VerdictKind VerdictKind => VerdictKindMap.Parse(Verdict);
    }

    /// <summary>Measured deviations; null where not measurable from the capture.</summary>
    public sealed class Deltas
    {
        /// <summary>Euclidean position delta, project units.</summary>
        [JsonPropertyName("position")]
        public double? Position { get; set; }

        [JsonPropertyName("mounting_height")]
        public double? MountingHeight { get; set; }

        /// <summary>Facing-angle delta, degrees.</summary>
        [JsonPropertyName("orientation")]
        public double? Orientation { get; set; }
    }

    public sealed class VerdictSummary
    {
        [JsonPropertyName("total")]
        public int Total { get; set; }

        [JsonPropertyName("pass")]
        public int Pass { get; set; }

        [JsonPropertyName("flag")]
        public int Flag { get; set; }

        [JsonPropertyName("absent")]
        public int Absent { get; set; }

        [JsonPropertyName("type_mismatch")]
        public int TypeMismatch { get; set; }
    }
}

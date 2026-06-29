using System.Collections.Generic;
using System.Text.Json;
using CaElevationReview.Addin.Manifest;
using Xunit;

namespace CaElevationReview.Tests
{
    /// <summary>
    /// Round-trip + schema-shape tests for the spec manifest DTOs. These guard the
    /// internal seam: if the JSON field names drift from the schema, the engine stops
    /// accepting our payload, and these tests are the cheap place that catches it.
    /// </summary>
    public sealed class SpecManifestSerializationTests
    {
        private static SpecManifest SampleManifest()
        {
            return new SpecManifest
            {
                SchemaVersion = "1.0.0",
                Project = new ProjectInfo
                {
                    Id = "proj-123",
                    Name = "Test Tower",
                    RevitFile = @"C:\models\test.rvt",
                    ExportedAt = "2026-06-28T12:00:00Z",
                    Units = "feet",
                },
                CoordinateSystem = new CoordinateSystem { Name = "Project Internal", NorthAngle = 0.0 },
                DefaultTolerances = new Tolerances { Position = 0.25, MountingHeight = 0.083, Orientation = 10.0 },
                Levels =
                {
                    new Level
                    {
                        Id = "level-1",
                        Name = "Level 1",
                        Elevation = 0.0,
                        Floorplan = new Floorplan
                        {
                            Image = "floorplans/level-1.png",
                            WidthPx = 2048,
                            HeightPx = 1536,
                            PixelToModel = new[] { 0.01, 0.0, -10.0, 0.0, -0.01, 15.0 },
                        },
                    },
                },
                Devices =
                {
                    new Device
                    {
                        Id = "uid-abc",
                        Family = "Card Reader",
                        Type = "HID-iCLASS",
                        LevelId = "level-1",
                        ElevationId = "elev-north",
                        Position = new Point3 { X = 12.5, Y = 3.0, Z = 3.5 },
                        MountingHeight = 3.5,
                        Orientation = new Orientation { FacingAngle = 90.0, UpAxis = "up" },
                    },
                },
            };
        }

        [Fact]
        public void RoundTrip_PreservesAllFields()
        {
            SpecManifest original = SampleManifest();

            string json = original.ToJson();
            SpecManifest parsed = SpecManifest.FromJson(json);

            Assert.Equal(original.SchemaVersion, parsed.SchemaVersion);
            Assert.Equal(original.Project.Id, parsed.Project.Id);
            Assert.Equal(original.Project.Units, parsed.Project.Units);
            Assert.Equal(original.DefaultTolerances!.Position, parsed.DefaultTolerances!.Position);

            Assert.Single(parsed.Levels);
            Level lvl = parsed.Levels[0];
            Assert.Equal("level-1", lvl.Id);
            Assert.Equal(6, lvl.Floorplan.PixelToModel.Length);
            Assert.Equal(-10.0, lvl.Floorplan.PixelToModel[2]);

            Assert.Single(parsed.Devices);
            Device dev = parsed.Devices[0];
            Assert.Equal("uid-abc", dev.Id);
            Assert.Equal(12.5, dev.Position.X);
            Assert.Equal(90.0, dev.Orientation!.FacingAngle);
        }

        [Fact]
        public void Serialize_UsesSchemaSnakeCaseFieldNames()
        {
            string json = SampleManifest().ToJson();
            using JsonDocument doc = JsonDocument.Parse(json);
            JsonElement root = doc.RootElement;

            // Field names must match the JSON schema exactly (snake_case), not C# casing.
            Assert.True(root.TryGetProperty("schema_version", out _));
            Assert.True(root.TryGetProperty("default_tolerances", out _));

            JsonElement level = root.GetProperty("levels")[0];
            JsonElement floorplan = level.GetProperty("floorplan");
            Assert.True(floorplan.TryGetProperty("width_px", out _));
            Assert.True(floorplan.TryGetProperty("pixel_to_model", out JsonElement p2m));
            Assert.Equal(6, p2m.GetArrayLength());

            JsonElement device = root.GetProperty("devices")[0];
            Assert.True(device.TryGetProperty("level_id", out _));
            Assert.True(device.TryGetProperty("mounting_height", out _));
        }

        [Fact]
        public void OptionalNulls_AreOmittedFromJson()
        {
            // A device with no orientation/tolerances/metadata should not emit those keys.
            var manifest = new SpecManifest
            {
                Project = new ProjectInfo { Id = "p", Name = "n", Units = "meters" },
                Levels =
                {
                    new Level
                    {
                        Id = "l", Name = "L", Elevation = 0,
                        Floorplan = new Floorplan { Image = "i.png", WidthPx = 1, HeightPx = 1, PixelToModel = new double[6] },
                    },
                },
                Devices =
                {
                    new Device { Id = "d", Family = "F", Type = "T", LevelId = "l", Position = new Point3() },
                },
            };

            string json = manifest.ToJson();
            using JsonDocument doc = JsonDocument.Parse(json);
            JsonElement device = doc.RootElement.GetProperty("devices")[0];

            Assert.False(device.TryGetProperty("orientation", out _));
            Assert.False(device.TryGetProperty("tolerances", out _));
            Assert.False(device.TryGetProperty("metadata", out _));
        }

        [Fact]
        public void Deserialize_AcceptsEngineUnknownDeviceMetadata()
        {
            // metadata is an open object; round-trip a couple of arbitrary keys.
            var manifest = new SpecManifest
            {
                Project = new ProjectInfo { Id = "p", Name = "n", Units = "feet" },
                Levels =
                {
                    new Level { Id = "l", Name = "L", Elevation = 0, Floorplan = new Floorplan { Image = "i", WidthPx = 1, HeightPx = 1, PixelToModel = new double[6] } },
                },
                Devices =
                {
                    new Device
                    {
                        Id = "d", Family = "F", Type = "T", LevelId = "l", Position = new Point3(),
                        Metadata = new Dictionary<string, JsonElement>
                        {
                            ["revit_element_id"] = JsonSerializer.SerializeToElement(98765),
                            ["category"] = JsonSerializer.SerializeToElement("Security Devices"),
                        },
                    },
                },
            };

            SpecManifest parsed = SpecManifest.FromJson(manifest.ToJson());
            Dictionary<string, JsonElement> meta = parsed.Devices[0].Metadata!;
            Assert.Equal(98765, meta["revit_element_id"].GetInt32());
            Assert.Equal("Security Devices", meta["category"].GetString());
        }
    }
}

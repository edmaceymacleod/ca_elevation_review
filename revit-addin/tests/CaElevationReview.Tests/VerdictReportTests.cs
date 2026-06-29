using CaElevationReview.Addin.Verdict;
using Xunit;

namespace CaElevationReview.Tests
{
    /// <summary>
    /// Deserialization tests for the engine's verdict report -- the other half of the
    /// seam. Uses a hand-written JSON blob shaped like real engine output so a schema
    /// drift on the engine side is caught here.
    /// </summary>
    public sealed class VerdictReportTests
    {
        private const string SampleJson = @"
        {
          ""schema_version"": ""1.0.0"",
          ""project_id"": ""proj-123"",
          ""generated_at"": ""2026-06-28T13:00:00Z"",
          ""engine_version"": ""0.1.0"",
          ""units"": ""feet"",
          ""device_results"": [
            {
              ""device_id"": ""uid-abc"",
              ""family"": ""Card Reader"",
              ""type"": ""HID-iCLASS"",
              ""verdict"": ""pass"",
              ""confidence"": 0.92,
              ""matched_shot_id"": ""shot-01"",
              ""identity_confirmed"": false,
              ""deltas"": { ""position"": 0.04, ""mounting_height"": 0.01, ""orientation"": 2.0 },
              ""approximate"": false,
              ""notes"": [""within tolerance""]
            },
            {
              ""device_id"": ""uid-def"",
              ""verdict"": ""type_mismatch"",
              ""confidence"": 0.61,
              ""matched_shot_id"": null,
              ""deltas"": { ""position"": null, ""mounting_height"": null, ""orientation"": null },
              ""approximate"": true
            }
          ],
          ""summary"": { ""total"": 2, ""pass"": 1, ""flag"": 0, ""absent"": 0, ""type_mismatch"": 1 }
        }";

        [Fact]
        public void Deserialize_ParsesDeviceResultsAndSummary()
        {
            VerdictReport report = VerdictReport.FromJson(SampleJson);

            Assert.Equal("1.0.0", report.SchemaVersion);
            Assert.Equal("proj-123", report.ProjectId);
            Assert.Equal("feet", report.Units);
            Assert.Equal(2, report.DeviceResults.Count);

            DeviceResult first = report.DeviceResults[0];
            Assert.Equal(VerdictKind.Pass, first.VerdictKind);
            Assert.Equal(0.92, first.Confidence);
            Assert.Equal(0.04, first.Deltas!.Position);
            Assert.False(first.Approximate);

            DeviceResult second = report.DeviceResults[1];
            Assert.Equal(VerdictKind.TypeMismatch, second.VerdictKind);
            Assert.Null(second.MatchedShotId);
            Assert.Null(second.Deltas!.Position);
            Assert.True(second.Approximate);

            Assert.Equal(2, report.Summary.Total);
            Assert.Equal(1, report.Summary.Pass);
            Assert.Equal(1, report.Summary.TypeMismatch);
        }

        [Theory]
        [InlineData("pass", VerdictKind.Pass)]
        [InlineData("flag", VerdictKind.Flag)]
        [InlineData("absent", VerdictKind.Absent)]
        [InlineData("type_mismatch", VerdictKind.TypeMismatch)]
        public void VerdictKindMap_RoundTrips(string wire, VerdictKind kind)
        {
            Assert.Equal(kind, VerdictKindMap.Parse(wire));
            Assert.Equal(wire, VerdictKindMap.ToWire(kind));
        }
    }
}

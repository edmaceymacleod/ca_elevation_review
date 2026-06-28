namespace CaElevationReview.Addin.Commands.Support
{
    /// <summary>
    /// Minimal session state shared between commands: the path of the most recent
    /// verdict report, so "Generate Report" can open what "Import Captures" produced.
    ///
    /// Deliberately simple (static) for v1; a real implementation would key this per
    /// document. Kept out of the command classes so it is trivially testable.
    /// </summary>
    public static class LastRun
    {
        /// <summary>Absolute path to the most recent verdict_report.json, or null.</summary>
        public static string? ReportPath { get; set; }
    }
}

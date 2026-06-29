#if canImport(OSLog)
    import OSLog

    /// Shared `os.Logger`s for the capture app.
    ///
    /// Per the "always add debug logging to complex/async flows" rule (see
    /// `../../CLAUDE.md`): the ARKit session, depth/pose extraction, and bundle IO
    /// are async and only misbehave on-device, so route their diagnostics here.
    /// Logs surface in Console.app and via `log stream` / `xcrun simctl spawn …
    /// log` with no debugger attached.
    ///
    /// Gate chatty per-frame logs on `FeatureFlags.verboseCaptureLogging` so the
    /// signal isn't drowned in normal operation.
    enum Log {
        private static let subsystem = "tech.sterling.caelevationreview"

        /// ARKit session lifecycle, frame capture, depth/intrinsics/pose extraction.
        static let capture = Logger(subsystem: subsystem, category: "capture")
        /// Field-bundle read and capture-package write.
        static let bundle = Logger(subsystem: subsystem, category: "bundle")
        /// View navigation, pin placement, export flow.
        static let ui = Logger(subsystem: subsystem, category: "ui")
    }
#endif

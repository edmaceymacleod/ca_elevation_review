//
//  CaElevationApp.swift
//  CaElevationApp
//
//  @main entry point for the CA Elevation Review iPhone capture app.
//
//  This target is the SwiftUI + ARKit *app layer*. It is deliberately thin: a
//  sensor client that loads a field bundle, lets the user pin location +
//  heading, captures RGB + LiDAR depth + ARKit pose, and exports a capture
//  package. NO analysis logic lives here -- that is the CPython engine's job.
//
//  All pure logic (models, bundle IO, affine math) lives in the platform-free
//  `CaElevationKit` package; this target depends on it. See README.md for how
//  these sources are added to an Xcode App target.
//

import SwiftUI
import CaElevationKit

@main
struct CaElevationApp: App {
    /// App-wide session state: which bundle is loaded and the shots taken so far.
    @StateObject private var session = CaptureSessionModel()

    var body: some Scene {
        WindowGroup {
            ProjectListView()
                .environmentObject(session)
        }
    }
}

/// Observable, app-wide capture state shared across the field-flow screens.
///
/// Holds the loaded field bundle (manifest + its on-disk location), the
/// currently selected level, and the shots accumulated during the walk. This is
/// the glue between screens; the heavy sensor work lives in `ARCaptureSession`
/// and the packaging in `CaptureExporter`.
@MainActor
final class CaptureSessionModel: ObservableObject {
    /// The decoded manifest of the loaded bundle, or `nil` before step 1.
    @Published var manifest: SpecManifest?
    /// On-disk root of the loaded field bundle (for resolving floorplan images).
    @Published var bundleDirectory: URL?
    /// The level the user is currently capturing on (step 2).
    @Published var selectedLevel: Level?
    /// Shots taken so far this session (step 3-4), keyed in capture order.
    @Published var shots: [Shot] = []

    /// Load and decode a field bundle directory (step 1).
    func loadBundle(at directory: URL) throws {
        let manifest = try BundleIO.readManifest(from: directory)
        self.manifest = manifest
        self.bundleDirectory = directory
        self.selectedLevel = manifest.levels.first
        self.shots = []
    }

    /// Append a finished shot to the session (called after Place-Pin confirm).
    func add(_ shot: Shot) {
        shots.append(shot)
    }

    /// Devices expected on the selected level (for the coverage view).
    var devicesForSelectedLevel: [Device] {
        guard let level = selectedLevel, let manifest else { return [] }
        return manifest.devices.filter { $0.levelId == level.id }
    }
}

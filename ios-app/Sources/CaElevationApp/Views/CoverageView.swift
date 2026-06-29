//
//  CoverageView.swift
//  CaElevationApp
//
//  Field flow step 5 -- "See it land." The plan with placed camera icons (one
//  per shot, showing heading) and a captured-vs-expected list for the level, so
//  the operator knows which walls still need a shot. Step 6 (export) lives here
//  too: assemble all shots into a CapturePackage and share it back to desktop.
//

import SwiftUI
import UIKit
import CaElevationKit

struct CoverageView: View {
    let level: Level

    @EnvironmentObject private var session: CaptureSessionModel
    @State private var exportedPackageURL: URL?
    @State private var isSharing = false
    @State private var exportError: String?

    var body: some View {
        VStack {
            planWithCameras
                .frame(maxHeight: 320)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .padding(.horizontal)

            List {
                Section("Shots this level (\(shotsForLevel.count))") {
                    ForEach(shotsForLevel, id: \.id) { shot in
                        ShotRow(shot: shot)
                    }
                }
                Section("Expected elevations") {
                    ForEach(expectedElevations, id: \.id) { item in
                        HStack {
                            Image(systemName: item.captured ? "checkmark.circle.fill" : "circle")
                                .foregroundStyle(item.captured ? .green : .secondary)
                            Text(item.id)
                            Spacer()
                            Text("\(item.deviceCount) devices")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle("Coverage")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Export") { exportPackage() }
                    .disabled(session.shots.isEmpty)
            }
        }
        .sheet(isPresented: $isSharing) {
            if let url = exportedPackageURL {
                // Step 6: hand the package back to desktop via the share sheet
                // (AirDrop / Files / iCloud) -- local-only, no sync server.
                ShareSheet(items: [url])
            }
        }
        .alert("Export failed", isPresented: .constant(exportError != nil)) {
            Button("OK") { exportError = nil }
        } message: {
            Text(exportError ?? "")
        }
    }

    // MARK: - Subviews

    private var planWithCameras: some View {
        FloorplanPinCanvas(
            level: level,
            bundleDirectory: session.bundleDirectory,
            cameras: shotsForLevel.map { CameraMarker(pin: $0.pin) }
        )
    }

    // MARK: - Derived

    private var shotsForLevel: [Shot] {
        session.shots.filter { $0.levelId == level.id }
    }

    private struct ExpectedElevation: Identifiable {
        let id: String
        let deviceCount: Int
        let captured: Bool
    }

    private var expectedElevations: [ExpectedElevation] {
        guard let manifest = session.manifest else { return [] }
        let devices = manifest.devices.filter { $0.levelId == level.id }
        let capturedIds = Set(shotsForLevel.compactMap { $0.elevationId })
        let grouped = Dictionary(grouping: devices) { $0.elevationId ?? "(untagged)" }
        return grouped
            .map { ExpectedElevation(id: $0.key, deviceCount: $0.value.count, captured: capturedIds.contains($0.key)) }
            .sorted { $0.id < $1.id }
    }

    // MARK: - Actions

    private func exportPackage() {
        guard let exportDirectory = session.exportDirectory else {
            exportError = "No export directory; load a bundle first."
            return
        }
        do {
            let url = try CaptureExporter.exportPackage(
                shots: session.shots,
                projectId: session.manifest?.project.id ?? "unknown",
                exportDirectory: exportDirectory
            )
            exportedPackageURL = url
            isSharing = true
        } catch {
            exportError = String(describing: error)
        }
    }
}

private struct ShotRow: View {
    let shot: Shot
    var body: some View {
        HStack {
            Image(systemName: "camera.viewfinder")
            VStack(alignment: .leading) {
                Text(shot.elevationId ?? "Untagged").font(.subheadline)
                Text(String(format: "pin (%.0f, %.0f) · %.0f°", shot.pin.x, shot.pin.y, shot.pin.heading))
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Shared floorplan canvas

/// A placed camera marker on the plan (pixel position + heading).
struct CameraMarker {
    let pin: Pin
}

/// Renders a level's floorplan with an optional tappable position pin and/or a
/// set of placed camera markers. Used by PlacePinView (one editable pin) and
/// CoverageView (many read-only camera icons).
///
/// Coordinate handling: the floorplan is displayed scaled-to-fit; taps and
/// marker positions are mapped between displayed points and floorplan PIXELS so
/// the stored `Pin.x/.y` are always in the plan's native pixel space (matching
/// the schema and the level affine).
struct FloorplanPinCanvas: View {
    let level: Level
    let bundleDirectory: URL?

    // Editable single-pin mode (PlacePinView).
    var pinPixel: Binding<CGPoint?>?
    var headingDegrees: Double = 0

    // Read-only multi-camera mode (CoverageView).
    var cameras: [CameraMarker] = []

    var body: some View {
        GeometryReader { geo in
            ZStack {
                planImage
                let transform = PlanTransform(
                    imagePixelSize: CGSize(width: level.floorplan.widthPx, height: level.floorplan.heightPx),
                    displaySize: geo.size
                )

                // Editable pin.
                if let pinPixel, let pixel = pinPixel.wrappedValue {
                    PinMarker(headingDegrees: headingDegrees)
                        .position(transform.displayPoint(fromPixel: pixel))
                }

                // Read-only camera icons.
                ForEach(Array(cameras.enumerated()), id: \.offset) { _, marker in
                    PinMarker(headingDegrees: marker.pin.heading, isCamera: true)
                        .position(transform.displayPoint(fromPixel: CGPoint(x: marker.pin.x, y: marker.pin.y)))
                }
            }
            .contentShape(Rectangle())
            .onTapGesture { location in
                guard let pinPixel else { return }
                let transform = PlanTransform(
                    imagePixelSize: CGSize(width: level.floorplan.widthPx, height: level.floorplan.heightPx),
                    displaySize: geo.size
                )
                pinPixel.wrappedValue = transform.pixel(fromDisplay: location)
            }
        }
    }

    @ViewBuilder
    private var planImage: some View {
        if let dir = bundleDirectory, let image = FloorplanImage.load(level: level, bundleDirectory: dir) {
            image.resizable().scaledToFit()
        } else {
            Rectangle().fill(.quaternary)
                .overlay(Image(systemName: "map").font(.largeTitle).foregroundStyle(.secondary))
        }
    }
}

/// Maps between floorplan pixel space and the scaled-to-fit display rect.
private struct PlanTransform {
    let imagePixelSize: CGSize
    let displaySize: CGSize

    /// scaledToFit scale and the letterbox origin offset.
    private var fit: (scale: CGFloat, origin: CGPoint) {
        guard imagePixelSize.width > 0, imagePixelSize.height > 0 else {
            return (1, .zero)
        }
        let scale = min(displaySize.width / imagePixelSize.width,
                        displaySize.height / imagePixelSize.height)
        let drawn = CGSize(width: imagePixelSize.width * scale, height: imagePixelSize.height * scale)
        let origin = CGPoint(x: (displaySize.width - drawn.width) / 2,
                             y: (displaySize.height - drawn.height) / 2)
        return (scale, origin)
    }

    func displayPoint(fromPixel pixel: CGPoint) -> CGPoint {
        let (scale, origin) = fit
        return CGPoint(x: origin.x + pixel.x * scale, y: origin.y + pixel.y * scale)
    }

    func pixel(fromDisplay point: CGPoint) -> CGPoint {
        let (scale, origin) = fit
        guard scale != 0 else { return .zero }
        return CGPoint(x: (point.x - origin.x) / scale, y: (point.y - origin.y) / scale)
    }
}

/// A pin / camera glyph with a heading arrow.
private struct PinMarker: View {
    var headingDegrees: Double
    var isCamera: Bool = false

    var body: some View {
        ZStack {
            Image(systemName: isCamera ? "camera.fill" : "mappin.circle.fill")
                .font(.title2)
                .foregroundStyle(isCamera ? .blue : .red)
            Image(systemName: "arrow.up")
                .font(.caption.bold())
                .foregroundStyle(.white)
                .offset(y: -18)
                // Heading is plan degrees (0=+X CCW); rotate the arrow to match.
                .rotationEffect(.degrees(90 - headingDegrees))
        }
    }
}

/// UIKit share sheet wrapper for the export hand-off.
private struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

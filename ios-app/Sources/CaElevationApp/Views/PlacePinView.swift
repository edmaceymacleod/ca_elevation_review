//
//  PlacePinView.swift
//  CaElevationApp
//
//  Field flow step 4 -- "Place it." Post-capture review: confirm the shot, drop
//  the location pin on the plan, and confirm the heading arrow (pre-filled from
//  the device compass). Optionally tag the target elevation.
//
//  THIS IS THE GEOREFERENCE PRIMITIVE. The pin (floorplan pixel + heading) is
//  the one piece of hard-to-automate input only a person can supply quickly; it
//  drops the capture into the building's coordinate system (see design.md,
//  "the floorplan pin as georeference anchor"). The pin pixel maps to model XY
//  through the level's `pixel_to_model` affine in CaElevationKit.
//

import SwiftUI
import CaElevationKit
#if canImport(OSLog)
import OSLog
#endif

struct PlacePinView: View {
    let level: Level
    let frame: CapturedFrame

    @EnvironmentObject private var session: CaptureSessionModel
    @Environment(\.dismiss) private var dismiss

    /// Pin position in floorplan PIXEL coordinates (the schema's `pin.x/.y`).
    @State private var pinPixel: CGPoint?
    /// Heading in plan, degrees, 0 = +X CCW. Pre-filled from the compass.
    @State private var heading: Double
    @State private var confidence: Pin.Confidence = .medium
    @State private var elevationId: String?
    /// User-facing staging error (e.g. disk full, path-escape rejection). When
    /// set, an alert is shown and the shot is NOT recorded or dismissed, so a
    /// failed capture never looks successful. Mirrors `CoverageView.exportError`.
    @State private var saveError: String?

    init(level: Level, frame: CapturedFrame) {
        self.level = level
        self.frame = frame
        // Heading is pre-filled on appear (see prefillHeading), because the
        // compass->plan conversion needs the manifest north angle from the
        // environment, which is not available at init.
        _heading = State(initialValue: 0)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                shotPreview
                planPinPicker
                headingControl
                elevationTag
            }
            .padding()
        }
        .navigationTitle("Place It")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear(perform: prefillHeading)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Confirm") { confirm() }
                    .disabled(pinPixel == nil)
            }
        }
        .alert("Couldn't save shot", isPresented: .constant(saveError != nil)) {
            Button("OK") { saveError = nil }
        } message: {
            Text(saveError ?? "")
        }
    }

    // MARK: - Subviews

    private var shotPreview: some View {
        VStack(alignment: .leading) {
            Text("Shot").font(.headline)
            if let image = frame.previewImage {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            } else {
                RoundedRectangle(cornerRadius: 12).fill(.quaternary).frame(height: 180)
            }
        }
    }

    /// Tap the plan to drop the operator-position pin. The tap point is
    /// converted from the displayed image frame back to floorplan pixels.
    private var planPinPicker: some View {
        VStack(alignment: .leading) {
            Text("Where you stood").font(.headline)
            FloorplanPinCanvas(
                level: level,
                bundleDirectory: session.bundleDirectory,
                pinPixel: $pinPixel,
                headingDegrees: heading
            )
            .frame(height: 300)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            if let pinPixel, let affine = currentAffine {
                let model = affine.modelXY(fromPixel: Double(pinPixel.x), Double(pinPixel.y))
                Text(String(format: "Model XY: (%.2f, %.2f)", model.x, model.y))
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            } else if pinPixel != nil {
                // Pin placed, but the level's affine is missing/singular, so a
                // model-XY readout would be meaningless. The exported pin pixel is
                // still valid (the engine recomputes model XY from it).
                Text("Plan not georeferenced; model XY unavailable.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("Tap the plan to mark your position.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var headingControl: some View {
        VStack(alignment: .leading) {
            Text("Heading: \(Int(heading))°").font(.headline)
            Slider(value: $heading, in: 0...360, step: 1)
            Picker("Confidence", selection: $confidence) {
                Text("Low").tag(Pin.Confidence.low)
                Text("Medium").tag(Pin.Confidence.medium)
                Text("High").tag(Pin.Confidence.high)
            }
            .pickerStyle(.segmented)
        }
    }

    private var elevationTag: some View {
        VStack(alignment: .leading) {
            Text("Target elevation (optional)").font(.headline)
            // Distinct elevation ids expected on this level.
            let ids = elevationIds
            Picker("Elevation", selection: $elevationId) {
                Text("None").tag(String?.none)
                ForEach(ids, id: \.self) { id in
                    Text(id).tag(String?.some(id))
                }
            }
            .pickerStyle(.menu)
        }
    }

    // MARK: - Derived

    private var currentAffine: Affine? {
        let affine = level.floorplan.affine
        // Require a non-singular affine before showing a model-XY readout: a
        // degenerate `pixel_to_model` passes `isValid` (count only) but the
        // engine's inverse rejects |det| < 1e-12, so a forward map would display
        // a confident-looking but untrustworthy coordinate.
        guard affine.isValid, abs(affine.determinant) >= 1e-12 else { return nil }
        return affine
    }

    private var elevationIds: [String] {
        guard let manifest = session.manifest else { return [] }
        let ids = manifest.devices
            .filter { $0.levelId == level.id }
            .compactMap { $0.elevationId }
        return Array(Set(ids)).sorted()
    }

    // MARK: - Actions

    /// Pre-fill the heading from the captured compass reading, converted from
    /// true-north compass degrees to plan degrees using the manifest north
    /// angle, so the user confirms / nudges rather than guesses (kills most
    /// coarse-heading error). Pin is left unplaced until the user taps the plan.
    private func prefillHeading() {
        guard let compass = frame.compassHeadingDegrees else { return }
        let northAngle = session.manifest?.coordinateSystem?.northAngle ?? 0
        // plan = 90 - (compass - northAngle), normalized to [0, 360).
        heading = (90 - (compass - northAngle)).normalizedDegrees
    }

    /// Assemble the shot from the captured frame + the user's pin and append it
    /// to the session (step 4 -> 5).
    private func confirm() {
        guard let pinPixel else { return }
        let pin = Pin(
            x: Double(pinPixel.x),
            y: Double(pinPixel.y),
            heading: heading,
            confidence: confidence
        )
        guard let exportDirectory = session.exportDirectory else {
            assertionFailure("no export directory; bundle not loaded")
            return
        }
        do {
            // CaptureExporter turns ARKit frame + pin into a Kit `Shot`, staging
            // RGB + depth media into the session's export directory.
            let shot = try CaptureExporter.makeShot(
                from: frame,
                level: level,
                elevationId: elevationId,
                pin: pin,
                exportDirectory: exportDirectory
            )
            session.add(shot)
            dismiss()
        } catch {
            // Surface to the user and log; do NOT dismiss — losing a hard-to-
            // retake capture silently (assertionFailure is a no-op in release)
            // is worse than making the operator retry. See CLAUDE.md rule 4.
            #if canImport(OSLog)
            Log.capture.error("Failed to export shot: \(error.localizedDescription, privacy: .public)")
            #endif
            saveError = "Couldn't save this shot: \(error.localizedDescription). Try again."
        }
    }
}

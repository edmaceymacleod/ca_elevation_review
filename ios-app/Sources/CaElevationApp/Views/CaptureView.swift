//
//  CaptureView.swift
//  CaElevationApp
//
//  Field flow step 3: live camera with LiDAR sceneDepth active. Frame one wall
//  per shot and shoot. On capture, we freeze the latest ARFrame and push the
//  user into PlacePinView to georeference it.
//
//  The live AR preview is platform-coupled (ARKit + RealityKit). See
//  ARCaptureSession for the sensor wiring. // LiDAR: requires real device.
//

import SwiftUI
import CaElevationKit

struct CaptureView: View {
    let level: Level

    @EnvironmentObject private var session: CaptureSessionModel
    @StateObject private var capture = ARCaptureSession()
    @StateObject private var heading = CompassHeading()
    @State private var pendingFrame: CapturedFrame?

    var body: some View {
        ZStack {
            // Live AR camera feed with LiDAR depth running underneath.
            ARCameraPreview(session: capture)
                .ignoresSafeArea()

            VStack {
                statusBar
                Spacer()
                shutterBar
            }
            .padding()
        }
        .navigationTitle(level.name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                // Steps 5-6: see captures land on the plan and export.
                NavigationLink {
                    CoverageView(level: level)
                } label: {
                    Label("Coverage", systemImage: "map")
                }
            }
        }
        .task {
            // Start the AR session when the view appears; stop on disappear.
            // Inject the compass so each snapshot stamps a heading to pre-fill
            // the pin arrow on the next screen.
            capture.headingProvider = heading
            heading.start()
            await capture.start()
        }
        .onDisappear {
            capture.stop()
            heading.stop()
        }
        .navigationDestination(item: $pendingFrame) { frame in
            PlacePinView(level: level, frame: frame)
        }
    }

    // MARK: - Subviews

    private var statusBar: some View {
        HStack {
            Label(
                capture.isDepthAvailable ? "LiDAR ready" : "No depth",
                systemImage: capture.isDepthAvailable
                    ? "dot.radiowaves.left.and.right"
                    : "exclamationmark.triangle"
            )
            .font(.caption.bold())
            .padding(8)
            .background(.ultraThinMaterial, in: Capsule())
            Spacer()
        }
    }

    private var shutterBar: some View {
        HStack {
            Spacer()
            Button {
                capturePressed()
            } label: {
                Circle()
                    .strokeBorder(.white, lineWidth: 4)
                    .frame(width: 76, height: 76)
                    .overlay(Circle().fill(.white).padding(8))
            }
            .disabled(!capture.isRunning)
            Spacer()
        }
    }

    // MARK: - Actions

    /// Step 3 -> 4: grab the current frame's sensors and move to Place-Pin.
    private func capturePressed() {
        // TODO: real-device only -- grabs the live ARFrame's RGB pixel buffer,
        // sceneDepth (LiDAR), intrinsics, and camera transform. Returns nil in
        // the simulator (no camera / no LiDAR).
        guard let frame = capture.snapshot() else { return }
        pendingFrame = frame
    }
}

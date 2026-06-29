//
//  ARCaptureSession.swift
//  CaElevationApp
//
//  Wraps ARKit's ARSession to pull, per captured frame:
//    * the RGB pixel buffer (camera image),
//    * sceneDepth (LiDAR) -- the metric per-pixel depth map,
//    * camera intrinsics (fx, fy, cx, cy, image size),
//    * the camera transform (6DOF pose, camera-to-world).
//
//  ============================================================================
//  // LiDAR: requires real device.
//  Everything ARKit here is platform-coupled and unavailable in the simulator
//  (no camera, no LiDAR). The pure models + IO live in CaElevationKit and are
//  what CI tests headlessly. This file is exercised only by on-device live
//  tests (Ed's responsibility per design.md).
//  ============================================================================
//

import Foundation
import SwiftUI
import UIKit
import CaElevationKit

#if canImport(ARKit)
import ARKit
import RealityKit
#endif
#if canImport(CoreImage)
import CoreImage
#endif

/// A frozen snapshot of the sensors at capture time, handed to PlacePinView /
/// CaptureExporter. The image / depth payloads are kept as encodable bytes so
/// the rest of the app (and tests, conceptually) need not touch ARKit types.
struct CapturedFrame: Identifiable, Hashable {
    let id = UUID()

    /// JPEG-encoded RGB image bytes.
    let rgbJPEG: Data
    /// Raw float32 depth map in meters, row-major HxW (LiDAR), if available.
    let depthFloat32: Data?
    /// `(height, width)` of the depth map, when `depthFloat32` is present.
    let depthSize: (height: Int, width: Int)?
    /// Camera intrinsics for the RGB image.
    let intrinsics: Intrinsics
    /// 4x4 row-major camera-to-world transform in ARKit's world frame.
    let pose: [Double]
    /// Raw COMPASS heading captured alongside the frame (degrees, 0 = true
    /// north, clockwise), to pre-fill the pin arrow. Filled from
    /// `CompassHeading`; nil if heading unavailable. PlacePinView converts this
    /// to PLAN degrees with the manifest's `coordinate_system.north_angle`.
    let compassHeadingDegrees: Double?
    /// RFC 3339 capture timestamp.
    let capturedAt: String

    /// Lightweight preview for the review screen.
    var previewImage: UIImage? { UIImage(data: rgbJPEG) }

    static func == (lhs: CapturedFrame, rhs: CapturedFrame) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

/// Owns the ARSession and exposes a tiny, UI-friendly surface.
@MainActor
final class ARCaptureSession: ObservableObject {
    @Published private(set) var isRunning = false
    @Published private(set) var isDepthAvailable = false

    /// Latest compass heading, injected so the snapshot can stamp it.
    var headingProvider: CompassHeading?

    #if canImport(ARKit)
    let session = ARSession()
    #endif

    /// Start the AR session with LiDAR sceneDepth enabled.
    func start() async {
        #if canImport(ARKit)
        // TODO: real-device only. Configure world tracking + sceneDepth.
        let configuration = ARWorldTrackingConfiguration()
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            configuration.frameSemantics.insert(.sceneDepth)
            isDepthAvailable = true
        } else {
            // No LiDAR (older device or simulator): still capture RGB + pose,
            // but the engine will lack metric depth for this shot.
            isDepthAvailable = false
        }
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        isRunning = true
        #else
        // Non-Apple build (CI / Linux): nothing to run.
        isRunning = false
        isDepthAvailable = false
        #endif
    }

    func stop() {
        #if canImport(ARKit)
        session.pause()
        #endif
        isRunning = false
    }

    /// Freeze the current frame's sensors into a `CapturedFrame`.
    ///
    /// - Returns: nil if no frame / depth is available (e.g. simulator).
    func snapshot() -> CapturedFrame? {
        #if canImport(ARKit)
        guard let frame = session.currentFrame else { return nil }

        // RGB: the captured pixel buffer encoded to JPEG.
        guard let rgbJPEG = Self.encodeJPEG(frame.capturedImage) else { return nil }

        // Intrinsics from the AR camera (in the captured image's pixel space).
        let k = frame.camera.intrinsics
        let resolution = frame.camera.imageResolution
        let intrinsics = Intrinsics(
            fx: Double(k.columns.0.x),
            fy: Double(k.columns.1.y),
            cx: Double(k.columns.2.x),
            cy: Double(k.columns.2.y),
            width: Int(resolution.width),
            height: Int(resolution.height)
        )

        // Pose: ARKit camera transform (column-major simd) -> 16-element
        // ROW-MAJOR array to match the capture-package schema.
        let pose = Self.rowMajor(frame.camera.transform)

        // LiDAR depth: float32 meters, row-major HxW.
        var depthData: Data?
        var depthSize: (Int, Int)?
        if let sceneDepth = frame.sceneDepth {
            let (data, size) = Self.encodeDepth(sceneDepth.depthMap)
            depthData = data
            depthSize = size
        }

        return CapturedFrame(
            rgbJPEG: rgbJPEG,
            depthFloat32: depthData,
            depthSize: depthSize.map { (height: $0.0, width: $0.1) },
            intrinsics: intrinsics,
            pose: pose,
            compassHeadingDegrees: headingProvider?.headingDegrees,
            capturedAt: ISO8601DateFormatter().string(from: Date())
        )
        #else
        return nil
        #endif
    }

    #if canImport(ARKit)
    /// Convert a column-major simd 4x4 to a 16-element row-major array.
    static func rowMajor(_ m: simd_float4x4) -> [Double] {
        // simd columns are m.columns.0..3; element (row r, col c) = columns[c][r].
        var out = [Double](repeating: 0, count: 16)
        for c in 0..<4 {
            let col = m[c]
            out[0 * 4 + c] = Double(col.x)
            out[1 * 4 + c] = Double(col.y)
            out[2 * 4 + c] = Double(col.z)
            out[3 * 4 + c] = Double(col.w)
        }
        return out
    }

    /// Encode a captured YpCbCr pixel buffer to JPEG.
    static func encodeJPEG(_ pixelBuffer: CVPixelBuffer) -> Data? {
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        let context = CIContext()
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else { return nil }
        return UIImage(cgImage: cgImage).jpegData(compressionQuality: 0.9)
    }

    /// Read a float32 depth map (meters) into row-major bytes + (H,W).
    static func encodeDepth(_ depthMap: CVPixelBuffer) -> (Data, (Int, Int)) {
        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }
        let width = CVPixelBufferGetWidth(depthMap)
        let height = CVPixelBufferGetHeight(depthMap)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(depthMap)
        var out = Data(capacity: width * height * MemoryLayout<Float32>.size)
        if let base = CVPixelBufferGetBaseAddress(depthMap) {
            // Copy row by row to drop any row padding -> tightly packed HxW.
            for row in 0..<height {
                let rowPtr = base.advanced(by: row * bytesPerRow)
                out.append(Data(bytes: rowPtr, count: width * MemoryLayout<Float32>.size))
            }
        }
        return (out, (height, width))
    }
    #endif
}

/// SwiftUI host for the live AR camera feed.
struct ARCameraPreview: UIViewRepresentable {
    let session: ARCaptureSession

    func makeUIView(context: Context) -> UIView {
        #if canImport(ARKit)
        let view = ARView(frame: .zero)
        // Drive the ARView from our owned ARSession so the snapshot and the
        // preview share one frame stream.
        // TODO: real-device only -- ARView shows a black frame in the simulator.
        view.session = session.session
        return view
        #else
        return UIView()
        #endif
    }

    func updateUIView(_ uiView: UIView, context: Context) {}
}

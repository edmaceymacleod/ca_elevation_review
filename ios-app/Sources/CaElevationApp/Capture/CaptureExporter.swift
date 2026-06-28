//
//  CaptureExporter.swift
//  CaElevationApp
//
//  Assembles `Shot` models from captured ARKit frames + the user's pin, and
//  packages all shots of a session into a `CapturePackage` written to disk via
//  CaElevationKit's `BundleIO`. The resulting directory is what gets shared
//  back to desktop (step 6).
//
//  The ARKit -> Kit mapping (pose, intrinsics, depth) is done here in the app
//  layer; the Kit only knows the wire format. Media files (RGB JPEG, raw depth)
//  are staged into the export directory with relative paths matching the shot
//  fields, so the package is self-contained.
//

import Foundation
import CaElevationKit

enum CaptureExporter {
    /// Current capture-package schema version this app emits.
    static let schemaVersion = "1.0.0"

    /// Build a `Shot` from a captured frame and the user's pin, staging the
    /// shot's RGB (and depth, if present) media into `exportDirectory`.
    static func makeShot(
        from frame: CapturedFrame,
        level: Level,
        elevationId: String?,
        pin: Pin,
        exportDirectory: URL
    ) throws -> Shot {
        let shotId = UUID().uuidString
        let base = "shots/\(shotId)"

        // Stage RGB.
        let rgbRel = try BundleIO.stageMedia(
            frame.rgbJPEG,
            relativePath: "\(base)/rgb.jpg",
            in: exportDirectory
        )

        // Stage depth, if the device produced LiDAR depth.
        var depthRel: String?
        var depthSize: [Int]?
        if let depth = frame.depthFloat32, let size = frame.depthSize {
            depthRel = try BundleIO.stageMedia(
                depth,
                relativePath: "\(base)/depth.f32",
                in: exportDirectory
            )
            depthSize = [size.height, size.width]
        }

        return Shot(
            id: shotId,
            levelId: level.id,
            elevationId: elevationId,
            rgbImage: rgbRel,
            depthMap: depthRel,
            depthSize: depthSize,
            pointCloud: nil,
            intrinsics: frame.intrinsics,
            pose: frame.pose,
            pin: pin,
            capturedAt: frame.capturedAt,
            observations: nil
        )
    }

    /// Assemble all session shots into a `CapturePackage` and write it (JSON +
    /// already-staged media) to `exportDirectory`. Returns the package
    /// directory URL to hand to the share sheet.
    @discardableResult
    static func exportPackage(
        shots: [Shot],
        projectId: String,
        exportDirectory: URL
    ) throws -> URL {
        let package = CapturePackage(
            schemaVersion: schemaVersion,
            projectId: projectId,
            capturedAt: ISO8601DateFormatter().string(from: Date()),
            deviceModel: deviceModelName(),
            appVersion: appVersion(),
            shots: shots
        )
        // Media for each shot was staged during makeShot, so validation passes.
        try BundleIO.writeCapturePackage(package, to: exportDirectory)
        return exportDirectory
    }

    /// A per-session export directory under the app's Documents folder.
    static func sessionExportDirectory() -> URL {
        let documents = FileManager.default
            .urls(for: .documentDirectory, in: .userDomainMask)[0]
        // One directory per session; reused across shots within a session.
        return documents.appendingPathComponent("CaptureExport", isDirectory: true)
    }

    // MARK: - Device metadata

    private static func deviceModelName() -> String {
        #if canImport(UIKit)
        return UIDevice.current.modelIdentifierString
        #else
        return "unknown"
        #endif
    }

    private static func appVersion() -> String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "0.0.0"
        let build = info?["CFBundleVersion"] as? String ?? "0"
        return "\(version) (\(build))"
    }
}

#if canImport(UIKit)
import UIKit

extension UIDevice {
    /// Hardware model identifier (e.g. "iPhone16,1"). The engine maps this to a
    /// marketing name if needed; we send the raw identifier for fidelity.
    var modelIdentifierString: String {
        var systemInfo = utsname()
        uname(&systemInfo)
        let mirror = Mirror(reflecting: systemInfo.machine)
        return mirror.children.reduce(into: "") { result, element in
            guard let value = element.value as? Int8, value != 0 else { return }
            result.append(Character(UnicodeScalar(UInt8(value))))
        }
    }
}
#endif

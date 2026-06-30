//
//  CapturePackage.swift
//  CaElevationKit
//
//  Codable models for the OUTGOING capture package: the payload the phone
//  exports back to the desktop after a field walk. Per shot it carries the RGB
//  image, an optional LiDAR depth map (or derived point cloud), ARKit camera
//  intrinsics + pose, and the user's floorplan pin + heading -- the
//  georeference anchor.
//
//  These types mirror EXACTLY the engine's JSON schema:
//      engine/src/ca_elevation_engine/schemas/capture_package.schema.json
//
//  Pure Foundation. No ARKit. The app layer (CaElevationApp/CaptureExporter)
//  fills these in from live ARFrames; this package only knows the wire format.
//

import Foundation

// MARK: - Package root

/// Top-level capture package. One of the two payloads the engine ingests.
public struct CapturePackage: Codable, Equatable, Sendable {
    public var schemaVersion: String
    /// Must match the manifest `project.id`.
    public var projectId: String
    /// RFC 3339 / ISO 8601 date-time string. Kept as `String` to round-trip the
    /// wire format byte-for-byte.
    public var capturedAt: String?
    /// e.g. `"iPhone 15 Pro"`.
    public var deviceModel: String?
    public var appVersion: String?
    public var shots: [Shot]

    public init(
        schemaVersion: String,
        projectId: String,
        capturedAt: String? = nil,
        deviceModel: String? = nil,
        appVersion: String? = nil,
        shots: [Shot]
    ) {
        self.schemaVersion = schemaVersion
        self.projectId = projectId
        self.capturedAt = capturedAt
        self.deviceModel = deviceModel
        self.appVersion = appVersion
        self.shots = shots
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case projectId = "project_id"
        case capturedAt = "captured_at"
        case deviceModel = "device_model"
        case appVersion = "app_version"
        case shots
    }
}

// MARK: - Shot

public struct Shot: Codable, Equatable, Sendable {
    public var id: String
    public var levelId: String
    /// Optional user-tagged target elevation / wall.
    public var elevationId: String?
    /// Relative path to the RGB image inside the bundle directory.
    public var rgbImage: String
    /// Relative path to a raw float32 depth map (meters), row-major HxW.
    public var depthMap: String?
    /// `[height, width]` of the depth map; required if `depthMap` is present.
    public var depthSize: [Int]?
    /// Relative path to an E57/PLY point cloud, an alternative to `depthMap`.
    public var pointCloud: String?
    public var intrinsics: Intrinsics
    /// 4x4 row-major camera-to-world transform in ARKit's world frame
    /// (right-handed, -Z forward, +Y up). Exactly 16 elements.
    public var pose: [Double]
    public var pin: Pin
    public var capturedAt: String?
    /// Optional pre-extracted device observations (synthetic fixtures / vision
    /// backend output channel). Not produced by the v1 capture app.
    public var observations: [ShotObservation]?

    public init(
        id: String,
        levelId: String,
        elevationId: String? = nil,
        rgbImage: String,
        depthMap: String? = nil,
        depthSize: [Int]? = nil,
        pointCloud: String? = nil,
        intrinsics: Intrinsics,
        pose: [Double],
        pin: Pin,
        capturedAt: String? = nil,
        observations: [ShotObservation]? = nil
    ) {
        self.id = id
        self.levelId = levelId
        self.elevationId = elevationId
        self.rgbImage = rgbImage
        self.depthMap = depthMap
        self.depthSize = depthSize
        self.pointCloud = pointCloud
        self.intrinsics = intrinsics
        self.pose = pose
        self.pin = pin
        self.capturedAt = capturedAt
        self.observations = observations
    }

    enum CodingKeys: String, CodingKey {
        case id
        case levelId = "level_id"
        case elevationId = "elevation_id"
        case rgbImage = "rgb_image"
        case depthMap = "depth_map"
        case depthSize = "depth_size"
        case pointCloud = "point_cloud"
        case intrinsics
        case pose
        case pin
        case capturedAt = "captured_at"
        case observations
    }
}

// MARK: - Intrinsics

/// Pinhole camera intrinsics, in the RGB image's pixel coordinate frame.
public struct Intrinsics: Codable, Equatable, Sendable {
    public var fx: Double
    public var fy: Double
    public var cx: Double
    public var cy: Double
    public var width: Int
    public var height: Int

    public init(fx: Double, fy: Double, cx: Double, cy: Double, width: Int, height: Int) {
        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy
        self.width = width
        self.height = height
    }
}

// MARK: - Pin (the georeference anchor)

/// User-placed georeference anchor: the floorplan pixel where the operator
/// stood plus the camera heading. This is the one piece of hard-to-automate
/// input only a person can supply quickly (see design.md, "the floorplan pin
/// as georeference anchor").
public struct Pin: Codable, Equatable, Sendable {
    public enum Confidence: String, Codable, Sendable {
        case low, medium, high
    }

    /// Floorplan pixel x of operator position.
    public var x: Double
    /// Floorplan pixel y of operator position.
    public var y: Double
    /// Camera heading in plan, degrees, 0 = +X CCW.
    public var heading: Double
    /// Defaults to `.medium`, mirroring the engine (`Pin.confidence: str =
    /// "medium"`) and the schema's `"default": "medium"`. A payload that omits
    /// it decodes to `.medium` on both sides rather than silently diverging
    /// (kit `nil` vs engine `"medium"`); the encoder always emits it.
    public var confidence: Confidence

    public init(x: Double, y: Double, heading: Double, confidence: Confidence = .medium) {
        self.x = x
        self.y = y
        self.heading = heading
        self.confidence = confidence
    }

    enum CodingKeys: String, CodingKey {
        case x, y, heading, confidence
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        x = try container.decode(Double.self, forKey: .x)
        y = try container.decode(Double.self, forKey: .y)
        heading = try container.decode(Double.self, forKey: .heading)
        confidence = try container.decodeIfPresent(Confidence.self, forKey: .confidence) ?? .medium
    }
}

// MARK: - ShotObservation (passthrough; not produced by v1 capture)

public struct ShotObservation: Codable, Equatable, Sendable {
    public var position: Point3
    public var mountingHeight: Double?
    public var facingAngle: Double?
    public var detectedType: String?
    /// 0...1.
    public var typeConfidence: Double?

    public init(
        position: Point3,
        mountingHeight: Double? = nil,
        facingAngle: Double? = nil,
        detectedType: String? = nil,
        typeConfidence: Double? = nil
    ) {
        self.position = position
        self.mountingHeight = mountingHeight
        self.facingAngle = facingAngle
        self.detectedType = detectedType
        self.typeConfidence = typeConfidence
    }

    enum CodingKeys: String, CodingKey {
        case position
        case mountingHeight = "mounting_height"
        case facingAngle = "facing_angle"
        case detectedType = "detected_type"
        case typeConfidence = "type_confidence"
    }
}

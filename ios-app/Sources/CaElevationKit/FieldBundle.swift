//
//  FieldBundle.swift
//  CaElevationKit
//
//  Codable models for the INCOMING field bundle (the "spec manifest"): the
//  payload the Revit add-in exports for the phone. It carries the project,
//  the levels with their floorplan image + plan-pixel-to-model affine, and the
//  expected devices.
//
//  These types mirror EXACTLY the engine's JSON schema:
//      engine/src/ca_elevation_engine/schemas/spec_manifest.schema.json
//  Field names use snake_case via explicit CodingKeys so the on-disk JSON is
//  byte-identical to what the engine and add-in produce/consume.
//
//  Pure Foundation. No UIKit / ARKit. Headlessly testable.
//

import Foundation

// MARK: - Manifest root

/// Top-level spec manifest. One of the two payloads the engine ingests.
public struct SpecManifest: Codable, Equatable, Sendable {
    /// Semantic version of the manifest format, e.g. `"1.0.0"`.
    public var schemaVersion: String
    public var project: Project
    public var coordinateSystem: CoordinateSystem?
    /// Project-wide default pass/flag thresholds; per-device tolerances override.
    public var defaultTolerances: Tolerances?
    public var levels: [Level]
    public var devices: [Device]

    public init(
        schemaVersion: String,
        project: Project,
        coordinateSystem: CoordinateSystem? = nil,
        defaultTolerances: Tolerances? = nil,
        levels: [Level],
        devices: [Device] = []
    ) {
        self.schemaVersion = schemaVersion
        self.project = project
        self.coordinateSystem = coordinateSystem
        self.defaultTolerances = defaultTolerances
        self.levels = levels
        self.devices = devices
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case project
        case coordinateSystem = "coordinate_system"
        case defaultTolerances = "default_tolerances"
        case levels
        case devices
    }
}

// MARK: - Project

public struct Project: Codable, Equatable, Sendable {
    public enum Units: String, Codable, Sendable {
        case feet
        case meters
    }

    public var id: String
    public var name: String
    public var revitFile: String?
    /// RFC 3339 / ISO 8601 date-time string, kept as `String` to round-trip the
    /// wire format byte-for-byte rather than reformatting through `Date`.
    public var exportedAt: String?
    public var units: Units

    public init(
        id: String,
        name: String,
        revitFile: String? = nil,
        exportedAt: String? = nil,
        units: Units
    ) {
        self.id = id
        self.name = name
        self.revitFile = revitFile
        self.exportedAt = exportedAt
        self.units = units
    }

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case revitFile = "revit_file"
        case exportedAt = "exported_at"
        case units
    }
}

// MARK: - Coordinate system

public struct CoordinateSystem: Codable, Equatable, Sendable {
    public var name: String?
    /// Angle of project north relative to true north, degrees.
    public var northAngle: Double?

    public init(name: String? = nil, northAngle: Double? = nil) {
        self.name = name
        self.northAngle = northAngle
    }

    enum CodingKeys: String, CodingKey {
        case name
        case northAngle = "north_angle"
    }
}

// MARK: - Tolerances

/// Pass/flag thresholds. `position` / `mountingHeight` in project units;
/// `orientation` in degrees.
public struct Tolerances: Codable, Equatable, Sendable {
    public var position: Double?
    public var mountingHeight: Double?
    public var orientation: Double?

    public init(position: Double? = nil, mountingHeight: Double? = nil, orientation: Double? = nil) {
        self.position = position
        self.mountingHeight = mountingHeight
        self.orientation = orientation
    }

    enum CodingKeys: String, CodingKey {
        case position
        case mountingHeight = "mounting_height"
        case orientation
    }
}

// MARK: - Level + floorplan

public struct Level: Codable, Equatable, Sendable {
    public var id: String
    public var name: String
    /// Z height of the finished floor for this level, project units.
    public var elevation: Double
    public var floorplan: Floorplan

    public init(id: String, name: String, elevation: Double, floorplan: Floorplan) {
        self.id = id
        self.name = name
        self.elevation = elevation
        self.floorplan = floorplan
    }
}

public struct Floorplan: Codable, Equatable, Sendable {
    /// Relative path to the floorplan image inside the bundle directory.
    public var image: String
    public var widthPx: Int
    public var heightPx: Int
    /// 2x3 row-major affine mapping plan pixel `(px,py,1)` -> model `(X,Y)`.
    /// `[a,b,c, d,e,f]` => `X = a*px + b*py + c`, `Y = d*px + e*py + f`.
    /// Use ``Affine`` to evaluate it.
    public var pixelToModel: [Double]

    public init(image: String, widthPx: Int, heightPx: Int, pixelToModel: [Double]) {
        self.image = image
        self.widthPx = widthPx
        self.heightPx = heightPx
        self.pixelToModel = pixelToModel
    }

    /// Convenience: the floorplan affine as an ``Affine`` value.
    public var affine: Affine { Affine(coefficients: pixelToModel) }

    enum CodingKeys: String, CodingKey {
        case image
        case widthPx = "width_px"
        case heightPx = "height_px"
        case pixelToModel = "pixel_to_model"
    }
}

// MARK: - Device

public struct Device: Codable, Equatable, Sendable {
    public var id: String
    public var family: String
    public var type: String
    public var levelId: String
    /// Which elevation / wall view this device belongs to.
    public var elevationId: String?
    public var position: Point3
    /// Height above finished floor, project units. If omitted the engine derives
    /// it from `position.z - level.elevation`.
    public var mountingHeight: Double?
    public var orientation: Orientation?
    public var tolerances: Tolerances?
    /// Free-form passthrough metadata. Decoded lazily as JSON so unknown keys
    /// survive a round-trip.
    public var metadata: JSONValue?

    public init(
        id: String,
        family: String,
        type: String,
        levelId: String,
        elevationId: String? = nil,
        position: Point3,
        mountingHeight: Double? = nil,
        orientation: Orientation? = nil,
        tolerances: Tolerances? = nil,
        metadata: JSONValue? = nil
    ) {
        self.id = id
        self.family = family
        self.type = type
        self.levelId = levelId
        self.elevationId = elevationId
        self.position = position
        self.mountingHeight = mountingHeight
        self.orientation = orientation
        self.tolerances = tolerances
        self.metadata = metadata
    }

    enum CodingKeys: String, CodingKey {
        case id
        case family
        case type
        case levelId = "level_id"
        case elevationId = "elevation_id"
        case position
        case mountingHeight = "mounting_height"
        case orientation
        case tolerances
        case metadata
    }
}

public struct Orientation: Codable, Equatable, Sendable {
    public enum UpAxis: String, Codable, Sendable {
        case up, down, left, right
    }

    /// Heading in plan the device faces, degrees, 0 = +X CCW.
    public var facingAngle: Double?
    public var upAxis: UpAxis?

    public init(facingAngle: Double? = nil, upAxis: UpAxis? = nil) {
        self.facingAngle = facingAngle
        self.upAxis = upAxis
    }

    enum CodingKeys: String, CodingKey {
        case facingAngle = "facing_angle"
        case upAxis = "up_axis"
    }
}

// MARK: - Shared geometry

/// A model-space point. Shared by the manifest and the capture package.
public struct Point3: Codable, Equatable, Sendable {
    public var x: Double
    public var y: Double
    public var z: Double

    public init(x: Double, y: Double, z: Double) {
        self.x = x
        self.y = y
        self.z = z
    }
}

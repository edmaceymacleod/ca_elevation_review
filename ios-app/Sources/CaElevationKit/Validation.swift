//
//  Validation.swift
//  CaElevationKit
//
//  Runtime content validation for the decoded wire models. The engine JSON
//  Schemas (engine/src/ca_elevation_engine/schemas/*.json) impose constraints
//  that Swift's Codable cannot express on its own -- array lengths, numeric
//  positivity, a semver pattern, non-empty IDs, the depth_map -> depth_size
//  dependency, and the floorplan affine's 6-tuple length. Codable happily
//  decodes a 15-element pose, a 5-element pixel_to_model, or an empty shots
//  array; these checks fail such payloads CLOSED so a malformed bundle is
//  rejected here rather than corrupting a downstream registration -- or, for a
//  short affine, trapping later in Affine.modelXY's precondition.
//
//  Pure Foundation. Headlessly testable.
//

import Foundation

/// A schema constraint violated by an otherwise-decodable payload.
public enum BundleValidationError: Error, Equatable, Sendable {
    /// `schema_version` did not match `^\d+\.\d+\.\d+$`.
    case schemaVersionNotSemver(String)
    /// A `minLength: 1` identifier was empty. `field` names which one.
    case emptyIdentifier(field: String)
    /// `shots` was empty (schema `minItems: 1`).
    case emptyShots
    /// `levels` was empty (schema `minItems: 1`).
    case emptyLevels
    /// `pose` was not exactly 16 elements.
    case poseWrongLength(count: Int)
    /// An intrinsic that must be `> 0` was not. `field` is fx/fy/width/height.
    case nonPositiveIntrinsic(field: String, value: Double)
    /// `depth_size` was present but not exactly 2 elements.
    case depthSizeWrongLength(count: Int)
    /// A `depth_size` element was `<= 0` (schema `exclusiveMinimum: 0`).
    case depthSizeNonPositive(value: Int)
    /// `depth_map` was present without the required `depth_size`.
    case depthMapWithoutSize(shotId: String)
    /// `floorplan.pixel_to_model` was not exactly 6 elements (schema
    /// `minItems/maxItems: 6`; engine `models.py:135`). A short affine would
    /// otherwise trap in ``Affine/modelXY(fromPixel:_:)``'s precondition.
    case affineWrongLength(count: Int)
    /// `floorplan.width_px` / `height_px` was `<= 0` (schema
    /// `exclusiveMinimum: 0`). `field` is width_px/height_px.
    case nonPositiveFloorplanDimension(field: String, value: Int)
}

/// `^\d+\.\d+\.\d+$` -- the schema's semantic-version pattern.
private let semverPattern = "^[0-9]+\\.[0-9]+\\.[0-9]+$"

private func requireSemver(_ value: String) throws {
    guard value.range(of: semverPattern, options: .regularExpression) != nil else {
        throw BundleValidationError.schemaVersionNotSemver(value)
    }
}

private func requireNonEmpty(_ value: String, field: String) throws {
    guard !value.isEmpty else {
        throw BundleValidationError.emptyIdentifier(field: field)
    }
}

extension CapturePackage {
    /// Validate the package against the schema constraints Codable cannot
    /// enforce. Throws ``BundleValidationError`` on the first violation.
    public func validate() throws {
        try requireSemver(schemaVersion)
        try requireNonEmpty(projectId, field: "project_id")
        guard !shots.isEmpty else { throw BundleValidationError.emptyShots }
        for shot in shots {
            try shot.validate()
        }
    }
}

extension Shot {
    func validate() throws {
        try requireNonEmpty(id, field: "shot.id")
        guard pose.count == 16 else {
            throw BundleValidationError.poseWrongLength(count: pose.count)
        }
        try intrinsics.validate()
        if let size = depthSize {
            guard size.count == 2 else {
                throw BundleValidationError.depthSizeWrongLength(count: size.count)
            }
            for dimension in size where dimension <= 0 {
                throw BundleValidationError.depthSizeNonPositive(value: dimension)
            }
        }
        if depthMap != nil, depthSize == nil {
            throw BundleValidationError.depthMapWithoutSize(shotId: id)
        }
    }
}

extension Intrinsics {
    func validate() throws {
        guard fx > 0 else {
            throw BundleValidationError.nonPositiveIntrinsic(field: "fx", value: fx)
        }
        guard fy > 0 else {
            throw BundleValidationError.nonPositiveIntrinsic(field: "fy", value: fy)
        }
        guard width > 0 else {
            throw BundleValidationError.nonPositiveIntrinsic(field: "width", value: Double(width))
        }
        guard height > 0 else {
            throw BundleValidationError.nonPositiveIntrinsic(field: "height", value: Double(height))
        }
    }
}

extension SpecManifest {
    /// Validate the manifest against the schema constraints Codable cannot
    /// enforce. Throws ``BundleValidationError`` on the first violation.
    public func validate() throws {
        try requireSemver(schemaVersion)
        try requireNonEmpty(project.id, field: "project.id")
        guard !levels.isEmpty else { throw BundleValidationError.emptyLevels }
        for level in levels {
            try level.validate()
        }
        for device in devices {
            try requireNonEmpty(device.id, field: "device.id")
        }
    }
}

extension Level {
    func validate() throws {
        try requireNonEmpty(id, field: "level.id")
        try floorplan.validate()
    }
}

extension Floorplan {
    func validate() throws {
        guard widthPx > 0 else {
            throw BundleValidationError.nonPositiveFloorplanDimension(field: "width_px", value: widthPx)
        }
        guard heightPx > 0 else {
            throw BundleValidationError.nonPositiveFloorplanDimension(field: "height_px", value: heightPx)
        }
        guard pixelToModel.count == 6 else {
            throw BundleValidationError.affineWrongLength(count: pixelToModel.count)
        }
    }
}

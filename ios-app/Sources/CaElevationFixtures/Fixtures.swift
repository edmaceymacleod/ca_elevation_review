//
//  Fixtures.swift
//  CaElevationFixtures
//
//  ONE canonical, schema-valid sample of each wire payload, built through the
//  kit's public initializers. Shared by the XCTest round-trip suite and the
//  `cek-emit` executable so there is a SINGLE definition of "a valid package /
//  manifest" -- the round-tripped value and the cross-checked value can never
//  drift apart.
//
//  The samples are deliberately RICH: every optional field is populated so each
//  snake_case CodingKey reaches the wire. The engine schemas use
//  `additionalProperties: false`, so the kit<->engine cross-check (cek-emit +
//  the xlang_schema CI job) rejects a mis-cased or stray key on any populated
//  field.
//
//  Pure Foundation. No UIKit / ARKit -- keep it so, or the kit's Linux/Windows
//  CI legs (which compile this target) break.
//

import CaElevationKit
import Foundation

/// Canonical, schema-valid wire-payload samples shared by tests and `cek-emit`.
public enum Fixtures {
    /// A rich, schema-valid `CapturePackage`: one shot carrying RGB + depth
    /// (with `depth_size`) + point cloud, full intrinsics, a 16-element
    /// row-major pose, a high-confidence pin, and one fully-populated
    /// observation -- so every `CapturePackage` / `Shot` / `ShotObservation`
    /// CodingKey is exercised on the wire.
    public static func capturePackage() -> CapturePackage {
        let observation = ShotObservation(
            position: Point3(x: 1.0, y: 2.0, z: 3.0),
            mountingHeight: 4.0,
            facingAngle: 90.0,
            detectedType: "Horn Strobe",
            typeConfidence: 0.9
        )
        let shot = Shot(
            id: "shot-1",
            levelId: "L1",
            elevationId: "E-North",
            rgbImage: "shots/shot-1/rgb.jpg",
            depthMap: "shots/shot-1/depth.bin",
            depthSize: [192, 256],
            pointCloud: "shots/shot-1/cloud.ply",
            intrinsics: Intrinsics(fx: 1450.2, fy: 1450.2, cx: 960, cy: 720, width: 1920, height: 1440),
            pose: [
                1, 0, 0, 1.5,
                0, 1, 0, 0.2,
                0, 0, 1, -3.0,
                0, 0, 0, 1
            ],
            pin: Pin(x: 512.5, y: 384.0, heading: 90, confidence: .high),
            capturedAt: "2026-06-28T12:34:56Z",
            observations: [observation]
        )
        return CapturePackage(
            schemaVersion: "1.0.0",
            projectId: "proj-001",
            capturedAt: "2026-06-28T12:35:00Z",
            deviceModel: "iPhone 15 Pro",
            appVersion: "0.1.0",
            shots: [shot]
        )
    }

    /// A rich, schema-valid `SpecManifest`: a project, a coordinate system,
    /// default tolerances, one level with a floorplan + 6-element affine, and
    /// one fully-populated device (orientation, tolerances, metadata) -- so
    /// every manifest CodingKey is exercised on the wire.
    public static func specManifest() -> SpecManifest {
        SpecManifest(
            schemaVersion: "1.0.0",
            project: Project(
                id: "proj-001",
                name: "Demo Building",
                revitFile: "Demo.rvt",
                exportedAt: "2026-06-28T12:00:00Z",
                units: .feet
            ),
            coordinateSystem: CoordinateSystem(name: "Project", northAngle: 0),
            defaultTolerances: Tolerances(position: 0.1, mountingHeight: 0.05, orientation: 5),
            levels: [
                Level(
                    id: "L1",
                    name: "Level 1",
                    elevation: 0,
                    floorplan: Floorplan(
                        image: "plans/L1.png",
                        widthPx: 2048,
                        heightPx: 1536,
                        pixelToModel: [0.01, 0, -5, 0, -0.01, 7.5]
                    )
                )
            ],
            devices: [
                Device(
                    id: "dev-1",
                    family: "Fire Alarm",
                    type: "Horn Strobe",
                    levelId: "L1",
                    elevationId: "E-North",
                    position: Point3(x: 1.0, y: 2.0, z: 3.0),
                    mountingHeight: 7.5,
                    orientation: Orientation(facingAngle: 90, upAxis: .up),
                    tolerances: Tolerances(position: 0.1, mountingHeight: 0.05, orientation: 5),
                    metadata: .object(["note": .string("sample")])
                )
            ]
        )
    }
}

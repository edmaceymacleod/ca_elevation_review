//
//  Affine.swift
//  CaElevationKit
//
//  The plan-pixel-to-model affine helper. Mirrors the engine's convention
//  (engine/src/ca_elevation_engine/geometry.py): a 2x3 row-major affine
//  `[a,b,c, d,e,f]` mapping a floorplan pixel `(px,py)` to model `(X,Y)` via
//
//      X = a*px + b*py + c
//      Y = d*px + e*py + f
//
//  Pure math. No platform dependency. Headlessly testable -- this is the math
//  that turns the user's floorplan pin into model coordinates for the engine.
//

import Foundation

/// A 2x3 row-major affine `[a,b,c, d,e,f]` mapping plan pixels to model XY.
public struct Affine: Equatable, Sendable {
    /// `[a, b, c, d, e, f]`, exactly 6 coefficients (row-major).
    public let coefficients: [Double]

    /// Creates an affine from 6 row-major coefficients. Coefficient arrays of
    /// any other length are accepted but ``isValid`` reports them invalid and
    /// the map functions trap, matching the engine's strict 6-tuple unpack.
    public init(coefficients: [Double]) {
        self.coefficients = coefficients
    }

    public init(a: Double, b: Double, c: Double, d: Double, e: Double, f: Double) {
        self.coefficients = [a, b, c, d, e, f]
    }

    /// The identity pixel->model affine (model == pixel coordinates).
    public static let identity = Affine(a: 1, b: 0, c: 0, d: 0, e: 1, f: 0)

    /// True iff exactly 6 coefficients are present.
    public var isValid: Bool { coefficients.count == 6 }

    /// Map a floorplan pixel `(px, py)` to model `(X, Y)`.
    ///
    /// - Precondition: ``isValid`` is `true`.
    public func modelXY(fromPixel px: Double, _ py: Double) -> (x: Double, y: Double) {
        precondition(isValid, "Affine requires exactly 6 coefficients")
        let a = coefficients[0], b = coefficients[1], c = coefficients[2]
        let d = coefficients[3], e = coefficients[4], f = coefficients[5]
        return (a * px + b * py + c, d * px + e * py + f)
    }

    /// Map a `Pin`'s pixel coordinate to model `(X, Y)`.
    public func modelXY(fromPixel pin: Pin) -> (x: Double, y: Double) {
        modelXY(fromPixel: pin.x, pin.y)
    }

    /// Determinant of the linear (2x2) part. Zero => singular / non-invertible.
    public var determinant: Double {
        guard isValid else { return 0 }
        let a = coefficients[0], b = coefficients[1]
        let d = coefficients[3], e = coefficients[4]
        return a * e - b * d
    }

    /// Inverse map model `(X, Y)` -> floorplan pixel `(px, py)`.
    ///
    /// Returns `nil` if the affine is singular. Mirrors the engine's
    /// `model_xy_to_pixel`.
    public func pixel(fromModelX x: Double, _ y: Double) -> (px: Double, py: Double)? {
        guard isValid else { return nil }
        let a = coefficients[0], b = coefficients[1], c = coefficients[2]
        let d = coefficients[3], e = coefficients[4], f = coefficients[5]
        let det = a * e - b * d
        // Match the engine (geometry.py model_xy_to_pixel): reject near-singular
        // affines, not just exactly-zero determinants.
        guard abs(det) >= 1e-12 else { return nil }
        let dx = x - c
        let dy = y - f
        let px = (e * dx - b * dy) / det
        let py = (-d * dx + a * dy) / det
        return (px, py)
    }

    /// Approximate model-units-per-pixel (geometric mean of the two axis
    /// scales). Mirrors the engine's `affine_scale`. Useful for sizing the pin
    /// marker / heading arrow in model terms.
    public var scale: Double {
        guard isValid else { return 0 }
        let a = coefficients[0], b = coefficients[1]
        let d = coefficients[3], e = coefficients[4]
        let sx = (a * a + d * d).squareRoot()
        let sy = (b * b + e * e).squareRoot()
        return (sx * sy).squareRoot()
    }
}

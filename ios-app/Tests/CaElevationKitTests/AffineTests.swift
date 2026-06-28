import XCTest
@testable import CaElevationKit

final class AffineTests: XCTestCase {
    func testIdentityMapsPixelToItself() {
        let (x, y) = Affine.identity.modelXY(fromPixel: 12.5, -3.0)
        XCTAssertEqual(x, 12.5, accuracy: 1e-12)
        XCTAssertEqual(y, -3.0, accuracy: 1e-12)
    }

    func testRowMajorConventionMatchesEngine() {
        // [a,b,c, d,e,f] => X=a*px+b*py+c, Y=d*px+e*py+f
        let affine = Affine(a: 2, b: 0, c: 10, d: 0, e: -3, f: 5)
        let (x, y) = affine.modelXY(fromPixel: 4, 6)
        XCTAssertEqual(x, 2 * 4 + 10, accuracy: 1e-12)   // 18
        XCTAssertEqual(y, -3 * 6 + 5, accuracy: 1e-12)   // -13
    }

    func testShearedAffineUsesCrossTerms() {
        let affine = Affine(coefficients: [1.5, 0.5, -2, 0.25, 2, 7])
        let (x, y) = affine.modelXY(fromPixel: 10, 8)
        XCTAssertEqual(x, 1.5 * 10 + 0.5 * 8 - 2, accuracy: 1e-12)
        XCTAssertEqual(y, 0.25 * 10 + 2 * 8 + 7, accuracy: 1e-12)
    }

    func testInverseRoundTrips() {
        let affine = Affine(coefficients: [1.5, 0.5, -2, 0.25, 2, 7])
        let (x, y) = affine.modelXY(fromPixel: 10, 8)
        let inverse = affine.pixel(fromModelX: x, y)
        XCTAssertNotNil(inverse)
        XCTAssertEqual(inverse!.px, 10, accuracy: 1e-9)
        XCTAssertEqual(inverse!.py, 8, accuracy: 1e-9)
    }

    func testSingularAffineHasNoInverse() {
        // Linear part collapses to a line (det == 0).
        let singular = Affine(a: 1, b: 2, c: 0, d: 2, e: 4, f: 0)
        XCTAssertEqual(singular.determinant, 0, accuracy: 1e-12)
        XCTAssertNil(singular.pixel(fromModelX: 1, 1))
    }

    func testMapFromPin() {
        let affine = Affine(a: 2, b: 0, c: 0, d: 0, e: 2, f: 0)
        let pin = Pin(x: 3, y: 4, heading: 90)
        let (x, y) = affine.modelXY(fromPixel: pin)
        XCTAssertEqual(x, 6, accuracy: 1e-12)
        XCTAssertEqual(y, 8, accuracy: 1e-12)
    }

    func testValidityReporting() {
        XCTAssertTrue(Affine(coefficients: [1, 0, 0, 0, 1, 0]).isValid)
        XCTAssertFalse(Affine(coefficients: [1, 0, 0]).isValid)
    }
}

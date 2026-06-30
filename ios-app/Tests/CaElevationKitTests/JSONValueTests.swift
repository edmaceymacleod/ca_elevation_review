import XCTest
@testable import CaElevationKit

final class JSONValueTests: XCTestCase {
    /// A decoder built via `BundleIO.makeDecoder()` has the nesting-depth guard
    /// installed (that is the decoder used for all manifest/capture reads).
    private func guardedDecoder() -> JSONDecoder {
        BundleIO.makeDecoder()
    }

    func testDecodesNestedValueWithinLimit() throws {
        // Nest arrays a little under the limit; this must decode fine.
        let depth = 64
        let json = String(repeating: "[", count: depth) + String(repeating: "]", count: depth)
        let value = try guardedDecoder().decode(JSONValue.self, from: Data(json.utf8))

        // Walk down the nested arrays to confirm the structure round-tripped.
        var current = value
        var counted = 0
        while case .array(let inner) = current, let first = inner.first {
            current = first
            counted += 1
        }
        // The innermost level is an empty array, so we descend depth-1 times.
        XCTAssertEqual(counted, depth - 1)
    }

    func testDecodeThrowsPastMaxDepth() {
        // Nest far past the limit: must throw (a catchable DecodingError) rather
        // than recurse unbounded and overflow the stack.
        let depth = JSONValue.maxDecodingDepth + 50
        let json = String(repeating: "[", count: depth) + String(repeating: "]", count: depth)

        XCTAssertThrowsError(
            try guardedDecoder().decode(JSONValue.self, from: Data(json.utf8))
        ) { error in
            XCTAssertTrue(error is DecodingError, "expected DecodingError, got \(error)")
        }
    }

    func testDepthGuardResetsBetweenDecodes() throws {
        // The shared counter is balanced back to zero after each decode (even on
        // throw), so reusing one decoder for several documents is safe.
        let decoder = guardedDecoder()
        let shallow = Data("[[1]]".utf8)

        let tooDeep = Data(
            (String(repeating: "[", count: JSONValue.maxDecodingDepth + 10)
                + String(repeating: "]", count: JSONValue.maxDecodingDepth + 10)).utf8
        )
        XCTAssertThrowsError(try decoder.decode(JSONValue.self, from: tooDeep))

        // A subsequent shallow decode must still succeed on the same decoder.
        let value = try decoder.decode(JSONValue.self, from: shallow)
        guard case .array = value else {
            return XCTFail("expected array, got \(value)")
        }
    }
}

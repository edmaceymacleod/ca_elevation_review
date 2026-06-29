//
//  JSONValue.swift
//  CaElevationKit
//
//  A minimal recursive JSON value, used for the manifest's free-form
//  `device.metadata` object so that unknown keys round-trip losslessly without
//  the kit needing to know their shape.
//
//  Pure Foundation. Headlessly testable.
//

import Foundation

/// A type-erased JSON value that decodes/encodes any JSON `object` payload.
public enum JSONValue: Codable, Equatable, Sendable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    /// Maximum array/object nesting depth accepted by ``init(from:)``.
    ///
    /// `device.metadata` is decoded from `manifest.json` files in an externally-
    /// synced (OneDrive / File Provider) folder, so the payload is untrusted. A
    /// pathologically deep blob would otherwise recurse without bound and overflow
    /// the stack — an uncatchable trap that crashes the whole library scan rather
    /// than failing one bundle. Bounding the depth turns that into a normal
    /// `DecodingError` the per-bundle `do/catch` can skip. 128 is far deeper than
    /// any legitimate metadata object.
    public static let maxDecodingDepth = 128

    /// `CodingUserInfoKey` under which ``init(from:)`` threads a shared nesting
    /// counter through `decoder.userInfo`. `JSONDecoder` propagates the same
    /// `userInfo` dictionary to every nested container, so a shared reference
    /// `DepthCounter` lets each recursion level see and bump the same count.
    /// Internal to this type.
    private static let depthKey = CodingUserInfoKey(rawValue: "JSONValue.decodingDepth")!

    /// Shared, mutable nesting counter passed by reference via `userInfo`.
    private final class DepthCounter {
        var depth = 0
    }

    /// Install a fresh nesting counter into a decoder's `userInfo` so nested
    /// ``JSONValue`` decoding enforces ``maxDecodingDepth``.
    ///
    /// `BundleIO.makeDecoder()` calls this so every manifest/capture decode is
    /// depth-bounded. Without it each recursion level would start a fresh counter
    /// and the bound wouldn't apply, so callers decoding `JSONValue` from an
    /// untrusted source should use a decoder prepared here.
    public static func installDepthGuard(on decoder: JSONDecoder) {
        decoder.userInfo[depthKey] = DepthCounter()
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else {
            // Arrays/objects recurse; bound the nesting depth so an over-nested
            // untrusted blob fails the decode instead of overflowing the stack.
            // The same `userInfo`-held counter is shared across all nested
            // decoders, so it tracks true depth even though `userInfo` itself is
            // read-only. Absent (e.g. decoding via a plain decoder), default to a
            // fresh counter so the guard still applies.
            let counter = (decoder.userInfo[Self.depthKey] as? DepthCounter) ?? DepthCounter()
            counter.depth += 1
            defer { counter.depth -= 1 }
            guard counter.depth <= Self.maxDecodingDepth else {
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "JSON nesting exceeds maximum depth of \(Self.maxDecodingDepth)"
                )
            }
            if let value = try? container.decode([JSONValue].self) {
                self = .array(value)
            } else if let value = try? container.decode([String: JSONValue].self) {
                self = .object(value)
            } else {
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "Unsupported JSON value"
                )
            }
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }
}

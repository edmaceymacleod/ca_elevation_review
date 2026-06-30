//
//  main.swift
//  cek-emit
//
//  Tiny Foundation-only CLI that emits the shared `Fixtures` wire payloads as
//  JSON so the engine's schema validator can check the Swift encoder against the
//  AUTHORITATIVE JSON Schemas (see the xlang_schema CI job and
//  scripts/win-xlang-check.ps1).
//
//  Usage:  cek-emit <output-dir> [stem]
//      <output-dir>  directory to write into (created if absent)
//      [stem]        filename stem, default "kit_sample"
//
//  Writes <output-dir>/<stem>.capture.json and <output-dir>/<stem>.manifest.json
//  -- the `.capture.json` / `.manifest.json` suffixes the engine validator maps
//  to capture_package.schema.json / spec_manifest.schema.json.
//
//  Encodes DIRECTLY with BundleIO.makeEncoder() rather than
//  BundleIO.writeCapturePackage(...) on purpose: that helper writes a file named
//  "capture.json" (which does NOT end with ".capture.json", so the validator
//  would skip it) and asserts referenced media exists (none does here).
//

import CaElevationFixtures
import CaElevationKit
import Foundation

func fail(_ message: String) -> Never {
    try? FileHandle.standardError.write(contentsOf: Data("cek-emit: \(message)\n".utf8))
    exit(1)
}

let arguments = CommandLine.arguments
guard arguments.count >= 2 else {
    fail("usage: cek-emit <output-dir> [stem]")
}

let outputDir = URL(fileURLWithPath: arguments[1], isDirectory: true)
let stem = arguments.count >= 3 ? arguments[2] : "kit_sample"
let encoder = BundleIO.makeEncoder()

do {
    try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)

    let captureURL = outputDir.appendingPathComponent("\(stem).capture.json")
    try encoder.encode(Fixtures.capturePackage()).write(to: captureURL, options: .atomic)
    print(captureURL.path)

    let manifestURL = outputDir.appendingPathComponent("\(stem).manifest.json")
    try encoder.encode(Fixtures.specManifest()).write(to: manifestURL, options: .atomic)
    print(manifestURL.path)
} catch {
    fail("failed to emit samples: \(error)")
}

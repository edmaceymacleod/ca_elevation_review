import XCTest
@testable import CaElevationKit

/// Covers `BundleIO.findBundles(in:)` — the library-root enumerator that lists
/// project subfolders (each holding a `manifest.json`) inside a synced folder
/// such as a OneDrive directory. Pure Foundation, so it runs headlessly on CI.
final class FindBundlesTests: XCTestCase {
    func testReturnsOnlySubdirsContainingAManifest() throws {
        let root = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: root) }

        // A valid bundle: a subdir with manifest.json.
        try makeBundle(named: "ProjectB", in: root)
        try makeBundle(named: "ProjectA", in: root)
        // A subdir WITHOUT a manifest — excluded.
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent("NotABundle"),
            withIntermediateDirectories: true
        )
        // A plain FILE at the top level — excluded (not a directory).
        try Data("x".utf8).write(to: root.appendingPathComponent("loose.txt"))

        let bundles = try BundleIO.findBundles(in: root)

        // Exactly the two real bundles, sorted by name (A before B).
        XCTAssertEqual(bundles.map(\.lastPathComponent), ["ProjectA", "ProjectB"])
    }

    func testEmptyRootReturnsEmpty() throws {
        let root = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: root) }

        XCTAssertEqual(try BundleIO.findBundles(in: root), [])
    }

    func testIsNonRecursive() throws {
        let root = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: root) }

        // manifest.json one level too deep: <root>/Group/Project/manifest.json.
        // The intermediate "Group" has no manifest of its own, so nothing matches.
        let group = root.appendingPathComponent("Group")
        try makeBundle(named: "Project", in: group)

        XCTAssertEqual(try BundleIO.findBundles(in: root), [])
    }

    func testNonExistentRootThrows() {
        let missing = FileManager.default.temporaryDirectory
            .appendingPathComponent("cek-missing-\(UUID().uuidString)")

        XCTAssertThrowsError(try BundleIO.findBundles(in: missing))
    }

    // MARK: - Helpers

    /// Create `<parent>/<name>/manifest.json` (contents are irrelevant — the
    /// enumerator only checks for the file's existence).
    private func makeBundle(named name: String, in parent: URL) throws {
        let dir = parent.appendingPathComponent(name)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: dir.appendingPathComponent(BundleIO.manifestFileName))
    }

    private func makeTempDir() throws -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cek-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }
}

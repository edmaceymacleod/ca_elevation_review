//
//  ProjectLibrary.swift
//  CaElevationApp
//
//  The model behind the multi-project picker. It points at one library root (a
//  folder synced onto the phone by OneDrive and chosen once via the document
//  picker), lists the field bundles inside it, and caches their thumbnails.
//
//  Ownership boundaries:
//   - Bookmark persistence  -> RootFolderStore
//   - Dataless/coordinated IO -> FileProviderAccess
//   - Thumbnails            -> ProjectThumbnail
//   - Pure bundle discovery -> CaElevationKit.BundleIO.findBundles
//  This type only orchestrates them and holds the security-scoped access for the
//  whole session. The single-bundle capture flow stays in CaptureSessionModel.
//

import CaElevationKit
import Foundation
import Observation
import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// One discovered project: its bundle directory and decoded manifest.
struct ProjectEntry: Identifiable, Equatable, Hashable {
    let url: URL
    let manifest: SpecManifest
    var id: URL { url }

    var name: String { manifest.project.name }
    var levelCount: Int { manifest.levels.count }

    // Identity is the bundle directory; `SpecManifest` isn't Hashable, and the
    // URL uniquely identifies a project for navigation purposes.
    func hash(into hasher: inout Hasher) { hasher.combine(url) }
}

@MainActor
@Observable
final class ProjectLibrary {
    /// Where the picker is in its lifecycle.
    enum State: Equatable {
        case needsRoot          // no folder chosen / resolvable yet
        case loading
        case loaded
        case failed(String)
    }

    private(set) var root: URL?
    private(set) var projects: [ProjectEntry] = []
    private(set) var state: State = .needsRoot

    /// Bumped on each refresh so views can re-key caches/`.task`s to the latest
    /// scan (e.g. regenerate thumbnails after a re-synced floorplan changes).
    private(set) var generation = 0

    /// Per-project floorplan thumbnails, keyed by bundle directory URL.
    var thumbnailCache: [URL: UIImage] = [:]

    /// The currently-held security-scoped URL, so we can balance start/stop.
    /// Released on every root change and on `clearRoot()`. The instance lives for
    /// the whole app lifetime (it's `@State` on the `App`), so there's no deinit
    /// release to do — and a `@MainActor` deinit can't touch isolated state.
    private var scopedURL: URL?

    // MARK: - Root lifecycle

    /// On launch: resolve a previously-saved root and load it. No-op (leaving
    /// `.needsRoot`) when nothing is saved.
    func restoreSavedRoot() async {
        guard let resolved = RootFolderStore.resolve() else {
            state = .needsRoot
            return
        }
        if resolved.isStale {
            // Refresh the bookmark while the URL still resolves.
            try? RootFolderStore.save(resolved.url)
        }
        await adopt(resolved.url)
    }

    /// Adopt a freshly-picked folder: persist its bookmark and load it.
    func adoptRoot(_ url: URL) async {
        do {
            try RootFolderStore.save(url)
        } catch {
            state = .failed("Couldn't remember that folder: \(error.localizedDescription)")
            return
        }
        await adopt(url)
    }

    /// Forget the current root and return to the choose-folder state.
    func clearRoot() {
        releaseScope()
        RootFolderStore.clear()
        root = nil
        projects = []
        thumbnailCache = [:]
        state = .needsRoot
    }

    private func adopt(_ url: URL) async {
        releaseScope()
        if url.startAccessingSecurityScopedResource() {
            scopedURL = url
        } else {
            // Some providers/local URLs don't require a scope and return false
            // legitimately, so this isn't fatal — but log it, because a genuine
            // failure to acquire the grant shows up later as unreadable children.
            #if canImport(OSLog)
            Log.bundle.warning(
                "Security scope not acquired for \(url.lastPathComponent, privacy: .public); reads may fail"
            )
            #endif
        }
        root = url
        await refresh()
    }

    private func releaseScope() {
        scopedURL?.stopAccessingSecurityScopedResource()
        scopedURL = nil
    }

    // MARK: - Loading projects

    /// Re-scan the root for bundles and decode each manifest. Enumeration and
    /// decodes run off the main actor (they can block on provider downloads);
    /// results are published back on the main actor.
    func refresh() async {
        guard let root else { state = .needsRoot; return }
        state = .loading
        // New scan: drop cached thumbnails and bump the generation so rows
        // regenerate against the freshly-synced files.
        thumbnailCache = [:]
        generation += 1
        do {
            let entries = try await Task.detached(priority: .userInitiated) {
                try Self.scan(root: root)
            }.value
            projects = entries
            state = .loaded
        } catch {
            #if canImport(OSLog)
            Log.bundle.error("Library scan failed: \(error.localizedDescription, privacy: .public)")
            #endif
            projects = []
            state = .failed("Couldn't read that folder. It may be offline — try again.")
        }
    }

    /// Coordinated enumeration + per-project manifest decode. Floorplan images
    /// are NOT validated/materialized here — listing must stay cheap; thumbnails
    /// and images download lazily when a row appears or a project is opened.
    nonisolated private static func scan(root: URL) throws -> [ProjectEntry] {
        // Coordinate the root so the provider enumerates its children, but list
        // the captured `root` (not the coordinator's substituted URL): the child
        // URLs must stay valid for the per-manifest reads below, which happen
        // after this coordination block ends.
        let bundleURLs = try FileProviderAccess.coordinatedRead(at: root) { _ in
            try BundleIO.findBundles(in: root)
        }
        let decoder = BundleIO.makeDecoder()
        return bundleURLs.compactMap { url in
            let manifestURL = url.appendingPathComponent(BundleIO.manifestFileName)
            do {
                let data = try FileProviderAccess.readData(at: manifestURL)
                return ProjectEntry(url: url, manifest: try decoder.decode(SpecManifest.self, from: data))
            } catch {
                #if canImport(OSLog)
                let name = url.lastPathComponent
                let reason = error.localizedDescription
                Log.bundle.error(
                    "Skipping \(name, privacy: .public): \(reason, privacy: .public)"
                )
                #endif
                return nil
            }
        }
    }

    // MARK: - Thumbnails

    /// Lazily produce (and cache) a thumbnail for a project's first floorplan.
    /// Returns the cached image immediately when present.
    func thumbnail(for entry: ProjectEntry, scale: CGFloat) async -> UIImage? {
        if let cached = thumbnailCache[entry.url] { return cached }
        guard let level = entry.manifest.levels.first,
              let url = try? BundleIO.floorplanURL(for: level, in: entry.url) else {
            return nil
        }
        guard let image = await ProjectThumbnail.generate(for: url, scale: scale) else {
            return nil
        }
        thumbnailCache[entry.url] = image
        return image
    }
}

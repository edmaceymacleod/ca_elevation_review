//
//  RootFolderStore.swift
//  CaElevationApp
//
//  Persists *which* folder the user pointed the app at — the "library root", a
//  folder synced onto the phone by another app (e.g. OneDrive) and exposed
//  through iOS Files / a File Provider. We can't hardcode a path into another
//  app's sandboxed container, so the user picks the folder once via the document
//  picker and we keep a security-scoped **bookmark** to re-open it on later
//  launches.
//
//  iOS note (do NOT copy macOS sample code here): on iOS, folders picked through
//  `.fileImporter` / `UIDocumentPicker` are re-accessed with a plain bookmark —
//  `bookmarkData(options: [])` and resolve with `options: []`. The
//  `.withSecurityScope` option and the `com.apple.security.files.bookmarks.*`
//  entitlements are macOS App Sandbox concepts; `.withSecurityScope` is
//  unavailable on iOS and would throw. No entitlement is required.
//

import Foundation

/// Stores and resolves the bookmark for the user-chosen library root.
enum RootFolderStore {
    /// `UserDefaults` key holding the bookmark blob. It is not a secret (just a
    /// folder reference), so plain defaults — not the Keychain — is appropriate.
    static let defaultsKey = "libraryRootBookmark"

    /// A resolved library-root URL plus whether its bookmark needs refreshing.
    struct ResolvedRoot {
        let url: URL
        /// `true` when the OS reports the bookmark as stale; the caller should
        /// re-save a fresh bookmark (see ``save(_:)``) while it still resolves.
        let isStale: Bool
    }

    /// Persist a bookmark to `url` so the chosen root survives app launches.
    ///
    /// The security scope must be **active while the bookmark is created**, or on
    /// iOS the bookmark can fail to create or resolve later (so the chosen folder
    /// would be forgotten on the next launch). We start/stop access transiently
    /// here; this is reference-counted, so it composes with a longer-lived scope
    /// the caller may already hold on the same URL.
    static func save(_ url: URL, defaults: UserDefaults = .standard) throws {
        let didAccess = url.startAccessingSecurityScopedResource()
        defer { if didAccess { url.stopAccessingSecurityScopedResource() } }
        let data = try url.bookmarkData(
            options: [],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        defaults.set(data, forKey: defaultsKey)
    }

    /// Resolve the saved bookmark, or `nil` if none is stored or it no longer
    /// resolves (folder moved/removed, provider signed out). A throwing resolve
    /// is treated as "root lost": the stale blob is cleared so the UI falls back
    /// to the choose-folder state.
    static func resolve(defaults: UserDefaults = .standard) -> ResolvedRoot? {
        guard let data = defaults.data(forKey: defaultsKey) else { return nil }
        var isStale = false
        do {
            let url = try URL(
                resolvingBookmarkData: data,
                options: [],
                relativeTo: nil,
                bookmarkDataIsStale: &isStale
            )
            return ResolvedRoot(url: url, isStale: isStale)
        } catch {
            clear(defaults: defaults)
            return nil
        }
    }

    /// Forget the saved root (used on re-pick failure or when the user resets).
    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: defaultsKey)
    }
}

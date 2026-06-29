//
//  FileProviderAccess.swift
//  CaElevationApp
//
//  Reads files out of a File Provider folder (e.g. OneDrive synced into iOS
//  Files) safely. The central problem: provider files may be *dataless*
//  placeholders that aren't materialized on disk yet. A raw path read
//  (`Data(contentsOf:)`, `UIImage(contentsOfFile:)`) does NOT trigger a
//  download — it just sees whatever bytes happen to be local — so we route every
//  read through `NSFileCoordinator`, which asks the system to materialize the
//  item and only runs the accessor once data is available.
//
//  Honest limitation: there is no reliable, synchronous "is this file
//  downloaded?" API for third-party providers (`ubiquitousItemDownloadingStatus`
//  is iCloud-only and absent for OneDrive). So we never poll status — we always
//  coordinate the read and surface progress in the UI. These calls can block on
//  the network, so callers must run them off the main actor.
//

import Foundation

enum FileProviderAccess {
    /// Coordinated read of a file's bytes, materializing it if dataless.
    ///
    /// Runs the `NSFileCoordinator` accessor synchronously on the calling thread;
    /// call it from a background context (e.g. `Task.detached` / an actor), never
    /// on `@MainActor`.
    static func readData(at url: URL) throws -> Data {
        try coordinatedRead(at: url) { resolved in
            try Data(contentsOf: resolved)
        }
    }

    /// Coordinated directory listing, giving the provider a chance to enumerate
    /// children before we read them. Returns the contained URLs (one level).
    static func contentsOfDirectory(at url: URL) throws -> [URL] {
        try coordinatedRead(at: url) { resolved in
            try FileManager.default.contentsOfDirectory(
                at: resolved,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: [.skipsHiddenFiles]
            )
        }
    }

    /// Run `accessor` inside an `NSFileCoordinator` read coordination for `url`.
    /// The coordinator passes a possibly-substituted URL (the materialized
    /// location) which the accessor must use instead of the original.
    static func coordinatedRead<T>(at url: URL, _ accessor: (URL) throws -> T) throws -> T {
        let coordinator = NSFileCoordinator()
        var coordinatorError: NSError?
        var result: Result<T, Error>?

        coordinator.coordinate(readingItemAt: url, options: [], error: &coordinatorError) { resolved in
            result = Result { try accessor(resolved) }
        }

        if let coordinatorError { throw coordinatorError }
        // `result` is always set when no coordinator error occurred.
        return try result!.get()
    }
}

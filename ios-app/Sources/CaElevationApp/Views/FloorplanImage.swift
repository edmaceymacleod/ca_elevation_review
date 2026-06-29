//
//  FloorplanImage.swift
//  CaElevationApp
//
//  Loads a level's floorplan image from the on-disk bundle. Kept in the app
//  layer because it touches UIKit (`UIImage`); `CaElevationKit` stays
//  platform-free.
//
//  The read goes through `FileProviderAccess` (an `NSFileCoordinator` read) so a
//  not-yet-downloaded (dataless) floorplan in a OneDrive/File Provider folder is
//  materialized first — `UIImage(contentsOfFile:)` would NOT trigger that
//  download. Because a coordinated read can block on the network, the load is
//  **async and runs off the main actor**; callers `await` it from a `.task` and
//  build the `UIImage` back on the main actor. There is deliberately no
//  synchronous loader: doing the coordinated read in a SwiftUI `body` would
//  freeze the UI / risk a watchdog kill on a dataless plan.
//

import SwiftUI
import UIKit
import CaElevationKit

enum FloorplanImage {
    /// Read a level's floorplan bytes off the main actor (the coordinated read
    /// may block on a provider download). Returns `nil` if the plan can't be
    /// read. `Data` is `Sendable`, so the caller builds the `UIImage` on the
    /// main actor — avoiding a non-`Sendable` `UIImage` crossing actors.
    static func loadData(level: Level, bundleDirectory: URL) async -> Data? {
        await Task.detached(priority: .userInitiated) { () -> Data? in
            guard let url = try? BundleIO.floorplanURL(for: level, in: bundleDirectory) else {
                return nil
            }
            return try? FileProviderAccess.readData(at: url)
        }.value
    }
}

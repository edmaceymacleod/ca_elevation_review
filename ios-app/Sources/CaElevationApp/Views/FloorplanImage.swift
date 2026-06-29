//
//  FloorplanImage.swift
//  CaElevationApp
//
//  Small helper to load a level's floorplan image from the on-disk bundle into
//  a SwiftUI `Image`. Kept in the app layer because it touches UIKit
//  (`UIImage`); `CaElevationKit` stays platform-free.
//

import SwiftUI
import UIKit
import CaElevationKit

enum FloorplanImage {
    /// Load the floorplan image for a level from the bundle directory.
    static func load(level: Level, bundleDirectory: URL) -> Image? {
        guard let uiImage = loadUIImage(level: level, bundleDirectory: bundleDirectory) else {
            return nil
        }
        return Image(uiImage: uiImage)
    }

    /// Load the raw `UIImage` (for views that need pixel dimensions / overlay
    /// coordinate mapping, e.g. the place-pin and coverage screens).
    ///
    /// Reads through `FileProviderAccess` so a not-yet-downloaded (dataless)
    /// floorplan in a OneDrive/File Provider folder is materialized first.
    /// `UIImage(contentsOfFile:)` would NOT trigger that download — it only sees
    /// bytes already on disk — so a coordinated `Data` read is used instead.
    static func loadUIImage(level: Level, bundleDirectory: URL) -> UIImage? {
        guard let url = try? BundleIO.floorplanURL(for: level, in: bundleDirectory),
              let data = try? FileProviderAccess.readData(at: url) else {
            return nil
        }
        return UIImage(data: data)
    }
}

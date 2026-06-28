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
        let url = BundleIO.floorplanURL(for: level, in: bundleDirectory)
        guard let uiImage = UIImage(contentsOfFile: url.path) else { return nil }
        return Image(uiImage: uiImage)
    }

    /// Load the raw `UIImage` (for views that need pixel dimensions / overlay
    /// coordinate mapping, e.g. the place-pin and coverage screens).
    static func loadUIImage(level: Level, bundleDirectory: URL) -> UIImage? {
        let url = BundleIO.floorplanURL(for: level, in: bundleDirectory)
        return UIImage(contentsOfFile: url.path)
    }
}

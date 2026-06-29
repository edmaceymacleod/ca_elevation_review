//
//  ProjectThumbnail.swift
//  CaElevationApp
//
//  Generates a small per-project thumbnail from a floorplan image that may live
//  in a File Provider folder (OneDrive) and may not be downloaded yet.
//
//  Uses `QLThumbnailGenerator` (QuickLookThumbnailing) rather than decoding the
//  full image: QuickLook is File-Provider-aware (it coordinates the read and can
//  render from the provider), and it returns a downscaled image instead of
//  loading a multi-megabyte floorplan into memory just to fill a list row. A
//  coordinated full-decode is kept as a fallback when QuickLook can't produce a
//  representation.
//

#if canImport(UIKit) && canImport(QuickLookThumbnailing)
import UIKit
import QuickLookThumbnailing

enum ProjectThumbnail {
    /// Produce a thumbnail `UIImage` for the file at `url`, or `nil` if neither
    /// QuickLook nor the fallback decode can render it.
    ///
    /// - Parameters:
    ///   - url: the floorplan image URL (possibly a dataless provider placeholder).
    ///   - size: target size in points.
    ///   - scale: display scale (pass `UIScreen.main.scale` from the main actor).
    static func generate(
        for url: URL,
        size: CGSize = CGSize(width: 56, height: 56),
        scale: CGFloat
    ) async -> UIImage? {
        let request = QLThumbnailGenerator.Request(
            fileAt: url,
            size: size,
            scale: scale,
            representationTypes: .thumbnail
        )
        if let representation = try? await QLThumbnailGenerator.shared
            .generateBestRepresentation(for: request) {
            return representation.uiImage
        }
        return fallbackDecode(at: url, size: size)
    }

    /// Last resort: coordinate a full read and down-render. Heavier than
    /// QuickLook, used only when QuickLook returns nothing.
    private static func fallbackDecode(at url: URL, size: CGSize) -> UIImage? {
        guard let data = try? FileProviderAccess.readData(at: url),
              let image = UIImage(data: data) else { return nil }
        let renderer = UIGraphicsImageRenderer(size: size)
        return renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
    }
}
#endif

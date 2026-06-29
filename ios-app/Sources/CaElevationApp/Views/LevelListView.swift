//
//  LevelListView.swift
//  CaElevationApp
//
//  Field flow step 2: pick a level / floorplan within the opened project. This
//  is the screen reached by tapping a project in `ProjectListView`; the project's
//  bundle is already loaded into `CaptureSessionModel`. Tapping a level row
//  navigates into capture.
//
//  (Previously this list lived inline in `ProjectListView`; it moved here when
//  the root screen became the multi-project picker.)
//

import SwiftUI
import CaElevationKit

struct LevelListView: View {
    @EnvironmentObject private var session: CaptureSessionModel
    let manifest: SpecManifest

    var body: some View {
        List(manifest.levels, id: \.id) { level in
            NavigationLink {
                CaptureView(level: level)
            } label: {
                LevelRow(
                    level: level,
                    bundleDirectory: session.bundleDirectory,
                    deviceCount: manifest.devices.filter { $0.levelId == level.id }.count
                )
            }
            .simultaneousGesture(TapGesture().onEnded {
                session.selectedLevel = level
            })
        }
        .navigationTitle(manifest.project.name)
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// A single level row with a floorplan thumbnail and expected-device count.
private struct LevelRow: View {
    let level: Level
    let bundleDirectory: URL?
    let deviceCount: Int

    var body: some View {
        HStack(spacing: 12) {
            thumbnail
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading) {
                Text(level.name).font(.headline)
                Text("\(deviceCount) expected device\(deviceCount == 1 ? "" : "s")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private var thumbnail: some View {
        if let dir = bundleDirectory,
           let image = FloorplanImage.load(level: level, bundleDirectory: dir) {
            image.resizable().scaledToFill()
        } else {
            RoundedRectangle(cornerRadius: 8)
                .fill(.quaternary)
                .overlay(Image(systemName: "map").foregroundStyle(.secondary))
        }
    }
}

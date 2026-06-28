//
//  ProjectListView.swift
//  CaElevationApp
//
//  Field flow steps 1-2: open a field bundle (received by AirDrop / Files /
//  iCloud) and pick a level / floorplan thumbnail to capture on.
//

import SwiftUI
import UniformTypeIdentifiers
import CaElevationKit

struct ProjectListView: View {
    @EnvironmentObject private var session: CaptureSessionModel
    @State private var isImporting = false
    @State private var loadError: String?

    var body: some View {
        NavigationStack {
            Group {
                if let manifest = session.manifest {
                    levelList(manifest)
                } else {
                    emptyState
                }
            }
            .navigationTitle("CA Elevation Review")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button("Open Bundle") { isImporting = true }
                }
            }
            .fileImporter(
                isPresented: $isImporting,
                allowedContentTypes: [.folder],
                allowsMultipleSelection: false
            ) { result in
                handleImport(result)
            }
            .alert("Could not load bundle", isPresented: .constant(loadError != nil)) {
                Button("OK") { loadError = nil }
            } message: {
                Text(loadError ?? "")
            }
        }
    }

    // MARK: - Subviews

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "tray.and.arrow.down")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text("Open a field bundle")
                .font(.headline)
            Text("Receive a bundle by AirDrop, Files, or iCloud Drive, then open it here.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button("Open Bundle") { isImporting = true }
                .buttonStyle(.borderedProminent)
        }
        .padding()
    }

    /// Step 2: level / floorplan thumbnail list. Tapping selects the level and
    /// navigates into capture.
    private func levelList(_ manifest: SpecManifest) -> some View {
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
    }

    // MARK: - Actions

    private func handleImport(_ result: Result<[URL], Error>) {
        do {
            guard let directory = try result.get().first else { return }
            // Security-scoped access is required for user-picked locations.
            let didAccess = directory.startAccessingSecurityScopedResource()
            defer { if didAccess { directory.stopAccessingSecurityScopedResource() } }
            // TODO: For a real app, copy the bundle into the app's Documents
            // directory so the security-scoped URL does not need to stay live
            // for the whole session.
            try session.loadBundle(at: directory)
        } catch {
            loadError = String(describing: error)
        }
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

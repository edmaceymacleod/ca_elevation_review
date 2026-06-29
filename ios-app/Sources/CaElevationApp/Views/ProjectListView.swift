//
//  ProjectListView.swift
//  CaElevationApp
//
//  Field flow step 1: the multi-project picker. The user points the app at one
//  library root — a folder synced onto the phone by OneDrive (or any provider in
//  iOS Files) that holds one subfolder per project. We list those bundles with a
//  thumbnail; tapping one loads it and pushes the level list -> capture.
//
//  The chosen root is remembered across launches (RootFolderStore), so after the
//  first pick the app opens straight to the project list.
//

import SwiftUI
import CaElevationKit

struct ProjectListView: View {
    @EnvironmentObject private var session: CaptureSessionModel
    @Environment(ProjectLibrary.self) private var library
    @State private var isImporting = false
    @State private var selectedProject: ProjectEntry?
    @State private var openError: String?

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("CA Elevation Review")
                .toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        Button("Choose Folder") { isImporting = true }
                    }
                }
                .navigationDestination(item: $selectedProject) { project in
                    LevelListView(manifest: project.manifest)
                }
                .fileImporter(
                    isPresented: $isImporting,
                    allowedContentTypes: [.folder],
                    allowsMultipleSelection: false
                ) { result in
                    handleImport(result)
                }
                .task { await library.restoreSavedRoot() }
                .refreshable { await library.refresh() }
                .alert("Couldn't open project", isPresented: .constant(openError != nil)) {
                    Button("OK") { openError = nil }
                } message: {
                    Text(openError ?? "")
                }
        }
    }

    // MARK: - Subviews

    @ViewBuilder
    private var content: some View {
        switch library.state {
        case .needsRoot:
            emptyState
        case .loading:
            ProgressView("Loading projects…")
        case .failed(let message):
            errorState(message)
        case .loaded:
            if library.projects.isEmpty {
                noProjectsState
            } else {
                projectList
            }
        }
    }

    private var projectList: some View {
        List(library.projects) { project in
            Button {
                openProject(project)
            } label: {
                ProjectRow(project: project)
            }
            .buttonStyle(.plain)
        }
    }

    private var emptyState: some View {
        infoState(
            systemImage: "folder.badge.plus",
            title: "Choose your projects folder",
            message: "Point the app at the OneDrive folder synced to this phone "
                + "that holds your project bundles.",
            actionTitle: "Choose Folder"
        )
    }

    private var noProjectsState: some View {
        infoState(
            systemImage: "tray",
            title: "No projects found",
            message: "That folder has no project bundles yet. Each project is a "
                + "subfolder containing a manifest.json. Pull to refresh once they sync.",
            actionTitle: "Choose a Different Folder"
        )
    }

    private func errorState(_ message: String) -> some View {
        infoState(
            systemImage: "exclamationmark.triangle",
            title: "Couldn't open folder",
            message: message,
            actionTitle: "Choose Folder"
        )
    }

    private func infoState(
        systemImage: String,
        title: String,
        message: String,
        actionTitle: String
    ) -> some View {
        VStack(spacing: 16) {
            Image(systemName: systemImage)
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text(title).font(.headline)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button(actionTitle) { isImporting = true }
                .buttonStyle(.borderedProminent)
        }
        .padding()
    }

    // MARK: - Actions

    private func openProject(_ project: ProjectEntry) {
        do {
            // The project's manifest is already decoded by the library scan, so
            // pass it straight through (no redundant re-read) and prepare a fresh
            // capture/export session for this project.
            try session.loadBundle(project.manifest, at: project.url)
            selectedProject = project
        } catch {
            #if canImport(OSLog)
            Log.bundle.error("Failed to open project: \(error.localizedDescription, privacy: .public)")
            #endif
            openError = "Couldn't start a capture session for \(project.name). \(error.localizedDescription)"
        }
    }

    private func handleImport(_ result: Result<[URL], Error>) {
        guard let directory = try? result.get().first else { return }
        Task { await library.adoptRoot(directory) }
    }
}

/// A single project row: floorplan thumbnail, name, and level count. The
/// thumbnail loads lazily (and is cached) so opening the folder doesn't download
/// every project's floorplan up front.
private struct ProjectRow: View {
    @Environment(ProjectLibrary.self) private var library
    @Environment(\.displayScale) private var displayScale
    let project: ProjectEntry
    @State private var thumbnail: UIImage?

    var body: some View {
        HStack(spacing: 12) {
            thumbnailView
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading) {
                Text(project.name).font(.headline)
                Text("\(project.levelCount) level\(project.levelCount == 1 ? "" : "s")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Image(systemName: "chevron.forward")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
        // Re-key on the library generation so a pull-to-refresh (which clears the
        // thumbnail cache) regenerates the image — otherwise a re-synced floorplan
        // would keep showing the stale thumbnail.
        .task(id: ThumbnailTaskID(url: project.id, generation: library.generation)) {
            thumbnail = await library.thumbnail(for: project, scale: displayScale)
        }
    }

    @ViewBuilder
    private var thumbnailView: some View {
        if let thumbnail {
            Image(uiImage: thumbnail).resizable().scaledToFill()
        } else {
            RoundedRectangle(cornerRadius: 8)
                .fill(.quaternary)
                .overlay(Image(systemName: "map").foregroundStyle(.secondary))
        }
    }
}

/// Identity for a project row's thumbnail `.task`: the project plus the library
/// generation, so the task re-runs when the library is refreshed.
private struct ThumbnailTaskID: Equatable {
    let url: URL
    let generation: Int
}

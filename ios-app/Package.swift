// swift-tools-version: 5.9
//
// Swift Package manifest for CaElevationKit -- the pure, platform-free logic
// library of the CA Elevation Review iPhone capture app.
//
// Only the *pure-logic* parts of the app live in this package. They build and
// test headlessly on any platform with a Swift toolchain (Linux CI, macOS),
// with no UIKit / ARKit / CoreLocation dependency. This mirrors the design
// doc's testability rule: "separation of pure logic from platform-coupled
// code ... app logic vs ARKit".
//
// The SwiftUI + ARKit app layer (Sources/CaElevationApp) is NOT a target here:
// it is built as an Xcode *App* target that depends on the CaElevationKit
// product. See README.md for how those sources are wired into Xcode.
import PackageDescription

let package = Package(
    name: "CaElevationKit",
    platforms: [
        // iOS is where the app ships; macOS lets the kit build/test on a Mac.
        // The kit itself is pure Foundation and also builds on Linux for CI.
        // Floor is iOS 17: the app layer uses iOS 17 SwiftUI APIs
        // (navigationDestination(item:)), and every LiDAR-capable iPhone
        // (12 Pro and later) runs iOS 17+, so this loses no target hardware.
        .iOS(.v17),
        .macOS(.v13)
    ],
    products: [
        .library(
            name: "CaElevationKit",
            targets: ["CaElevationKit"]
        )
    ],
    targets: [
        .target(
            name: "CaElevationKit",
            path: "Sources/CaElevationKit"
        ),
        .testTarget(
            name: "CaElevationKitTests",
            dependencies: ["CaElevationKit"],
            path: "Tests/CaElevationKitTests"
        )
    ]
)

//
//  CompassHeading.swift
//  CaElevationApp
//
//  CoreLocation heading provider used to PRE-FILL the pin arrow on the
//  Place-It screen, so the user confirms / nudges the camera heading rather
//  than guessing -- killing most coarse-heading error (see design.md).
//
//  ============================================================================
//  Platform-coupled: CoreLocation. Requires a real device with a magnetometer
//  and "When In Use" location authorization (add NSLocationWhenInUseUsage
//  Description to the app's Info.plist). The simulator can fake a static
//  heading but not a live compass.
//  ============================================================================
//
//  IMPORTANT -- coordinate convention: CoreLocation reports `trueHeading` in
//  COMPASS degrees (0 = geographic north, clockwise). The capture-package pin
//  `heading` is in PLAN degrees (0 = +X, counter-clockwise) and is relative to
//  the model/plan frame. The conversion from compass-true-north to plan degrees
//  needs the manifest's `coordinate_system.north_angle` (project north vs true
//  north). `planHeadingDegrees(northAngle:)` performs that mapping.
//

import Foundation
import Combine

#if canImport(CoreLocation)
import CoreLocation
#endif

/// Publishes the device compass heading for the pin pre-fill.
@MainActor
final class CompassHeading: NSObject, ObservableObject {
    /// Latest true heading in COMPASS degrees (0 = true north, clockwise), or
    /// nil until the first reading.
    @Published private(set) var trueHeadingDegrees: Double?

    #if canImport(CoreLocation)
    private let manager = CLLocationManager()
    #endif

    override init() {
        super.init()
        #if canImport(CoreLocation)
        manager.delegate = self
        manager.headingFilter = 1 // degrees
        #endif
    }

    /// Request authorization and begin heading updates. // Real device only.
    func start() {
        #if canImport(CoreLocation)
        manager.requestWhenInUseAuthorization()
        if CLLocationManager.headingAvailable() {
            manager.startUpdatingHeading()
        }
        #endif
    }

    func stop() {
        #if canImport(CoreLocation)
        manager.stopUpdatingHeading()
        #endif
    }

    /// Raw compass heading, surfaced for the capture snapshot. The Place-It view
    /// converts this to plan degrees with the manifest north angle.
    var headingDegrees: Double? { trueHeadingDegrees }

    /// Convert the current compass true-heading to PLAN degrees (0 = +X CCW),
    /// given the manifest's project-north-vs-true-north angle.
    ///
    /// Compass: 0 = north, clockwise. Plan: 0 = +X, counter-clockwise, with +Y
    /// up. Mapping north (compass 0) to +Y (plan 90) and flipping handedness:
    ///     plan = 90 - (compass - northAngle)
    /// normalized to [0, 360).
    func planHeadingDegrees(northAngle: Double) -> Double? {
        guard let compass = trueHeadingDegrees else { return nil }
        let plan = 90 - (compass - northAngle)
        return plan.truncatingRemainder(dividingBy: 360).normalizedDegrees
    }
}

#if canImport(CoreLocation)
extension CompassHeading: CLLocationManagerDelegate {
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateHeading newHeading: CLHeading) {
        // trueHeading is -1 if unavailable (no location fix); fall back to magnetic.
        let heading = newHeading.trueHeading >= 0 ? newHeading.trueHeading : newHeading.magneticHeading
        Task { @MainActor in
            self.trueHeadingDegrees = heading
        }
    }
}
#endif

extension Double {
    /// Normalize to [0, 360).
    var normalizedDegrees: Double {
        let r = truncatingRemainder(dividingBy: 360)
        return r < 0 ? r + 360 : r
    }
}

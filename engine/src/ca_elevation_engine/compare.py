"""Locate expected devices in the capture and measure deviations.

For each expected device the engine asks: which shots could see it (frustum
test against the registered pose), is there an observation near where it should
be, and how far off is it? The output is a per-device :class:`Match` carrying
the best observation, the measured deltas, and coverage facts. Verdict
classification (applying tolerances) lives in :mod:`ca_elevation_engine.verdict`.

The deterministic, headless path consumes ``shot.observations`` (model-frame
device candidates produced synthetically by fixtures or by a vision/registration
backend). Heavy point-cloud-derived observation extraction is an optional
upstream concern; this module is agnostic to where observations came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import geometry as geo
from .models import (
    CapturePackage,
    Device,
    Observation,
    SpecManifest,
)
from .register import ShotRegistration

# A device is considered "could be seen" by a shot if it projects within the
# frame (plus this fractional margin) and in front of the camera.
FRUSTUM_MARGIN_FRAC = 0.10

# Observation-to-device association gate: an observation may match a device only
# if within this multiple of the device's position tolerance, with an absolute
# floor so tiny tolerances still admit a real-but-noisy match.
GATE_TOLERANCE_MULT = 3.0
GATE_ABS_FLOOR = 0.5  # project units


@dataclass
class ShotCoverage:
    shot_id: str
    projected_uv: tuple[float, float]
    depth: float
    in_frame: bool


@dataclass
class Match:
    """How an expected device fared against the capture."""

    device: Device
    covered_by: list[ShotCoverage] = field(default_factory=list)
    observation: Observation | None = None
    matched_shot_id: str | None = None
    match_distance: float | None = None
    position_delta: float | None = None
    height_delta: float | None = None
    orientation_delta: float | None = None
    approximate: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def in_coverage(self) -> bool:
        return any(c.in_frame for c in self.covered_by)


def _expected_height(device: Device, manifest: SpecManifest) -> float | None:
    if device.mounting_height is not None:
        return device.mounting_height
    level = manifest.level_by_id(device.level_id)
    if level is None:
        return None
    return device.position.z - level.elevation


def _coverage_for_device(
    device: Device,
    capture: CapturePackage,
    registrations: dict[str, ShotRegistration],
) -> list[ShotCoverage]:
    """Which shots (on the device's level) could see this device."""
    out: list[ShotCoverage] = []
    p = device.position.as_tuple()
    for shot in capture.shots:
        if shot.level_id != device.level_id:
            continue
        reg = registrations.get(shot.id)
        if reg is None:
            continue
        # Project the device (model frame) back into the camera. We need the
        # model->camera transform: invert arkit_to_model, then world->camera.
        intr = (shot.intrinsics.fx, shot.intrinsics.fy, shot.intrinsics.cx, shot.intrinsics.cy)
        # Move the device point from model frame into ARKit world frame.
        import numpy as np

        model_to_arkit = np.linalg.inv(reg.arkit_to_model)
        p_arkit = geo.transform_point(model_to_arkit, p)
        u, v, depth = geo.project_point(shot.pose, intr, p_arkit)
        mw = shot.intrinsics.width * FRUSTUM_MARGIN_FRAC
        mh = shot.intrinsics.height * FRUSTUM_MARGIN_FRAC
        in_frame = (
            depth > 0
            and -mw <= u <= shot.intrinsics.width + mw
            and -mh <= v <= shot.intrinsics.height + mh
        )
        out.append(
            ShotCoverage(shot_id=shot.id, projected_uv=(u, v), depth=depth, in_frame=in_frame)
        )
    return out


def _candidate_observations(
    device: Device,
    capture: CapturePackage,
    coverage: list[ShotCoverage],
) -> list[tuple[str, Observation]]:
    """Gather (shot_id, observation) candidates from shots that cover the device."""
    covering = {c.shot_id for c in coverage if c.in_frame}
    # Fall back to all same-level shots if frustum coverage found nothing but
    # observations exist (keeps a near miss matchable).
    out: list[tuple[str, Observation]] = []
    for shot in capture.shots:
        if shot.level_id != device.level_id:
            continue
        if covering and shot.id not in covering:
            continue
        for obs in shot.observations:
            out.append((shot.id, obs))
    return out


def match_device(
    device: Device,
    capture: CapturePackage,
    manifest: SpecManifest,
    registrations: dict[str, ShotRegistration],
) -> Match:
    """Locate one device in the capture and measure its deviations."""
    coverage = _coverage_for_device(device, capture, registrations)
    match = Match(device=device, covered_by=coverage)

    tol = manifest.effective_tolerances(device)
    # Explicit None check: an explicit position tolerance of 0.0 must not be
    # silently replaced by the floor (truthy `or` would swallow it).
    pos_tol = tol.position if tol.position is not None else GATE_ABS_FLOOR
    gate = max(pos_tol * GATE_TOLERANCE_MULT, GATE_ABS_FLOOR)

    candidates = _candidate_observations(device, capture, coverage)
    expected = device.position.as_tuple()

    # Among in-gate candidates, prefer a type-AGREEING (or type-unknown)
    # observation over a closer wrong-type one, then break ties by distance --
    # so a nearby decoy of the wrong type can't mask the correct device. Imported
    # function-locally to avoid a compare<->verdict import cycle.
    from .verdict import TYPE_MISMATCH_MIN_CONFIDENCE, _types_disagree

    best: tuple[str, Observation, float] | None = None
    best_key: tuple[bool, float] | None = None
    for shot_id, obs in candidates:
        d = geo.distance3(expected, obs.position.as_tuple())
        if d > gate:
            continue
        disagrees = bool(
            obs.detected_type
            and obs.type_confidence is not None
            and obs.type_confidence >= TYPE_MISMATCH_MIN_CONFIDENCE
            and _types_disagree(device.type, obs.detected_type)
        )
        key = (disagrees, d)  # False (agrees/unknown) sorts before True
        if best_key is None or key < best_key:
            best_key = key
            best = (shot_id, obs, d)

    if best is None:
        if not match.in_coverage:
            match.notes.append("not within any captured view (coverage gap)")
        else:
            match.notes.append("expected in view but no matching device observed")
        # Approximate when there was no metric depth anywhere on the level.
        match.approximate = not _level_has_depth(device.level_id, capture)
        return match

    shot_id, obs, dist = best
    match.observation = obs
    match.matched_shot_id = shot_id
    match.match_distance = dist
    match.position_delta = dist

    exp_h = _expected_height(device, manifest)
    if exp_h is not None and obs.mounting_height is not None:
        match.height_delta = abs(obs.mounting_height - exp_h)

    if device.orientation.facing_angle is not None and obs.facing_angle is not None:
        match.orientation_delta = geo.angle_delta_deg(
            device.orientation.facing_angle, obs.facing_angle
        )

    shot = next((s for s in capture.shots if s.id == shot_id), None)
    match.approximate = shot is None or (shot.depth_map is None and shot.point_cloud is None)
    if match.approximate:
        match.notes.append("geometry approximate (no metric depth for matched shot)")
    return match


def _level_has_depth(level_id: str, capture: CapturePackage) -> bool:
    return any(
        s.level_id == level_id and (s.depth_map is not None or s.point_cloud is not None)
        for s in capture.shots
    )


def match_all(
    manifest: SpecManifest,
    capture: CapturePackage,
    registrations: dict[str, ShotRegistration],
) -> list[Match]:
    """Match every device in the manifest. Order follows the manifest."""
    return [match_device(d, capture, manifest, registrations) for d in manifest.devices]

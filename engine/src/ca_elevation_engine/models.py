"""In-memory data models for the elevation verification engine.

These dataclasses are the typed representation of the two ingested payloads
(spec manifest, capture package) and the emitted verdict report. They are the
shared contract every engine module builds against. Each model carries
``from_dict`` / ``to_dict`` so the JSON wire format (validated against the
schemas in ``schemas/``) and the typed object stay in lockstep.

Keep this module pure: no IO, no heavy deps. Geometry lives in ``geometry``;
loading/validation in ``ingest``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION = "1.0.0"


class Verdict(str, Enum):
    """Per-device outcome of verification."""

    PASS = "pass"
    FLAG = "flag"
    ABSENT = "absent"
    TYPE_MISMATCH = "type_mismatch"


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Point3:
    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Point3:
        return cls(x=float(d["x"]), y=float(d["y"]), z=float(d["z"]))

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class Tolerances:
    """Pass/flag thresholds. Distances in project units, orientation in degrees."""

    position: float | None = None
    mounting_height: float | None = None
    orientation: float | None = None

    def merged_with(self, fallback: Tolerances) -> Tolerances:
        """Return tolerances using own values, falling back per-field."""
        return Tolerances(
            position=self.position if self.position is not None else fallback.position,
            mounting_height=self.mounting_height
            if self.mounting_height is not None
            else fallback.mounting_height,
            orientation=self.orientation if self.orientation is not None else fallback.orientation,
        )

    def to_dict(self) -> dict[str, float]:
        out: dict[str, float] = {}
        if self.position is not None:
            out["position"] = self.position
        if self.mounting_height is not None:
            out["mounting_height"] = self.mounting_height
        if self.orientation is not None:
            out["orientation"] = self.orientation
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Tolerances:
        d = d or {}
        return cls(
            position=d.get("position"),
            mounting_height=d.get("mounting_height"),
            orientation=d.get("orientation"),
        )


# Sensible defaults if a manifest omits default_tolerances entirely.
# ~1 inch / ~0.5 inch in feet; 10 degrees.
DEFAULT_TOLERANCES = Tolerances(position=0.083, mounting_height=0.042, orientation=10.0)


@dataclass
class Orientation:
    facing_angle: float | None = None
    up_axis: str = "up"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"up_axis": self.up_axis}
        if self.facing_angle is not None:
            out["facing_angle"] = self.facing_angle
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Orientation:
        d = d or {}
        return cls(facing_angle=d.get("facing_angle"), up_axis=d.get("up_axis", "up"))


# --------------------------------------------------------------------------- #
# Spec manifest
# --------------------------------------------------------------------------- #
@dataclass
class Floorplan:
    image: str
    width_px: int
    height_px: int
    pixel_to_model: list[float]  # 2x3 row-major affine [a,b,c,d,e,f]

    def to_dict(self) -> dict[str, Any]:
        return {
            "image": self.image,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "pixel_to_model": list(self.pixel_to_model),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Floorplan:
        return cls(
            image=d["image"],
            width_px=int(d["width_px"]),
            height_px=int(d["height_px"]),
            pixel_to_model=[float(v) for v in d["pixel_to_model"]],
        )


@dataclass
class Level:
    id: str
    name: str
    elevation: float
    floorplan: Floorplan

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "elevation": self.elevation,
            "floorplan": self.floorplan.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Level:
        return cls(
            id=d["id"],
            name=d["name"],
            elevation=float(d["elevation"]),
            floorplan=Floorplan.from_dict(d["floorplan"]),
        )


@dataclass
class Device:
    id: str
    family: str
    type: str
    level_id: str
    position: Point3
    elevation_id: str | None = None
    mounting_height: float | None = None
    orientation: Orientation = field(default_factory=Orientation)
    tolerances: Tolerances = field(default_factory=Tolerances)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "family": self.family,
            "type": self.type,
            "level_id": self.level_id,
            "position": self.position.to_dict(),
        }
        if self.elevation_id is not None:
            out["elevation_id"] = self.elevation_id
        if self.mounting_height is not None:
            out["mounting_height"] = self.mounting_height
        if self.orientation.facing_angle is not None or self.orientation.up_axis != "up":
            out["orientation"] = self.orientation.to_dict()
        tol = self.tolerances.to_dict()
        if tol:
            out["tolerances"] = tol
        if self.metadata:
            out["metadata"] = self.metadata
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Device:
        return cls(
            id=d["id"],
            family=d["family"],
            type=d["type"],
            level_id=d["level_id"],
            position=Point3.from_dict(d["position"]),
            elevation_id=d.get("elevation_id"),
            mounting_height=d.get("mounting_height"),
            orientation=Orientation.from_dict(d.get("orientation")),
            tolerances=Tolerances.from_dict(d.get("tolerances")),
            metadata=d.get("metadata", {}),
        )


@dataclass
class Project:
    id: str
    name: str
    units: str
    revit_file: str | None = None
    exported_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {"id": self.id, "name": self.name, "units": self.units}
        if self.revit_file is not None:
            out["revit_file"] = self.revit_file
        if self.exported_at is not None:
            out["exported_at"] = self.exported_at
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Project:
        return cls(
            id=d["id"],
            name=d["name"],
            units=d["units"],
            revit_file=d.get("revit_file"),
            exported_at=d.get("exported_at"),
        )


@dataclass
class SpecManifest:
    schema_version: str
    project: Project
    levels: list[Level]
    devices: list[Device]
    default_tolerances: Tolerances = field(default_factory=lambda: DEFAULT_TOLERANCES)
    coordinate_system: dict[str, Any] = field(default_factory=dict)

    def level_by_id(self, level_id: str) -> Level | None:
        return next((lv for lv in self.levels if lv.id == level_id), None)

    def effective_tolerances(self, device: Device) -> Tolerances:
        """Per-device tolerances with manifest defaults filled in."""
        return device.tolerances.merged_with(self.default_tolerances).merged_with(
            DEFAULT_TOLERANCES
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "project": self.project.to_dict(),
            "levels": [lv.to_dict() for lv in self.levels],
            "devices": [dv.to_dict() for dv in self.devices],
        }
        dt = self.default_tolerances.to_dict()
        if dt:
            out["default_tolerances"] = dt
        if self.coordinate_system:
            out["coordinate_system"] = self.coordinate_system
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SpecManifest:
        return cls(
            schema_version=d["schema_version"],
            project=Project.from_dict(d["project"]),
            levels=[Level.from_dict(x) for x in d["levels"]],
            devices=[Device.from_dict(x) for x in d.get("devices", [])],
            default_tolerances=Tolerances.from_dict(d.get("default_tolerances")),
            coordinate_system=d.get("coordinate_system", {}),
        )


# --------------------------------------------------------------------------- #
# Capture package
# --------------------------------------------------------------------------- #
@dataclass
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Intrinsics:
        return cls(
            fx=float(d["fx"]),
            fy=float(d["fy"]),
            cx=float(d["cx"]),
            cy=float(d["cy"]),
            width=int(d["width"]),
            height=int(d["height"]),
        )


@dataclass
class Pin:
    x: float
    y: float
    heading: float
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "heading": self.heading, "confidence": self.confidence}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Pin:
        return cls(
            x=float(d["x"]),
            y=float(d["y"]),
            heading=float(d["heading"]),
            confidence=d.get("confidence", "medium"),
        )


@dataclass
class Observation:
    """A candidate device seen in a shot, expressed in model coordinates.

    Produced either synthetically (fixtures) or by a registration/vision
    backend. The compare step matches these against expected devices.
    """

    position: Point3
    mounting_height: float | None = None
    facing_angle: float | None = None
    detected_type: str | None = None
    type_confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"position": self.position.to_dict()}
        if self.mounting_height is not None:
            out["mounting_height"] = self.mounting_height
        if self.facing_angle is not None:
            out["facing_angle"] = self.facing_angle
        if self.detected_type is not None:
            out["detected_type"] = self.detected_type
        if self.type_confidence is not None:
            out["type_confidence"] = self.type_confidence
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Observation:
        return cls(
            position=Point3.from_dict(d["position"]),
            mounting_height=d.get("mounting_height"),
            facing_angle=d.get("facing_angle"),
            detected_type=d.get("detected_type"),
            type_confidence=d.get("type_confidence"),
        )


@dataclass
class Shot:
    id: str
    level_id: str
    rgb_image: str
    intrinsics: Intrinsics
    pose: list[float]  # 4x4 row-major
    pin: Pin
    elevation_id: str | None = None
    depth_map: str | None = None
    depth_size: list[int] | None = None
    point_cloud: str | None = None
    captured_at: str | None = None
    observations: list[Observation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "level_id": self.level_id,
            "rgb_image": self.rgb_image,
            "intrinsics": self.intrinsics.to_dict(),
            "pose": list(self.pose),
            "pin": self.pin.to_dict(),
        }
        if self.elevation_id is not None:
            out["elevation_id"] = self.elevation_id
        if self.depth_map is not None:
            out["depth_map"] = self.depth_map
        if self.depth_size is not None:
            out["depth_size"] = list(self.depth_size)
        if self.point_cloud is not None:
            out["point_cloud"] = self.point_cloud
        if self.captured_at is not None:
            out["captured_at"] = self.captured_at
        if self.observations:
            out["observations"] = [o.to_dict() for o in self.observations]
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Shot:
        return cls(
            id=d["id"],
            level_id=d["level_id"],
            rgb_image=d["rgb_image"],
            intrinsics=Intrinsics.from_dict(d["intrinsics"]),
            pose=[float(v) for v in d["pose"]],
            pin=Pin.from_dict(d["pin"]),
            elevation_id=d.get("elevation_id"),
            depth_map=d.get("depth_map"),
            depth_size=d.get("depth_size"),
            point_cloud=d.get("point_cloud"),
            captured_at=d.get("captured_at"),
            observations=[Observation.from_dict(o) for o in d.get("observations", [])],
        )


@dataclass
class CapturePackage:
    schema_version: str
    project_id: str
    shots: list[Shot]
    captured_at: str | None = None
    device_model: str | None = None
    app_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "shots": [s.to_dict() for s in self.shots],
        }
        if self.captured_at is not None:
            out["captured_at"] = self.captured_at
        if self.device_model is not None:
            out["device_model"] = self.device_model
        if self.app_version is not None:
            out["app_version"] = self.app_version
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CapturePackage:
        return cls(
            schema_version=d["schema_version"],
            project_id=d["project_id"],
            shots=[Shot.from_dict(s) for s in d["shots"]],
            captured_at=d.get("captured_at"),
            device_model=d.get("device_model"),
            app_version=d.get("app_version"),
        )


# --------------------------------------------------------------------------- #
# Verdict report
# --------------------------------------------------------------------------- #
@dataclass
class Deltas:
    position: float | None = None
    mounting_height: float | None = None
    orientation: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "mounting_height": self.mounting_height,
            "orientation": self.orientation,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Deltas:
        d = d or {}
        return cls(
            position=d.get("position"),
            mounting_height=d.get("mounting_height"),
            orientation=d.get("orientation"),
        )


@dataclass
class DeviceResult:
    device_id: str
    verdict: Verdict
    confidence: float
    family: str | None = None
    type: str | None = None
    matched_shot_id: str | None = None
    identity_confirmed: bool = False
    deltas: Deltas = field(default_factory=Deltas)
    approximate: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "device_id": self.device_id,
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "matched_shot_id": self.matched_shot_id,
            "identity_confirmed": self.identity_confirmed,
            "deltas": self.deltas.to_dict(),
            "approximate": self.approximate,
            "notes": list(self.notes),
        }
        if self.family is not None:
            out["family"] = self.family
        if self.type is not None:
            out["type"] = self.type
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceResult:
        return cls(
            device_id=d["device_id"],
            verdict=Verdict(d["verdict"]),
            confidence=float(d["confidence"]),
            family=d.get("family"),
            type=d.get("type"),
            matched_shot_id=d.get("matched_shot_id"),
            identity_confirmed=d.get("identity_confirmed", False),
            deltas=Deltas.from_dict(d.get("deltas")),
            approximate=d.get("approximate", False),
            notes=d.get("notes", []),
        )


@dataclass
class VerdictReport:
    schema_version: str
    project_id: str
    device_results: list[DeviceResult]
    units: str | None = None
    generated_at: str | None = None
    engine_version: str | None = None

    @property
    def summary(self) -> dict[str, int]:
        counts = {v.value: 0 for v in Verdict}
        for r in self.device_results:
            counts[r.verdict.value] += 1
        return {
            "total": len(self.device_results),
            "pass": counts[Verdict.PASS.value],
            "flag": counts[Verdict.FLAG.value],
            "absent": counts[Verdict.ABSENT.value],
            "type_mismatch": counts[Verdict.TYPE_MISMATCH.value],
        }

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "device_results": [r.to_dict() for r in self.device_results],
            "summary": self.summary,
        }
        if self.units is not None:
            out["units"] = self.units
        if self.generated_at is not None:
            out["generated_at"] = self.generated_at
        if self.engine_version is not None:
            out["engine_version"] = self.engine_version
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VerdictReport:
        return cls(
            schema_version=d["schema_version"],
            project_id=d["project_id"],
            device_results=[DeviceResult.from_dict(r) for r in d["device_results"]],
            units=d.get("units"),
            generated_at=d.get("generated_at"),
            engine_version=d.get("engine_version"),
        )

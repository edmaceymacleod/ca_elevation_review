"""Seeder F-04: coverage distinctions + orientation FLAG + up_axis no-op.

Single level, one depth shot at the origin. Exercises:
  * in-coverage ABSENT (device in frustum, no nearby obs) -> confidence 0.7;
  * coverage-gap ABSENT (device behind the camera) -> confidence 0.25;
  * orientation FLAG via facing_angle delta exceeding the orientation tolerance;
  * a device with ``up_axis="down"`` that still PASSes (documents that up_axis is
    not compared by the engine in v1).

Deterministic; regenerate via ``python -m fixtures.seeders.regen_goldens``.
"""

from __future__ import annotations

from . import _common as c

SLUG = "f04_coverage_orientation"


def build_manifest() -> dict:
    levels = [c.level("L1", "Level 1", 0.0, "plan_L1.png")]
    devices = [
        # In frustum, but no observation near it -> in-coverage ABSENT (0.7).
        c.device("D-INVIEW-ABSENT", "Speaker", "JBL-C6", 8.0, 0.0, 4.0, facing=0.0),
        # Behind camera -> coverage-gap ABSENT (0.25).
        c.device("D-GAP-ABSENT", "Camera", "AXIS-P32", -8.0, 0.0, 7.0, facing=180.0),
        # Orientation delta 30 > 10 -> FLAG.
        c.device("D-ORIENT-FLAG", "Card Reader", "HID-R10", 8.0, 2.0, 4.0, facing=0.0),
        # up_axis down; verdict still PASS (no-op on the verdict).
        c.device(
            "D-DOWN-PASS", "Card Reader", "HID-R10", 8.0, -2.0, 4.0, facing=0.0, up_axis="down"
        ),
    ]
    return c.manifest("demo-coverage-04", "Synthetic Coverage & Orientation", levels, devices)


def build_capture() -> dict:
    obs = [
        # D-ORIENT-FLAG: located but facing 30deg off.
        c.observation(8.0, 2.0, 4.0, mounting_height=4.0, facing=30.0),
        # D-DOWN-PASS: tight match, facing 1deg.
        c.observation(8.0, -2.0, 4.0, mounting_height=4.0, facing=1.0),
        # (No observation near D-INVIEW-ABSENT at (8,0,4); D-GAP-ABSENT is behind.)
    ]
    return c.capture("demo-coverage-04", [c.shot("S1", "L1", obs)])


def write():
    return c.write_payloads(SLUG, build_manifest(), build_capture())


def main() -> None:
    mpath, cpath = write()
    print(f"manifest: {mpath}")
    print(f"capture: {cpath}")


if __name__ == "__main__":
    main()

"""Seeder F-03: tolerance boundaries (just-inside vs just-outside).

Single level, one depth shot. Each axis (position / mounting_height /
orientation) gets a just-inside PASS and a just-outside FLAG, plus a per-device
tolerance override in both directions (tight -> FLAG, loose -> PASS). Deltas are
binary-exact (powers-of-two) to avoid FP brittleness.

Deterministic; regenerate via ``python -m fixtures.seeders.regen_goldens``.
"""

from __future__ import annotations

from . import _common as c

SLUG = "f03_tolerance_boundary"


def build_manifest() -> dict:
    levels = [c.level("L1", "Level 1", 0.0, "plan_L1.png")]
    devices = [
        c.device("D-POS-INSIDE", "Card Reader", "HID-R10", 8.0, 0.0, 4.0),
        c.device("D-POS-OUTSIDE", "Card Reader", "HID-R10", 8.0, 1.0, 4.0),
        c.device("D-HEIGHT-INSIDE", "Card Reader", "HID-R10", 8.0, 2.0, 4.0, mounting_height=4.0),
        c.device("D-HEIGHT-OUTSIDE", "Card Reader", "HID-R10", 8.0, 3.0, 4.0, mounting_height=4.0),
        c.device("D-ORIENT-INSIDE", "Card Reader", "HID-R10", 8.0, -1.0, 4.0, facing=0.0),
        c.device("D-ORIENT-OUTSIDE", "Card Reader", "HID-R10", 8.0, -2.0, 4.0, facing=0.0),
        c.device(
            "D-OVERRIDE-TIGHT",
            "Card Reader",
            "HID-R10",
            8.0,
            -3.0,
            4.0,
            tolerances={"position": 0.02},
        ),
        c.device(
            "D-OVERRIDE-LOOSE",
            "Card Reader",
            "HID-R10",
            8.0,
            4.0,
            4.0,
            tolerances={"position": 0.5},
        ),
    ]
    return c.manifest("demo-tolerance-03", "Synthetic Tolerance Boundary", levels, devices)


def build_capture() -> dict:
    obs = [
        # position delta 0.0625 < 0.083 -> PASS.
        c.observation(8.0625, 0.0, 4.0, facing=0.0),
        # position delta 0.25 (>0.083, <=0.5 gate) -> FLAG.
        c.observation(8.25, 1.0, 4.0, facing=0.0),
        # height delta 0.03125 < 0.042 -> PASS.
        c.observation(8.0, 2.0, 4.0, mounting_height=4.03125, facing=0.0),
        # height delta 0.125 > 0.042 -> FLAG.
        c.observation(8.0, 3.0, 4.0, mounting_height=4.125, facing=0.0),
        # orient delta 8 < 10 -> PASS.
        c.observation(8.0, -1.0, 4.0, facing=8.0),
        # orient delta 25 > 10 -> FLAG.
        c.observation(8.0, -2.0, 4.0, facing=25.0),
        # override tight: delta 0.0625 > 0.02 -> FLAG (still within gate 0.5).
        c.observation(8.0625, -3.0, 4.0, facing=0.0),
        # override loose: delta 0.25 < 0.5 -> PASS.
        c.observation(8.25, 4.0, 4.0, facing=0.0),
    ]
    return c.capture("demo-tolerance-03", [c.shot("S1", "L1", obs)])


def write():
    return c.write_payloads(SLUG, build_manifest(), build_capture())


def main() -> None:
    mpath, cpath = write()
    print(f"manifest: {mpath}")
    print(f"capture: {cpath}")


if __name__ == "__main__":
    main()

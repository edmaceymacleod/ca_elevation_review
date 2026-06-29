"""Seeder F-02: multi-level capture exercising the mounting-height datum.

Two levels with distinct nonzero elevations. Exercises:
  * expected height derived from ``position.z - level.elevation`` (no explicit
    mounting_height) across L1 (elevation 0) and L2 (elevation 12);
  * explicit ``mounting_height`` devices, one PASS (clean just-inside) and one
    FLAG (height delta just over the mounting-height tolerance).

Deterministic; regenerate via ``python -m fixtures.seeders.regen_goldens``.
"""

from __future__ import annotations

from . import _common as c

SLUG = "f02_multilevel_datum"


def build_manifest() -> dict:
    levels = [
        c.level("L1", "Level 1", 0.0, "plan_L1.png"),
        c.level("L2", "Level 2", 12.0, "plan_L2.png"),
    ]
    devices = [
        # Height from z - elevation = 4 - 0 = 4. Obs height 4.0 -> PASS.
        c.device("D-L1-PASS", "Card Reader", "HID-R10", 8.0, 0.0, 4.0, level_id="L1"),
        # Height from z - elevation = 16 - 12 = 4. Obs height 4.0 -> PASS (datum).
        c.device("D-L2-DATUM-PASS", "Card Reader", "HID-R10", 8.0, 0.0, 16.0, level_id="L2"),
        # Explicit mounting_height 4.0; obs 4.10 -> delta 0.10 > 0.042 -> FLAG.
        c.device(
            "D-L2-HEIGHT-FLAG",
            "Card Reader",
            "HID-R10",
            8.0,
            2.0,
            16.0,
            level_id="L2",
            mounting_height=4.0,
        ),
        # Explicit mounting_height 4.0; obs 4.03125 -> delta 0.03125 < 0.042 -> PASS.
        c.device(
            "D-L2-HEIGHT-PASS",
            "Card Reader",
            "HID-R10",
            8.0,
            -2.0,
            16.0,
            level_id="L2",
            mounting_height=4.0,
        ),
    ]
    return c.manifest("demo-multilevel-02", "Synthetic Multi-level", levels, devices)


def build_capture() -> dict:
    s1 = c.shot(
        "S1",
        "L1",
        [c.observation(8.0, 0.0, 4.0, mounting_height=4.0, facing=0.0)],
    )
    s2 = c.shot(
        "S2",
        "L2",
        [
            c.observation(8.0, 0.0, 16.0, mounting_height=4.0, facing=0.0),
            c.observation(8.0, 2.0, 16.0, mounting_height=4.10, facing=0.0),
            c.observation(8.0, -2.0, 16.0, mounting_height=4.03125, facing=0.0),
        ],
    )
    return c.capture("demo-multilevel-02", [s1, s2])


def write():
    return c.write_payloads(SLUG, build_manifest(), build_capture())


def main() -> None:
    mpath, cpath = write()
    print(f"manifest: {mpath}")
    print(f"capture: {cpath}")


if __name__ == "__main__":
    main()

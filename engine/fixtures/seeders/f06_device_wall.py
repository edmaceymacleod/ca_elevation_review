"""Seeder F-06: dense coplanar device wall + type-aware tie-break.

12 card readers on a vertical wall plane at x=8, spaced 0.6 ft apart, each with a
co-located correct observation. One device (D-W05) additionally has a closer
wrong-type decoy observation; the type-aware tie-break in ``compare.match_device``
must prefer the agreeing observation so D-W05 still PASSes (the decoy can't mask
the correct device).

Deterministic; regenerate via ``python -m fixtures.seeders.regen_goldens``.
"""

from __future__ import annotations

from . import _common as c

SLUG = "f06_device_wall"

YS = [-2.75 + 0.6 * i for i in range(12)]


def build_manifest() -> dict:
    levels = [c.level("L1", "Level 1", 0.0, "plan_L1.png")]
    devices = [
        c.device(f"D-W{i:02d}", "Card Reader", "HID-R10", 8.0, YS[i], 4.0, facing=0.0)
        for i in range(12)
    ]
    return c.manifest("demo-wall-06", "Synthetic Device Wall", levels, devices)


def build_capture() -> dict:
    obs = []
    for i in range(12):
        # Correct, type-agreeing observation (jitter <= 0.03).
        obs.append(
            c.observation(
                8.02,
                YS[i],
                4.0,
                mounting_height=4.0,
                facing=0.0,
                detected_type="HID-R10",
                type_confidence=0.85,
            )
        )
    # D-W05: closer wrong-type decoy that must NOT win the match.
    obs.append(
        c.observation(
            8.0,
            YS[5],
            4.0,
            mounting_height=4.0,
            facing=0.0,
            detected_type="Exit Sign",
            type_confidence=0.9,
        )
    )
    return c.capture("demo-wall-06", [c.shot("S1", "L1", obs)])


def write():
    return c.write_payloads(SLUG, build_manifest(), build_capture())


def main() -> None:
    mpath, cpath = write()
    print(f"manifest: {mpath}")
    print(f"capture: {cpath}")


if __name__ == "__main__":
    main()

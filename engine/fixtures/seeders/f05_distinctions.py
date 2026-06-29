"""Seeder F-05: TYPE_MISMATCH vs ABSENT vs FLAG vs low-confidence-no-mismatch.

Single level, one depth shot. Demonstrates all four verdict classes side by
side, including a low-confidence (``type_confidence < 0.6``) detected_type that
must NOT trigger TYPE_MISMATCH (proves the confidence gate).

Deterministic; regenerate via ``python -m fixtures.seeders.regen_goldens``.
"""

from __future__ import annotations

from . import _common as c

SLUG = "f05_distinctions"


def build_manifest() -> dict:
    levels = [c.level("L1", "Level 1", 0.0, "plan_L1.png")]
    devices = [
        c.device("D-TYPE", "Card Reader", "HID-R10", 7.5, 1.0, 4.0),
        c.device("D-TYPE-LOWCONF", "Card Reader", "HID-R10", 7.5, 2.0, 4.0),
        c.device("D-ABSENT", "Speaker", "JBL-C6", 8.0, -2.0, 4.0),
        c.device("D-FLAG", "Card Reader", "HID-R10", 8.0, 0.0, 4.0),
        c.device("D-PASS", "Card Reader", "HID-R10", 8.0, 3.0, 4.0),
    ]
    return c.manifest("demo-distinctions-05", "Synthetic Distinctions", levels, devices)


def build_capture() -> dict:
    obs = [
        # D-TYPE: confident wrong type -> TYPE_MISMATCH.
        c.observation(
            7.5,
            1.0,
            4.0,
            mounting_height=4.0,
            facing=0.0,
            detected_type="Exit Sign",
            type_confidence=0.9,
        ),
        # D-TYPE-LOWCONF: wrong type but low confidence -> NOT a mismatch -> PASS.
        c.observation(
            7.5,
            2.0,
            4.0,
            mounting_height=4.0,
            facing=0.0,
            detected_type="Exit Sign",
            type_confidence=0.4,
        ),
        # D-FLAG: 0.3 ft off in Y (within gate 0.5, over tol 0.083) -> FLAG.
        c.observation(8.0, 0.3, 4.0, mounting_height=4.0, facing=0.0),
        # D-PASS: tight match.
        c.observation(8.02, 3.0, 4.01, mounting_height=4.01, facing=0.0),
        # (No observation near D-ABSENT at (8,-2,4).)
    ]
    return c.capture("demo-distinctions-05", [c.shot("S1", "L1", obs)])


def write():
    return c.write_payloads(SLUG, build_manifest(), build_capture())


def main() -> None:
    mpath, cpath = write()
    print(f"manifest: {mpath}")
    print(f"capture: {cpath}")


if __name__ == "__main__":
    main()

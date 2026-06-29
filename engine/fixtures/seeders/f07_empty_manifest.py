"""Seeder F-07: zero-device manifest (degenerate empty corpus).

A schema-valid manifest with no devices, plus a capture with one shot whose
observations are necessarily ignored (there are no expected devices to match).
Proves the pipeline + output schema accept the empty case: empty
``device_results`` and an all-zero summary.

Deterministic; regenerate via ``python -m fixtures.seeders.regen_goldens``.
"""

from __future__ import annotations

from . import _common as c

SLUG = "f07_empty_manifest"


def build_manifest() -> dict:
    levels = [c.level("L1", "Level 1", 0.0, "plan_L1.png")]
    return c.manifest("demo-empty-07", "Synthetic Empty Manifest", levels, [])


def build_capture() -> dict:
    obs = [c.observation(8.0, 0.0, 4.0, mounting_height=4.0, facing=0.0)]
    return c.capture("demo-empty-07", [c.shot("S1", "L1", obs)])


def write():
    return c.write_payloads(SLUG, build_manifest(), build_capture())


def main() -> None:
    mpath, cpath = write()
    print(f"manifest: {mpath}")
    print(f"capture: {cpath}")


if __name__ == "__main__":
    main()

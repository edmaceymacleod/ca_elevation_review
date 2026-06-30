"""Seeder F-08: TYPE_MISMATCH driven by the engine's device-type heuristic.

Unlike F-05 (which hand-authors detected_type + type_confidence), this scenario
proves the *engine* populates them. The single observation for D-HEUR-TYPE
carries only a RAW, unscored detected_type hint ("illuminated exit sign") and no
type_confidence. The pipeline's typedetect.enrich_capture_types step canonicalizes
that hint to the known family "Exit Sign" (substring match, 0.7) which disagrees
with the expected type "HID-R10" -> TYPE_MISMATCH.

"Exit Sign" must be a real family in the manifest for the heuristic catalog to
contain it; D-EXIT provides one. D-EXIT's own observation carries NO detected_type
(a plain positional match) so it stays a clean PASS -- the heuristic emits FAMILY
strings, and a family ("Exit Sign") would not equal D-EXIT's SKU type ("EXIT-LED").

Deterministic; regenerate via ``python engine/tools/regen_fixtures.py`` (or
``python -m fixtures.seeders.regen_goldens``).
"""

from __future__ import annotations

from . import _common as c

SLUG = "f08_type_heuristic"


def build_manifest() -> dict:
    levels = [c.level("L1", "Level 1", 0.0, "plan_L1.png")]
    devices = [
        # Expected a card reader; the capture's raw hint reads "exit sign".
        c.device("D-HEUR-TYPE", "Card Reader", "HID-R10", 7.5, 1.0, 4.0),
        # Puts the family "Exit Sign" into the heuristic catalog. Clean PASS.
        c.device("D-EXIT", "Exit Sign", "EXIT-LED", 8.0, 3.0, 4.0),
    ]
    return c.manifest("demo-type-heuristic-08", "Synthetic Type Heuristic", levels, devices)


def build_capture() -> dict:
    obs = [
        # Raw, UNSCORED type hint -> the engine canonicalizes + scores it 0.7,
        # which disagrees with expected "HID-R10" -> TYPE_MISMATCH.
        c.observation(
            7.5,
            1.0,
            4.0,
            mounting_height=4.0,
            facing=0.0,
            detected_type="illuminated exit sign",
        ),
        # D-EXIT: clean positional match, no type signal -> PASS.
        c.observation(8.0, 3.0, 4.0, mounting_height=4.0, facing=0.0),
    ]
    return c.capture("demo-type-heuristic-08", [c.shot("S1", "L1", obs)])


def write():
    return c.write_payloads(SLUG, build_manifest(), build_capture())


def main() -> None:
    mpath, cpath = write()
    print(f"manifest: {mpath}")
    print(f"capture: {cpath}")


if __name__ == "__main__":
    main()

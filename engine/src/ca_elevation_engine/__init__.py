"""ca_elevation_engine -- the OSS core of the As-Built Elevation Verification Tool.

Given an expected device manifest (extracted from a Revit model) and a captured
site reality (RGB + LiDAR depth + ARKit pose + a floorplan pin), the engine
registers the capture into model coordinates, compares each expected device
against what was observed, and emits per-device verdicts plus an issuable report.

Public surface:

    from ca_elevation_engine import run_pipeline, __version__
    from ca_elevation_engine.models import SpecManifest, CapturePackage, VerdictReport

The engine is independently runnable and headlessly testable: heavy native
backends (Open3D / pye57 / OpenCV / CoreML) are optional extras, loaded lazily.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__", "run_pipeline"]


def run_pipeline(*args, **kwargs):
    """Lazy re-export of :func:`ca_elevation_engine.pipeline.run_pipeline`.

    Imported lazily so ``import ca_elevation_engine`` stays cheap and free of
    optional-backend imports.
    """
    from .pipeline import run_pipeline as _run

    return _run(*args, **kwargs)

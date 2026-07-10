"""3D-print validation — fable_run/out/00_manual.md §6.3 (FDM 0.4 mm nozzle) + mistakes P1–P4.

Emits the standard Row/Report envelope. Geometric checks run on the OCCT-tessellated mesh; the
slicer-oracle row shells out to the system `prusa-slicer` CLI (validated headless) — the ultimate
"is this actually sliceable" test. Rows the tooling can't compute are omitted, never faked.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple

import numpy as np

from .mesh_verify import _as_mesh, min_wall
from .verifier import Report, Row

_OVERHANG_THR = math.sin(math.radians(50))     # nz < −0.766 = steep unsupported overhang (§6.3)
DEFAULT_BED = (250.0, 210.0, 210.0)            # PrusaSlicer MK-class build volume (§6.3)


def _overhang_fraction(m) -> float:
    """Area fraction of steep down-facing faces above the first 1 mm (the bed layer is not an overhang)."""
    fn = m.face_normals
    ctr = m.triangles.mean(axis=1)
    zmin = float(m.bounds[0][2])
    area = m.area_faces
    steep = (fn[:, 2] < -_OVERHANG_THR) & (ctr[:, 2] > zmin + 1.0)
    return float(area[steep].sum() / max(area.sum(), 1e-9))


def _bed_contact_fraction(m) -> float:
    """Bed-contact face area / footprint bbox area (§6.3: ≥ 10% or needs a brim)."""
    ctr = m.triangles.mean(axis=1)
    zmin = float(m.bounds[0][2])
    on_bed = np.abs(ctr[:, 2] - zmin) < 0.5
    foot = float((m.bounds[1][0] - m.bounds[0][0]) * (m.bounds[1][1] - m.bounds[0][1]))
    return float(m.area_faces[on_bed].sum() / max(foot, 1e-9))


def slicer_oracle(solid, timeout: int = 150) -> Optional[Tuple[bool, Optional[str]]]:
    """§6.3 slicer oracle: export to STL and slice with the system prusa-slicer (default FFF profile).
    Returns (exit_ok, estimated_print_time) or None if prusa-slicer isn't installed (honest skip)."""
    exe = shutil.which("prusa-slicer")
    if exe is None:
        return None
    import cadquery as cq
    with tempfile.TemporaryDirectory() as d:
        stl, gco = os.path.join(d, "p.stl"), os.path.join(d, "p.gcode")
        cq.exporters.export(solid.val() if hasattr(solid, "val") else solid, stl)
        try:
            r = subprocess.run([exe, "--export-gcode", "--output", gco, stl],
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return (False, None)
        pt = None
        if r.returncode == 0 and os.path.exists(gco):
            for line in open(gco):
                if "estimated printing time" in line:
                    pt = line.strip().split("= ")[-1]
                    break
        return (r.returncode == 0, pt)


def verify_print(solid, *, min_wall_mm: float = 0.8, max_overhang_frac: float = 0.02,
                 min_bed_contact_frac: float = 0.10, bed: Tuple[float, float, float] = DEFAULT_BED,
                 run_slicer: bool = True, tol: float = 0.1) -> Report:
    """§6.3 FDM printability report. `valid` = watertight; single-solid contract per Report.passed."""
    m = _as_mesh(solid, tol)
    rows: List[Row] = []

    watertight = bool(m.is_watertight)
    rows.append(Row("print · watertight (single manifold)", True, watertight, watertight,
                    "ok" if watertight else "validity"))

    mw = min_wall(m)
    ok_w = mw is not None and mw >= min_wall_mm - 1e-3
    rows.append(Row("print · min_wall", f"≥{min_wall_mm}", round(mw, 3) if mw is not None else None,
                    ok_w, "ok" if ok_w else "dfm"))

    oh = _overhang_fraction(m)
    ok_oh = oh <= max_overhang_frac
    rows.append(Row("print · unsupported_overhang_area", f"≤{max_overhang_frac}", round(oh, 4),
                    ok_oh, "ok" if ok_oh else "dfm"))

    bc = _bed_contact_fraction(m)
    ok_bc = bc >= min_bed_contact_frac
    rows.append(Row("print · bed_contact_frac", f"≥{min_bed_contact_frac}", round(bc, 3),
                    ok_bc, "ok" if ok_bc else "dfm"))

    ext = (m.bounds[1] - m.bounds[0])
    fits = bool(ext[0] <= bed[0] and ext[1] <= bed[1] and ext[2] <= bed[2])
    rows.append(Row("print · fits_build_volume", f"≤{bed}", tuple(round(float(e), 1) for e in ext),
                    fits, "ok" if fits else "dfm"))

    if run_slicer:
        oracle = slicer_oracle(solid)
        if oracle is not None:
            exit_ok, pt = oracle
            rows.append(Row("print · slicer_oracle (prusa-slicer)", "exit 0", f"exit {'0' if exit_ok else 'nonzero'}"
                            + (f", {pt}" if pt else ""), exit_ok, "ok" if exit_ok else "dfm"))

    return Report(valid=watertight, solids=1 if watertight else int(m.body_count), volume=abs(float(m.volume)),
                  rows=rows)

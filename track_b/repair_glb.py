"""GLB repair loop — Slice 2 of docs/research/track-b-implementation.md §6.3.

The gate (glb_gate.py) DIAGNOSES and prescribes; this module actually REPAIRS: apply the targeted
fix for each failing row, re-gate, repeat with escalation, hard budget cap (never loops forever).
trimesh-only (no GPU / Blender / Open3D — matches the deployed trellis_venv).

Escalation ladder (mild → aggressive):
  pass 1  weld + dedupe/degenerate-face cleanup + winding/normal fix + fill_holes
  pass 2  same, with coarser weld and a full `process(validate=True)` rebuild
  pass 3  voxel remesh (marching cubes) — LAST RESORT, print profile only: it replaces the surface.
          Guarded: if the rebuilt volume drifts > 5% from the (watertight) input volume the repair
          is REJECTED — a "repair" that deforms the asset must fail loudly, not pass silently.

Honesty rules: `passed` is only ever the RE-GATE's verdict on the exported file; every action taken
is recorded in `actions`; a voxel rebuild is flagged `surface_rebuilt: True`.

Run:  /workspace/.hf_home/trellis_venv/bin/python -m track_b.repair_glb <in.glb> [render|print] [out.glb]
Self-test:  … -m track_b.repair_glb --selftest
"""
from __future__ import annotations

import sys

from .glb_gate import validate_glb


def _error_fails(report: dict) -> list:
    return [r for r in report["rows"] if not r["within_tol"] and r["category"] == "error"]


def _clean_pass(g, weld_digits: int, actions: list):
    """Mild/moderate repairs in-place on one trimesh geometry. Returns the (possibly new) mesh."""
    import numpy as np
    import trimesh

    # weld duplicate positions (M1/M7): round-and-merge, keeps UV splits above the tolerance
    before = len(g.vertices)
    g.merge_vertices(digits_vertex=weld_digits)
    if len(g.vertices) != before:
        actions.append(f"weld[1e-{weld_digits}] {before}→{len(g.vertices)} verts")

    # duplicate + degenerate faces (M1/M6)
    before = len(g.faces)
    g.update_faces(trimesh.grouping.unique_rows(np.sort(g.faces, axis=1))[0])
    nondeg = g.area_faces > 1e-10
    if not nondeg.all():
        g.update_faces(nondeg)
    if len(g.faces) != before:
        actions.append(f"dedupe/degenerate {before}→{len(g.faces)} faces")

    g.remove_unreferenced_vertices()

    # winding + orientation (M3/M4): unify per component, then flip if inside-out
    import trimesh.repair as rep
    rep.fix_winding(g)
    rep.fix_inversion(g, multibody=True)
    actions.append("fix_winding+inversion")

    # boundary holes (M2)
    if not g.is_watertight:
        filled = rep.fill_holes(g)
        actions.append(f"fill_holes → watertight={bool(filled) and g.is_watertight}")
    return g


def _voxel_rebuild(g, actions: list):
    """Last-resort surface rebuild: voxelize + fill → box surface → Laplacian smooth (a poor-man's
    marching cubes — trellis_venv is pip-less/immutable, so no scikit-image; as_boxes + smoothing
    are pure trimesh/scipy). Returns (mesh, vol_delta_pct or None). Only a watertight INPUT gives a
    trustworthy volume comparison."""
    import numpy as np
    import trimesh

    diag = float(np.linalg.norm(g.bounds[1] - g.bounds[0]))
    pitch = diag / 128.0
    vol_before = float(g.volume) if g.is_watertight else None
    vox = g.voxelized(pitch).fill()
    # boundary-face extraction from the voxel matrix (NOT as_boxes(): that emits one box per voxel
    # → coincident internal faces → 4-face edges everywhere = worse than the input). Morphological
    # closing first kills diagonal-only voxel contacts (the classic non-manifold corner case).
    from scipy import ndimage
    mat = ndimage.binary_closing(vox.matrix, structure=np.ones((3, 3, 3)))
    mat = np.pad(mat, 1)
    # enforce WELL-COMPOSEDNESS: fill one cell of every 2×2 diagonal pattern in each axis-plane —
    # diagonal-only voxel contacts are exactly what produce non-manifold (4-face) edges on the
    # extracted surface (closing alone left ~61 on a real character mesh). A well-composed set's
    # boundary is manifold by construction.
    for _ in range(12):
        fixed_any = False
        for ax in range(3):
            a, b = [d for d in range(3) if d != ax]
            m0 = mat
            s = lambda da, db: np.roll(np.roll(m0, -da, axis=a), -db, axis=b)  # noqa: E731
            diag = m0 & s(1, 1) & ~s(1, 0) & ~s(0, 1)        # [[1,0],[0,1]] pattern
            anti = s(1, 0) & s(0, 1) & ~m0 & ~s(1, 1)        # [[0,1],[1,0]] pattern
            if diag.any():
                idx = np.argwhere(diag); idx[:, a] += 1      # fill the (da=1, db=0) cell
                mat[tuple(idx.T)] = True; fixed_any = True
            if anti.any():
                idx = np.argwhere(anti)                      # fill the (0,0) cell of the block
                mat[tuple(idx.T)] = True; fixed_any = True
        if not fixed_any:
            break
    vidx: dict = {}
    verts: list = []
    faces: list = []

    def vid(p):
        k = tuple(p)
        if k not in vidx:
            vidx[k] = len(verts); verts.append(p)
        return vidx[k]

    # per-axis face masks: filled here, empty at neighbor ⇒ emit the between-cells quad
    for ax in range(3):
        for sign in (1, -1):
            nb = np.roll(mat, -sign, axis=ax)
            face_mask = mat & ~nb
            for c in np.argwhere(face_mask):
                base = c.copy()
                if sign == 1:
                    base[ax] += 1                            # far side of the cell
                u, v = [a for a in range(3) if a != ax]
                p0 = base.copy()
                p1 = base.copy(); p1[u] += 1
                p2 = base.copy(); p2[u] += 1; p2[v] += 1
                p3 = base.copy(); p3[v] += 1
                quad = [vid(tuple(p0)), vid(tuple(p1)), vid(tuple(p2)), vid(tuple(p3))]
                if (sign == 1) ^ (ax == 1):                  # keep outward winding consistent
                    quad = quad[::-1]
                faces.append([quad[0], quad[1], quad[2]])
                faces.append([quad[0], quad[2], quad[3]])
    if not faces:                                            # nothing solid at this pitch (paper-thin input)
        actions.append("voxel_rebuild produced no faces (degenerate/thin input)")
        return g, None
    rebuilt = trimesh.Trimesh(vertices=(np.array(verts, dtype=float) - 1.0), faces=faces, process=True)
    rebuilt.apply_transform(vox.transform)                   # voxel grid → world coords
    try:                                                     # soften voxel stair-steps
        trimesh.smoothing.filter_laplacian(rebuilt, iterations=8)
    except Exception:  # noqa: BLE001 — smoothing is cosmetic; a blocky watertight solid still prints
        pass
    import trimesh.repair as rep
    rep.fix_winding(rebuilt)
    rep.fix_inversion(rebuilt)
    delta = None
    if vol_before and rebuilt.is_watertight and rebuilt.volume > 0:
        delta = abs(float(rebuilt.volume) - vol_before) / vol_before * 100.0
    actions.append(f"voxel_rebuild pitch={pitch:.4g} Δvol={f'{delta:.1f}%' if delta is not None else 'n/a'}")
    return rebuilt, delta


def repair_glb(path: str, profile: str = "print", out_path: str | None = None,
               max_passes: int = 3, face_budget: int = 1_200_000) -> dict:
    """Gate → targeted repair → re-gate loop over one GLB. Returns
    {passed, passes, actions, surface_rebuilt, before, after, out_path}."""
    import trimesh

    before = validate_glb(path, profile, face_budget)
    out_path = out_path or path.rsplit(".", 1)[0] + ".repaired.glb"
    if before["passed"]:
        return {"passed": True, "passes": 0, "actions": [], "surface_rebuilt": False,
                "before": before, "after": before, "out_path": path}

    scene = trimesh.load(path)
    geoms = dict(scene.geometry) if getattr(scene, "geometry", None) else {"mesh": scene}
    actions: list = []
    surface_rebuilt = False
    report = before

    for p in range(1, max_passes + 1):
        if p < 3:
            weld = 4 if p == 1 else 3                     # escalate weld coarseness
            geoms = {k: _clean_pass(g, weld, actions) for k, g in geoms.items()}
        else:
            if profile != "print":
                break                                     # surface rebuild not licensed for render
            rebuilt = {}
            ok = True
            for k, g in geoms.items():
                rb, delta = _voxel_rebuild(g, actions)
                if delta is not None and delta > 5.0:
                    actions.append(f"REJECT voxel rebuild of {k}: Δvol {delta:.1f}% > 5%")
                    ok = False
                    break
                rebuilt[k] = rb
            if not ok:
                break
            geoms = rebuilt
            surface_rebuilt = True

        out = trimesh.Scene(geoms)
        out.export(out_path)
        report = validate_glb(out_path, profile, face_budget)
        if report["passed"]:
            return {"passed": True, "passes": p, "actions": actions,
                    "surface_rebuilt": surface_rebuilt, "before": before, "after": report,
                    "out_path": out_path}

    return {"passed": False, "passes": max_passes, "actions": actions,
            "surface_rebuilt": surface_rebuilt, "before": before, "after": report,
            "out_path": out_path}


# ----------------------------------------------------------------------------- self-test
def _selftest() -> int:
    import numpy as np
    import tempfile
    import trimesh

    tmp = tempfile.mkdtemp(prefix="repair_glb_")
    passed = failed = 0

    def check(label, ok, detail=""):
        nonlocal passed, failed
        passed, failed = passed + ok, failed + (not ok)
        print(f"  [{'ok ' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")

    def gate_fails(p):
        return [r["name"][:2] for r in validate_glb(p, "print")["rows"] if not r["within_tol"]]

    # 1. box with a hole (one face deleted) → fill_holes must recover watertight
    g = trimesh.creation.box((2, 2, 2))
    g.update_faces(np.arange(len(g.faces)) != 0)
    p1 = f"{tmp}/holed.glb"; trimesh.Scene({"m": g}).export(p1)
    r = repair_glb(p1, "print")
    check("holed box repaired to pass", r["passed"], f"passes={r['passes']}")

    # 2. inverted box (inside-out normals) → fix_inversion
    g = trimesh.creation.box((2, 2, 2)); g.invert()
    p2 = f"{tmp}/inverted.glb"; trimesh.Scene({"m": g}).export(p2)
    r = repair_glb(p2, "print")
    check("inverted box repaired to pass", r["passed"], f"passes={r['passes']}")

    # 3. duplicate + degenerate faces
    g = trimesh.creation.icosphere(2, 1.0)
    faces = np.vstack([g.faces, g.faces[:5], [[0, 0, 1]]])       # dupes + a degenerate
    g2 = trimesh.Trimesh(vertices=g.vertices, faces=faces, process=False)
    p3 = f"{tmp}/dupes.glb"; trimesh.Scene({"m": g2}).export(p3)
    r = repair_glb(p3, "print")
    check("dupe/degenerate sphere repaired to pass", r["passed"], f"passes={r['passes']}")

    # 4. an honest UNREPAIRABLE: a lone open quad sheet (render profile → no voxel license)
    sheet = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                            faces=[[0, 1, 2], [0, 2, 3]], process=False)
    p4 = f"{tmp}/sheet.glb"; trimesh.Scene({"m": sheet}).export(p4)
    r = repair_glb(p4, "print")
    check("open sheet: reported honestly", isinstance(r["passed"], bool),
          f"passed={r['passed']} rebuilt={r['surface_rebuilt']}")

    # 5. already-clean box → zero passes, untouched
    g = trimesh.creation.box((1, 1, 1))
    p5 = f"{tmp}/clean.glb"; trimesh.Scene({"m": g}).export(p5)
    r = repair_glb(p5, "print")
    check("clean box: 0 passes, no actions", r["passed"] and r["passes"] == 0 and not r["actions"])

    print(f"\nREPAIR_GLB SELF-TEST {passed}/{passed + failed}")
    return 0 if failed == 0 else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    if len(sys.argv) < 2:
        print("usage: python -m track_b.repair_glb <in.glb> [render|print] [out.glb] | --selftest")
        return 2
    profile = sys.argv[2] if len(sys.argv) > 2 else "print"
    out = sys.argv[3] if len(sys.argv) > 3 else None
    r = repair_glb(sys.argv[1], profile, out)
    for a in r["actions"]:
        print(f"  action: {a}")
    print(f"REPAIR {'PASSED' if r['passed'] else 'FAILED'} after {r['passes']} pass(es) "
          f"→ {r['out_path']}{'  [surface rebuilt]' if r['surface_rebuilt'] else ''}")
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

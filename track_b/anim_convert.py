"""GLB <-> Puppeteer rig conversion.

Converter A: SkinTokens-rigged GLB -> (mesh.obj, rig.txt) for Puppeteer's
video-guided animation optimizer (animation/optimization.py).

Converter B: optimizer output (local_quats.pt, root_quats.pt, root_pos.pt)
-> the same GLB with a glTF animation clip appended.

Conventions that this module bridges (all verified against the sources):
- Puppeteer quats are (w,x,y,z); glTF stores (x,y,z,w).
- Puppeteer joints have IDENTITY rest orientations; its FK is
  child_global = [Q_p * q_child,  Q_p @ offset + P_p].
- SkinTokens GLB bone nodes carry NON-identity rest rotations, so the glTF
  rotation channel for joint j is NOT q_j: the glTF pose global transform must
  equal [Q_j * Rhat_j, P_j] (Rhat_j = glTF global rest rotation), which we
  build numerically per frame and decompose into node-local TRS.
- Puppeteer normalizes verts+joints to a unit cube internally
  (utils/data_loader.py normalize_vertices: bbox center, max-extent scale);
  root translations come back in that normalized space.
"""

from __future__ import annotations

import json
import os
import struct

import numpy as np

# ---------------------------------------------------------------- quaternions
# internal convention: (w, x, y, z), matching Puppeteer's quat_utils


def _qmul(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    w1, x1, y1, z1 = np.moveaxis(q1, -1, 0)
    w2, x2, y2, z2 = np.moveaxis(q2, -1, 0)
    return np.stack(
        (
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ),
        axis=-1,
    )


def _qmat(q: np.ndarray) -> np.ndarray:
    """(...,4) wxyz -> (...,3,3) rotation matrices."""
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    w, x, y, z = np.moveaxis(q, -1, 0)
    m = np.empty(q.shape[:-1] + (3, 3), dtype=np.float64)
    m[..., 0, 0] = 1 - 2 * (y * y + z * z)
    m[..., 0, 1] = 2 * (x * y - w * z)
    m[..., 0, 2] = 2 * (x * z + w * y)
    m[..., 1, 0] = 2 * (x * y + w * z)
    m[..., 1, 1] = 1 - 2 * (x * x + z * z)
    m[..., 1, 2] = 2 * (y * z - w * x)
    m[..., 2, 0] = 2 * (x * z - w * y)
    m[..., 2, 1] = 2 * (y * z + w * x)
    m[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return m


def _mat_to_quat(m: np.ndarray) -> np.ndarray:
    """(3,3) -> (4,) wxyz. Shepperd's method."""
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        return np.array([0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s])
    i = int(np.argmax(np.diag(m)))
    if i == 0:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return np.array([(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s])
    if i == 1:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return np.array([(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s])
    s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return np.array([(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s])


def _trs(t, q, s=None) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = _qmat(np.asarray(q, dtype=np.float64))
    if s is not None:
        m[:3, :3] = m[:3, :3] @ np.diag(s)
    m[:3, 3] = t
    return m


# ---------------------------------------------------------------- GLB reading


def _load_gltf(glb_path: str):
    from pygltflib import GLTF2

    g = GLTF2().load(glb_path)
    blob = g.binary_blob()
    return g, blob


_CTYPE = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _read_accessor(g, blob, idx: int) -> np.ndarray:
    acc = g.accessors[idx]
    bv = g.bufferViews[acc.bufferView]
    n = _NCOMP[acc.type]
    fmt = _CTYPE[acc.componentType]
    itemsize = struct.calcsize(fmt)
    start = (bv.byteOffset or 0) + (acc.byteOffset or 0)
    stride = bv.byteStride or n * itemsize
    if stride == n * itemsize:
        out = np.frombuffer(blob, dtype=np.dtype(fmt), count=acc.count * n, offset=start)
    else:
        rows = [
            np.frombuffer(blob, dtype=np.dtype(fmt), count=n, offset=start + i * stride)
            for i in range(acc.count)
        ]
        out = np.concatenate(rows)
    return out.reshape(acc.count, n) if n > 1 else out.reshape(acc.count)


def _node_local(n) -> np.ndarray:
    if n.matrix:
        return np.array(n.matrix, dtype=np.float64).reshape(4, 4).T  # glTF is column-major
    t = n.translation or [0, 0, 0]
    r = n.rotation or [0, 0, 0, 1]  # xyzw
    s = n.scale or [1, 1, 1]
    return _trs(t, [r[3], r[0], r[1], r[2]], s)


def _rig_structure(g):
    """Skin joints, parents (within the joint set), root, and rest globals."""
    skin = g.skins[0]
    joints = list(skin.joints)
    jset = set(joints)
    parent_node = {}
    for i, n in enumerate(g.nodes):
        for c in n.children or []:
            parent_node[c] = i

    # global rest transform per node (walk up to scene root)
    cache = {}

    def gmat(i):
        if i in cache:
            return cache[i]
        m = _node_local(g.nodes[i])
        p = parent_node.get(i)
        out = m if p is None else gmat(p) @ m
        cache[i] = out
        return out

    parents = []  # index into `joints`, -1 for root
    for j in joints:
        p = parent_node.get(j)
        while p is not None and p not in jset:
            p = parent_node.get(p)
        parents.append(joints.index(p) if p is not None else -1)
    roots = [k for k, p in enumerate(parents) if p == -1]
    if len(roots) != 1:
        raise ValueError(f"expected exactly 1 root joint, found {len(roots)}")
    rest_global = np.stack([gmat(j) for j in joints])  # (J,4,4)
    return joints, parents, roots[0], rest_global, gmat, parent_node


# ------------------------------------------------------- A: GLB -> obj + rig


def glb_to_obj_rig(glb_path: str, out_dir: str, proxy_faces: int = 30000) -> dict:
    """Write mesh.obj + rig.txt (+ gray material.mtl) into out_dir/objs.

    If the mesh exceeds proxy_faces, the OBJ is a quadric-decimated PROXY with
    skin weights transferred by nearest original vertex — the optimizer only
    needs the mesh for its rendering losses; the motion it recovers lives on
    the skeleton, which the original GLB shares (Puppeteer: 20min@10k verts vs
    90min@70k — raw TRELLIS meshes are ~700k). Set proxy_faces=0 to disable.

    Returns meta needed by motion_to_glb (also written to rig_meta.json).
    """
    g, blob = _load_gltf(glb_path)
    objs = os.path.join(out_dir, "objs")
    os.makedirs(objs, exist_ok=True)

    meshes = [(i, n) for i, n in enumerate(g.nodes) if n.mesh is not None]
    if len(meshes) != 1:
        raise ValueError(f"expected exactly 1 mesh node, found {len(meshes)}")
    mesh_node_idx, mesh_node = meshes[0]
    prims = g.meshes[mesh_node.mesh].primitives
    if len(prims) != 1:
        raise ValueError(f"expected 1 primitive, found {len(prims)}")
    prim = prims[0]

    joints, parents, root, rest_global, gmat, _pn = _rig_structure(g)
    names = [g.nodes[j].name or f"bone_{k}" for k, j in enumerate(joints)]

    verts = _read_accessor(g, blob, prim.attributes.POSITION).astype(np.float64)
    mesh_g = gmat(mesh_node_idx)
    if not np.allclose(mesh_g, np.eye(4), atol=1e-6):
        verts = (verts @ mesh_g[:3, :3].T) + mesh_g[:3, 3]
    faces = _read_accessor(g, blob, prim.indices).reshape(-1, 3).astype(np.int64)
    jidx = _read_accessor(g, blob, prim.attributes.JOINTS_0).astype(np.int64)
    jw = _read_accessor(g, blob, prim.attributes.WEIGHTS_0).astype(np.float64)

    full_verts = verts
    if proxy_faces and len(faces) > proxy_faces:
        import trimesh
        from scipy.spatial import cKDTree

        proxy = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        proxy = proxy.simplify_quadric_decimation(face_count=proxy_faces)
        nearest = cKDTree(verts).query(np.asarray(proxy.vertices))[1]
        verts = np.asarray(proxy.vertices, dtype=np.float64)
        faces = np.asarray(proxy.faces, dtype=np.int64)
        jidx, jw = jidx[nearest], jw[nearest]

    with open(os.path.join(objs, "material.mtl"), "w") as f:
        f.write("newmtl gray\nKd 0.62 0.62 0.62\nKa 0.2 0.2 0.2\nKs 0.05 0.05 0.05\n")
    with open(os.path.join(objs, "mesh.obj"), "w") as f:
        f.write("mtllib material.mtl\nusemtl gray\n")
        for v in verts:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for a, b, c in faces + 1:
            f.write(f"f {a} {b} {c}\n")

    jpos = rest_global[:, :3, 3]
    lines = [f"joints {names[k]} {p[0]:.8f} {p[1]:.8f} {p[2]:.8f}" for k, p in enumerate(jpos)]
    lines.append(f"root {names[root]}")
    for v_i in range(len(verts)):
        row = [(int(jidx[v_i, s]), float(jw[v_i, s])) for s in range(jidx.shape[1]) if jw[v_i, s] > 1e-6]
        if not row:
            continue
        tot = sum(w for _, w in row)
        parts = " ".join(f"{names[j]} {w / tot:.6f}" for j, w in row)
        lines.append(f"skin {v_i} {parts}")
    for k, p in enumerate(parents):
        if p >= 0:
            lines.append(f"hier {names[p]} {names[k]}")
    with open(os.path.join(objs, "rig.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")

    # normalization Puppeteer's loader will apply (data_loader.normalize_vertices)
    vmin, vmax = verts.min(axis=0), verts.max(axis=0)
    center = (vmax + vmin) / 2.0
    scale = float((vmax - vmin).max())
    meta = {
        "joint_names": names,
        "center": center.tolist(),
        "scale": scale,
        "n_verts": int(len(verts)),
        "n_verts_full": int(len(full_verts)),
        "n_faces": int(len(faces)),
        "n_joints": len(joints),
        "root": int(root),
    }
    with open(os.path.join(out_dir, "rig_meta.json"), "w") as f:
        json.dump(meta, f)
    return meta


# --------------------------------------------- B: motion -> animated GLB


def _pad4(b: bytes) -> bytes:
    return b + b"\x00" * (-len(b) % 4)


def motion_to_glb(glb_path: str, motion_dir: str, out_path: str, fps: float = 10.0,
                  clip_name: str = "clip") -> dict:
    """Append a glTF animation built from Puppeteer optimizer output.

    motion_dir must contain local_quats.pt (T,J,4), root_quats.pt (T,4),
    root_pos.pt (T,3) — all (w,x,y,z), root pos in Puppeteer's normalized space.
    """
    import torch
    from pygltflib import (GLTF2, Accessor, Animation, AnimationChannel,
                           AnimationChannelTarget, AnimationSampler, BufferView)

    g, blob = _load_gltf(glb_path)
    joints, parents, root, rest_global, gmat, parent_node = _rig_structure(g)
    J = len(joints)

    def _load(name):
        return torch.load(os.path.join(motion_dir, name), map_location="cpu").detach().to(torch.float64).numpy()

    lq = _load("local_quats.pt")
    if lq.ndim != 3 or lq.shape[1] != J:
        raise ValueError(f"local_quats {lq.shape} vs J={J}")
    T = lq.shape[0]
    rq = _load("root_quats.pt") if os.path.exists(os.path.join(motion_dir, "root_quats.pt")) else None
    rp = _load("root_pos.pt") if os.path.exists(os.path.join(motion_dir, "root_pos.pt")) else None

    # Puppeteer works in normalized coords; undo for world-space root motion.
    meta_path = os.path.join(os.path.dirname(motion_dir.rstrip("/")), "..", "rig_meta.json")
    verts_meta = None
    for cand in (os.path.join(motion_dir, "rig_meta.json"),
                 os.path.abspath(meta_path),
                 os.path.join(os.path.dirname(glb_path), "rig_meta.json")):
        if os.path.exists(cand):
            with open(cand) as f:
                verts_meta = json.load(f)
            break
    if verts_meta is None:
        raise FileNotFoundError("rig_meta.json (from glb_to_obj_rig) not found")
    center = np.array(verts_meta["center"], dtype=np.float64)
    scale = float(verts_meta["scale"])

    # Puppeteer FK in normalized space, then lift to world:
    # W_j(t) = T(center) S(scale) [RootT * G_j(t)] S(1/scale) T(-center) * Rhat_j
    jpos_w = rest_global[:, :3, 3]                       # world rest joint positions
    jpos_n = (jpos_w - center) / scale                   # normalized (matches rig.txt after loader norm)
    offsets = np.zeros((J, 3))
    for k in range(J):
        offsets[k] = jpos_n[k] - (jpos_n[parents[k]] if parents[k] >= 0 else 0.0)

    order = []                                            # topological
    pend = [root]
    childs = [[] for _ in range(J)]
    for k, p in enumerate(parents):
        if p >= 0:
            childs[p].append(k)
    while pend:
        cur = pend.pop(0)
        order.append(cur)
        pend.extend(childs[cur])

    Qg = np.zeros((T, J, 4))
    Pg = np.zeros((T, J, 3))
    for k in order:
        if parents[k] < 0:
            Qg[:, k] = lq[:, k]
            Pg[:, k] = jpos_n[k]
        else:
            p = parents[k]
            Qg[:, k] = _qmul(Qg[:, p], lq[:, k])
            Pg[:, k] = np.einsum("tij,j->ti", _qmat(Qg[:, p]), offsets[k]) + Pg[:, p]
    if rq is not None and rp is not None:
        Rm = _qmat(rq)
        Pg = np.einsum("tij,tkj->tki", Rm, Pg) + rp[:, None, :]
        Qg = _qmul(rq[:, None, :], Qg)

    # world-space global pose matrices per joint per frame
    Mw = np.tile(np.eye(4), (T, J, 1, 1))
    # M_j = W_j @ rest_global_j with W_j the de-normalized Puppeteer skinning
    # transform; the algebra collapses to rotation Q_j*Rhat_j, translation P_j*s+c.
    Mw[..., :3, :3] = _qmat(Qg) @ rest_global[None, :, :3, :3]
    Mw[..., :3, 3] = Pg * scale + center

    # decompose into node-local TRS (parent = joint parent, else the node chain above root)
    rot_channels = np.zeros((J, T, 4))                    # xyzw for glTF
    trans_channels = np.zeros((J, T, 3))
    inv_parent = np.zeros((T, 4, 4))
    for k in order:
        if parents[k] < 0:
            above = parent_node.get(joints[k])
            A = gmat(above) if above is not None else np.eye(4)
            Minv = np.linalg.inv(A)[None].repeat(T, axis=0)
        else:
            Minv = np.linalg.inv(Mw[:, parents[k]])
        L = Minv @ Mw[:, k]
        trans_channels[k] = L[:, :3, 3]
        for t in range(T):
            q = _mat_to_quat(L[t, :3, :3])
            if t > 0 and np.dot(q, prev) < 0:             # keep quat continuity
                q = -q
            prev = q
            rot_channels[k, t] = [q[1], q[2], q[3], q[0]]

    # append binary data: times + per-joint rotation (+ root translation)
    blob = bytearray(_pad4(bytes(blob)))
    g.bufferViews = g.bufferViews or []
    g.accessors = g.accessors or []

    def _push(arr: np.ndarray, acc_type: str):
        data = _pad4(arr.astype(np.float32).tobytes())
        off = len(blob)
        blob.extend(data)
        g.bufferViews.append(BufferView(buffer=0, byteOffset=off, byteLength=len(data)))
        flat = arr.reshape(arr.shape[0], -1) if arr.ndim > 1 else arr.reshape(-1, 1)
        g.accessors.append(Accessor(
            bufferView=len(g.bufferViews) - 1, componentType=5126, count=arr.shape[0],
            type=acc_type, max=flat.max(axis=0).tolist(), min=flat.min(axis=0).tolist()))
        return len(g.accessors) - 1

    times = np.arange(T, dtype=np.float32) / fps
    t_acc = _push(times, "SCALAR")

    samplers, channels = [], []
    for k in range(J):
        r_acc = _push(rot_channels[k], "VEC4")
        samplers.append(AnimationSampler(input=t_acc, interpolation="LINEAR", output=r_acc))
        channels.append(AnimationChannel(
            sampler=len(samplers) - 1,
            target=AnimationChannelTarget(node=joints[k], path="rotation")))
        # translations: constant for non-root by construction; root carries motion
        if k == root or np.ptp(trans_channels[k], axis=0).max() > 1e-5:
            p_acc = _push(trans_channels[k], "VEC3")
            samplers.append(AnimationSampler(input=t_acc, interpolation="LINEAR", output=p_acc))
            channels.append(AnimationChannel(
                sampler=len(samplers) - 1,
                target=AnimationChannelTarget(node=joints[k], path="translation")))

    g.animations = g.animations or []
    g.animations.append(Animation(name=clip_name, samplers=samplers, channels=channels))
    g.buffers[0].byteLength = len(blob)
    g.set_binary_blob(bytes(blob))
    g.save(out_path)
    return {"frames": int(T), "joints": J, "duration_s": float(times[-1]) if T else 0.0,
            "channels": len(channels)}

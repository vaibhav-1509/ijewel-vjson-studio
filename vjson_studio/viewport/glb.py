"""Load a .glb into plain numpy meshes, decoding Draco-compressed primitives.

VTK's own glTF importer refuses files that *require* KHR_draco_mesh_compression,
which is how iJewel/Blender export jewellery, so geometry is decoded here with
pygltflib + DracoPy and handed to the viewport as world-space triangles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pygltflib

DRACO = "KHR_draco_mesh_compression"

_COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


@dataclass
class MeshPart:
    node: str
    material: str              # glTF material name - matches vjson configurator titles
    points: np.ndarray         # (n, 3) float64, world space
    faces: np.ndarray          # (m, 3) int64
    base_color: tuple = (0.8, 0.8, 0.8)
    metallic: float = 1.0
    roughness: float = 0.3


@dataclass
class GlbModel:
    path: Path
    parts: list[MeshPart] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def triangles(self) -> int:
        return sum(len(p.faces) for p in self.parts)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.parts:
            return np.zeros(3), np.zeros(3)
        allp = np.concatenate([p.points for p in self.parts])
        return allp.min(axis=0), allp.max(axis=0)


def _buffer_view_bytes(g: pygltflib.GLTF2, blob: bytes, index: int) -> bytes:
    bv = g.bufferViews[index]
    start = bv.byteOffset or 0
    return blob[start:start + bv.byteLength]


def _accessor(g: pygltflib.GLTF2, blob: bytes, index: int) -> np.ndarray:
    acc = g.accessors[index]
    dtype = np.dtype(_COMPONENT[acc.componentType])
    n = _NCOMP[acc.type]
    if acc.bufferView is None:
        return np.zeros((acc.count, n), dtype)
    bv = g.bufferViews[acc.bufferView]
    data = _buffer_view_bytes(g, blob, acc.bufferView)
    off = acc.byteOffset or 0
    stride = bv.byteStride or dtype.itemsize * n
    if stride == dtype.itemsize * n:
        arr = np.frombuffer(data, dtype, acc.count * n, off).reshape(acc.count, n)
    else:
        rows = [np.frombuffer(data, dtype, n, off + i * stride) for i in range(acc.count)]
        arr = np.stack(rows)
    return arr


def _node_matrix(node) -> np.ndarray:
    if node.matrix:
        return np.array(node.matrix, dtype=float).reshape(4, 4).T     # glTF is column-major
    t = np.array(node.translation or [0, 0, 0], dtype=float)
    x, y, z, w = node.rotation or [0, 0, 0, 1]
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    s = np.array(node.scale or [1, 1, 1], dtype=float)
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def _primitive_geometry(g, blob, prim, warnings):
    ext = (prim.extensions or {}).get(DRACO)
    if ext:
        import DracoPy
        raw = _buffer_view_bytes(g, blob, ext["bufferView"])
        mesh = DracoPy.decode(raw)
        pts = np.asarray(mesh.points, dtype=float).reshape(-1, 3)
        faces = np.asarray(mesh.faces, dtype=np.int64).reshape(-1, 3)
        return pts, faces
    if prim.mode not in (None, 4):
        warnings.append(f"skipped a primitive with draw mode {prim.mode} (only triangles are shown)")
        return None
    pos = getattr(prim.attributes, "POSITION", None)
    if pos is None:
        return None
    pts = _accessor(g, blob, pos).astype(float)
    if prim.indices is not None:
        faces = _accessor(g, blob, prim.indices).astype(np.int64).reshape(-1, 3)
    else:
        faces = np.arange(len(pts), dtype=np.int64).reshape(-1, 3)
    return pts, faces


def load_glb(path: str | Path) -> GlbModel:
    path = Path(path)
    g = pygltflib.GLTF2().load(str(path))
    blob = g.binary_blob() or b""
    model = GlbModel(path, extensions=list(g.extensionsUsed or []))
    unknown_required = [e for e in (g.extensionsRequired or []) if e != DRACO]
    if unknown_required:
        model.warnings.append("required extensions not understood (geometry still shown): " + ", ".join(unknown_required))

    def material_info(idx):
        if idx is None or idx >= len(g.materials):
            return "", (0.8, 0.8, 0.8), 1.0, 0.3
        m = g.materials[idx]
        pbr = m.pbrMetallicRoughness
        col = tuple((pbr.baseColorFactor or [0.8, 0.8, 0.8, 1])[:3]) if pbr else (0.8, 0.8, 0.8)
        met = pbr.metallicFactor if pbr and pbr.metallicFactor is not None else 1.0
        rough = pbr.roughnessFactor if pbr and pbr.roughnessFactor is not None else 1.0
        return m.name or f"material_{idx}", col, met, rough

    def walk(ni, parent):
        node = g.nodes[ni]
        world = parent @ _node_matrix(node)
        if node.mesh is not None:
            for prim in g.meshes[node.mesh].primitives:
                geo = _primitive_geometry(g, blob, prim, model.warnings)
                if geo is None:
                    continue
                pts, faces = geo
                pts = pts @ world[:3, :3].T + world[:3, 3]
                name, col, met, rough = material_info(prim.material)
                model.parts.append(MeshPart(node.name or f"node_{ni}", name, pts, faces, col, met, rough))
        for c in node.children or []:
            walk(c, world)

    scene = g.scenes[g.scene or 0] if g.scenes else None
    roots = scene.nodes if scene else range(len(g.nodes))
    for ni in roots:
        walk(ni, np.eye(4))
    return model

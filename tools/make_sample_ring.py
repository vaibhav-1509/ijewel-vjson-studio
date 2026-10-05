"""Write tests/fixtures/sample_ring.glb - a simple synthetic ring (band, head, gem).

It exists so tests and screenshots never need a real jewellery model. Material
names match the configurator titles in tests/fixtures/sample.vjson.
    .venv\\Scripts\\python tools\\make_sample_ring.py
"""
from pathlib import Path

import numpy as np
import pygltflib as G
import pyvista as pv

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample_ring.glb"


def triangles(mesh):
    m = mesh.triangulate().clean()
    return np.asarray(m.points, np.float32), np.asarray(m.faces.reshape(-1, 4)[:, 1:], np.uint32)


def main():
    # Y is up (glTF / three.js). The band stands in the XY plane, the stone sits on top.
    band = pv.ParametricTorus(ringradius=1.0, crosssectionradius=0.12, u_res=96, v_res=24, w_res=2)
    head = pv.Cylinder(center=(0, 1.16, 0), direction=(0, 1, 0), radius=0.26, height=0.14, resolution=32)
    gem = pv.Cone(center=(0, 1.40, 0), direction=(0, -1, 0), height=0.34, radius=0.40, resolution=16).merge(
        pv.Cylinder(center=(0, 1.60, 0), direction=(0, 1, 0), radius=0.40, height=0.06, resolution=16))
    parts = [("band", "metal-main", band), ("head", "metal-main", head), ("gem", "mainstone-round-white", gem)]
    mats = [G.Material(name="metal-main", pbrMetallicRoughness=G.PbrMetallicRoughness(
                baseColorFactor=[0.8, 0.8, 0.8, 1], metallicFactor=1, roughnessFactor=0.2)),
            G.Material(name="mainstone-round-white", pbrMetallicRoughness=G.PbrMetallicRoughness(
                baseColorFactor=[1, 1, 1, 1], metallicFactor=0, roughnessFactor=0.05))]
    mat_index = {m.name: i for i, m in enumerate(mats)}
    blob = b""
    views, accessors, meshes, nodes = [], [], [], []
    for name, mat, mesh in parts:
        pts, faces = triangles(mesh)
        for arr, target, ctype, typ in ((faces.ravel(), 34963, 5125, "SCALAR"), (pts, 34962, 5126, "VEC3")):
            data = arr.tobytes()
            blob += b"\0" * ((-len(blob)) % 4)
            views.append(G.BufferView(buffer=0, byteOffset=len(blob), byteLength=len(data), target=target))
            blob += data
            extra = {"min": pts.min(0).tolist(), "max": pts.max(0).tolist()} if typ == "VEC3" else {}
            accessors.append(G.Accessor(bufferView=len(views) - 1, componentType=ctype, type=typ,
                                        count=len(arr) if typ == "SCALAR" else len(pts), **extra))
        meshes.append(G.Mesh(name=name, primitives=[G.Primitive(attributes=G.Attributes(POSITION=len(accessors) - 1),
                                                                indices=len(accessors) - 2, material=mat_index[mat])]))
        nodes.append(G.Node(name=name, mesh=len(meshes) - 1))
    g = G.GLTF2(scene=0, scenes=[G.Scene(nodes=list(range(len(nodes))))], nodes=nodes, meshes=meshes, materials=mats,
                accessors=accessors, bufferViews=views, buffers=[G.Buffer(byteLength=len(blob))],
                asset=G.Asset(generator="vjson Studio 3D sample"))
    g.set_binary_blob(blob)
    g.save_binary(str(OUT))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

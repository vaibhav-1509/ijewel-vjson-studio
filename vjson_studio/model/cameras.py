"""iJewel3D camera views: the CameraViews plugin and the maths behind it.

A view stores position and target; quaternion and up are derived from them
exactly as three.js ``Object3D.lookAt`` does for a camera with world-up
(0, 1, 0). ``look_at_orient`` is a direct port of the reference editor's
verified ``lookAtOrient``.
"""
from __future__ import annotations

import math
import re
from typing import Any, Sequence

Vec = Sequence[float]

CAMERA_VIEWS_DEFAULTS = {
    "viewLooping": False, "viewPauseTime": 200, "animEase": "easeInOutSine",
    "animDuration": 1000, "rotationOffset": 0.25, "interpolateMode": "spherical",
    "splineCurve": "chordal", "seekOnScroll": False,
}
EASES = ["linear", "easeInSine", "easeOutSine", "easeInOutSine", "easeInQuad", "easeOutQuad",
         "easeInOutQuad", "easeInCubic", "easeOutCubic", "easeInOutCubic"]


def v3(x: float, y: float, z: float) -> dict:
    return {"x": x, "y": y, "z": z, "isVector3": True}


def xyz(v: dict) -> tuple[float, float, float]:
    return (v["x"], v["y"], v["z"])


def look_at_orient(pos: Vec, tgt: Vec) -> dict:
    z = [pos[0] - tgt[0], pos[1] - tgt[1], pos[2] - tgt[2]]
    l = math.hypot(*z) or 1
    z = [a / l for a in z]
    up = (0, 1, 0)
    x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]]
    l = math.hypot(*x)
    if l < 1e-8:                        # looking straight up or down
        x, l = [1, 0, 0], 1
    x = [a / l for a in x]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    m11, m12, m13 = x[0], y[0], z[0]
    m21, m22, m23 = x[1], y[1], z[1]
    m31, m32, m33 = x[2], y[2], z[2]
    tr = m11 + m22 + m33
    if tr > 0:
        s = 0.5 / math.sqrt(tr + 1)
        qw, qx, qy, qz = 0.25 / s, (m32 - m23) * s, (m13 - m31) * s, (m21 - m12) * s
    elif m11 > m22 and m11 > m33:
        s = 2 * math.sqrt(1 + m11 - m22 - m33)
        qw, qx, qy, qz = (m32 - m23) / s, 0.25 * s, (m12 + m21) / s, (m13 + m31) / s
    elif m22 > m33:
        s = 2 * math.sqrt(1 + m22 - m11 - m33)
        qw, qx, qy, qz = (m13 - m31) / s, (m12 + m21) / s, 0.25 * s, (m23 + m32) / s
    else:
        s = 2 * math.sqrt(1 + m33 - m11 - m22)
        qw, qx, qy, qz = (m21 - m12) / s, (m13 + m31) / s, (m23 + m32) / s, 0.25 * s
    return {"quaternion": {"x": qx, "y": qy, "z": qz, "w": qw, "isQuaternion": True},
            "up": {"x": y[0], "y": y[1], "z": y[2], "isVector3": True}}


def reorient(view: dict) -> None:
    view.update(look_at_orient(xyz(view["position"]), xyz(view["target"])))


def make_view(name: str, pos: Vec, tgt: Vec, duration: float = 1) -> dict:
    view = {"position": v3(*pos), "target": v3(*tgt), "quaternion": None, "up": None,
            "duration": duration, "name": name, "serializableClassId": "CameraView"}
    reorient(view)
    return view


def has_custom_orientation(view: dict, tol: float = 1e-3) -> bool:
    """True when the stored quaternion is not a plain look-at (roll, other aim)."""
    q = view.get("quaternion")
    if not q:
        return True
    o = look_at_orient(xyz(view["position"]), xyz(view["target"]))["quaternion"]
    return sum(abs(o[k] - q[k]) for k in "xyzw") > tol


def camera_views_plugin(doc: dict, create: bool = False) -> dict | None:
    p = next((p for p in doc["plugins"] if p.get("type") == "CameraViews"), None)
    if p is None and create:
        p = {"cameraViews": [], **CAMERA_VIEWS_DEFAULTS, "type": "CameraViews"}
        doc["plugins"].append(p)
    return p


def views(doc: dict) -> list[dict]:
    p = camera_views_plugin(doc)
    return p.get("cameraViews", []) if p else []


def next_view_name(doc: dict) -> str:
    nums = [int(m.group(1)) for v in views(doc) if (m := re.match(r"^#view(\d+)$", v.get("name") or ""))]
    return f"#view{(max(nums) if nums else 0) + 1}"


def default_camera(doc: dict) -> dict:
    return doc["scene"]["defaultCamera"]


def default_fov(doc: dict) -> float:
    """Vertical field of view in degrees, as iJewel renders it."""
    return float(default_camera(doc).get("camOptions", {}).get("fov", 45))

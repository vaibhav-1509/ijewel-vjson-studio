"""Viewport maths with no GL: display fit, frustums, framing, easing, fly-to."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

IJEWEL_RADIUS = 2.0        # iJewel auto-scales a loaded model to about this radius


@dataclass
class DisplayFit:
    """Display-only model transform. Never written into the vjson."""
    mode: str = "ijewel"       # "ijewel" (centre + radius 2), or "raw"
    offset: tuple = (0.0, 0.0, 0.0)
    scale: float = 1.0          # extra uniform scale on top of the mode

    def matrix(self, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        m = np.eye(4)
        s, c = 1.0, np.zeros(3)
        if self.mode == "ijewel":
            c = (lo + hi) / 2
            r = float(np.linalg.norm(hi - lo)) / 2
            s = IJEWEL_RADIUS / r if r > 0 else 1.0
        s *= self.scale
        m[:3, :3] *= s
        m[:3, 3] = -c * s + np.asarray(self.offset, float)
        return m


def nice_step(x: float) -> float:
    """1, 2 or 5 x 10^k at or above x - the spacing 3D packages use for grid lines."""
    if x <= 0:
        return 1.0
    e = math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * 10 ** e >= x - 1e-12:
            return m * 10 ** e
    return 10 ** (e + 1)


def ground_grid(extent: float, y: float = 0.0, cells: int = 20, major_every: int = 5):
    """Line sets for a ground grid centred on the world origin, on the plane at ``y``.

    Returns {"minor", "major", "x_axis", "z_axis"} -> (points (n, 3), VTK line cells).
    The X axis line runs along X at z=0 (red), the Z axis along Z at x=0 (blue),
    as in Blender/Maya; Y is up.
    """
    step = nice_step(max(extent, 1e-6) / cells)
    n = max(int(math.ceil(extent / step)), 1)
    half = n * step
    sets = {"minor": [], "major": [], "x_axis": [], "z_axis": []}
    for i in range(-n, n + 1):
        c = i * step
        along_x = ((-half, y, c), (half, y, c))     # line parallel to X at z = c
        along_z = ((c, y, -half), (c, y, half))     # line parallel to Z at x = c
        if i == 0:
            sets["x_axis"].append(along_x)
            sets["z_axis"].append(along_z)
        else:
            key = "major" if i % major_every == 0 else "minor"
            sets[key] += [along_x, along_z]
    out = {}
    for k, segs in sets.items():
        pts = np.array([p for s in segs for p in s], dtype=float).reshape(-1, 3)
        cells_ = np.array([v for j in range(len(segs)) for v in (2, 2 * j, 2 * j + 1)], dtype=np.int64)
        out[k] = (pts, cells_)
    out["half"], out["step"] = half, step
    return out


def basis(pos, tgt):
    """Camera right/up/forward for a look-at with world-up Y (three.js convention)."""
    pos, tgt = np.asarray(pos, float), np.asarray(tgt, float)
    fwd = tgt - pos
    n = np.linalg.norm(fwd)
    fwd = fwd / n if n else np.array([0, 0, -1.0])
    right = np.cross(fwd, [0, 1, 0])
    if np.linalg.norm(right) < 1e-8:
        right = np.array([1.0, 0, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return right, up, fwd


def frustum(pos, tgt, fov_deg: float, aspect: float, depth: float):
    """Points (5, 3) and VTK line cells for a camera glyph: apex + far rectangle."""
    right, up, fwd = basis(pos, tgt)
    p = np.asarray(pos, float)
    h = math.tan(math.radians(fov_deg) / 2) * depth
    w = h * aspect
    c = p + fwd * depth
    pts = np.array([p, c + up * h - right * w, c + up * h + right * w, c - up * h + right * w, c - up * h - right * w])
    lines = []
    for a, b in [(0, 1), (0, 2), (0, 3), (0, 4), (1, 2), (2, 3), (3, 4), (4, 1)]:
        lines += [2, a, b]
    # small "up" tick so the glyph shows which way is up
    pts = np.vstack([pts, c + up * h * 1.35])
    lines += [2, 1, 5, 2, 2, 5]
    return pts, np.array(lines)


def framing(view_w: int, view_h: int, aspect: float, fov_deg: float):
    """Where iJewel's canvas of ``aspect`` falls inside our viewport.

    iJewel keeps the *vertical* fov. When its canvas is wider than ours we widen
    our own vertical fov so the same horizontal extent fits, and the frame is
    letterboxed. Returns (our_fov_deg, (x0, y0, x1, y1)) in pixels.
    """
    ours = view_w / max(view_h, 1)
    if aspect <= ours:
        fw = view_h * aspect
        x0 = (view_w - fw) / 2
        return fov_deg, (x0, 0.0, x0 + fw, float(view_h))
    t = math.tan(math.radians(fov_deg) / 2) * aspect / ours
    our_fov = math.degrees(2 * math.atan(t))
    fh = view_w / aspect
    y0 = (view_h - fh) / 2
    return our_fov, (0.0, y0, float(view_w), y0 + fh)


def _ease_table():
    s = math.sin
    c = math.cos
    pi = math.pi
    return {
        "linear": lambda t: t,
        "easeInSine": lambda t: 1 - c(t * pi / 2),
        "easeOutSine": lambda t: s(t * pi / 2),
        "easeInOutSine": lambda t: -(c(pi * t) - 1) / 2,
        "easeInQuad": lambda t: t * t,
        "easeOutQuad": lambda t: 1 - (1 - t) ** 2,
        "easeInOutQuad": lambda t: 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2,
        "easeInCubic": lambda t: t ** 3,
        "easeOutCubic": lambda t: 1 - (1 - t) ** 3,
        "easeInOutCubic": lambda t: 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2,
    }


EASE = _ease_table()


def ease(name: str, t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return EASE.get(name, EASE["easeInOutSine"])(t)


def fly(a_pos, a_tgt, b_pos, b_tgt, t: float, mode: str = "spherical"):
    """Camera at fraction t between two views. Spherical keeps the orbit radius
    smooth around the moving target, like iJewel's default interpolation."""
    a_pos, a_tgt, b_pos, b_tgt = (np.asarray(x, float) for x in (a_pos, a_tgt, b_pos, b_tgt))
    tgt = a_tgt + (b_tgt - a_tgt) * t
    if mode != "spherical":
        return a_pos + (b_pos - a_pos) * t, tgt
    va, vb = a_pos - a_tgt, b_pos - b_tgt
    ra, rb = np.linalg.norm(va), np.linalg.norm(vb)
    if ra < 1e-12 or rb < 1e-12:
        return a_pos + (b_pos - a_pos) * t, tgt
    ua, ub = va / ra, vb / rb
    dot = float(np.clip(np.dot(ua, ub), -1, 1))
    om = math.acos(dot)
    if om < 1e-6:
        u = ua
    else:
        u = (math.sin((1 - t) * om) * ua + math.sin(t * om) * ub) / math.sin(om)
    return tgt + u * (ra + (rb - ra) * t), tgt


def material_for_part(glb_material: str, variations: list[dict]) -> dict | None:
    """The configurator variation that applies to a GLB material name.

    iJewel matches each variation title against material names on the model
    (as a regex when ``regex`` is true); an exact match wins.
    """
    exact = next((v for v in variations if v.get("title") == glb_material), None)
    if exact:
        return exact
    for v in variations:
        if v.get("regex"):
            try:
                if re.fullmatch(v.get("title", ""), glb_material):
                    return v
            except re.error:
                pass
    return None


def int_to_rgb(n: int) -> tuple[float, float, float]:
    n = int(n) & 0xFFFFFF
    return ((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255

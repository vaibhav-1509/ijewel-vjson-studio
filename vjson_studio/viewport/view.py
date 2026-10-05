"""The 3D viewport: GLB model, orbit camera, saved-view glyphs, framing overlay.

Coordinates are iJewel's (three.js, Y up). The model can be moved and scaled
for display only (``DisplayFit``); camera views are always read and written in
the vjson's own coordinates.
"""
from __future__ import annotations

import time

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from . import scene_math as sm
from .glb import GlbModel

VIEW_COLOR = "#3b82f6"
SELECTED_COLOR = "#f59e0b"


def _studio_cubemap(size: int = 64) -> vtk.vtkTexture:
    """A soft procedural studio environment so PBR metal and gems read well."""
    tex = vtk.vtkTexture()
    tex.CubeMapOn()
    tex.MipmapOn()
    tex.InterpolateOn()
    # +x -x +y -y +z -z ; bright top, darker floor, two side softboxes
    for i in range(6):
        y = np.linspace(1, 0, size)[:, None] * np.ones((1, size))
        if i == 2:
            base = np.full((size, size), 1.0)
        elif i == 3:
            base = np.full((size, size), 0.18)
        else:
            base = 0.25 + 0.65 * y
            if i in (0, 1):
                x = np.linspace(-1, 1, size)[None, :]
                base = base + 0.6 * np.exp(-((x * 2.2) ** 2) - (((y - 0.6) * 3) ** 2))
        img = (np.clip(base, 0, 1) * 255).astype(np.uint8)
        rgb = np.dstack([img, img, img]).reshape(-1, 3)
        data = pv.ImageData(dimensions=(size, size, 1))
        data.point_data["rgb"] = rgb
        data.point_data.active_scalars_name = "rgb"
        tex.SetInputDataObject(i, data)
    # return the raw vtkTexture: wrapping it in pv.Texture and setting the
    # cube_map/mipmap properties there crashes VTK 9.7 on the first paint
    return tex


class Viewport(QWidget):
    view_clicked = Signal(int)       # index of a camera glyph clicked
    camera_moved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plotter = QtInteractor(self)
        lay.addWidget(self.plotter.interactor)
        p = self.plotter
        p.set_background("#2b2d31", top="#45484f")
        p.enable_terrain_style(mouse_wheel_zooms=True)   # orbit around target, Y stays up
        p.camera.up = (0, 1, 0)
        p.enable_anti_aliasing("ssaa")
        try:
            p.set_environment_texture(_studio_cubemap(), is_srgb=True)
            self._pbr = True
        except Exception:
            self._pbr = False
        p.add_light(pv.Light(position=(3, 6, 4), light_type="scene light", intensity=0.7))

        self.model: GlbModel | None = None
        self.fit = sm.DisplayFit()
        self._model_actors: list = []
        self._helper_actors: dict = {}
        self._view_actors: list = []
        self._label_actor = None
        self.fov = 45.0
        self.aspect: float | None = None          # framing overlay aspect; None = off
        self.show_views = True
        self.show_ground = True
        self.show_gizmo = True
        self.show_axes = False
        self.show_bbox = False
        self._gizmo = None
        self._views: list[dict] = []
        self._selected = -1
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._anim_step)
        self._anim_job = None
        self._press = None

        iren = p.iren.interactor
        iren.AddObserver("LeftButtonPressEvent", self._on_press, 1.0)
        iren.AddObserver("LeftButtonReleaseEvent", self._on_release, 1.0)
        iren.AddObserver("EndInteractionEvent", lambda *_: self.camera_moved.emit())
        self._make_frame_actor()
        p.render_window.AddObserver("WindowResizeEvent", lambda *_: self._update_frame())
        self._update_frame()
        self._set_gizmo(self.show_gizmo)
        self._rebuild_helpers()                 # ground grid is visible before any model loads

    # ---------- model ----------

    def set_model(self, model: GlbModel | None, colours=None):
        """``colours`` maps a GLB material name to (rgb, metallic, roughness, is_gem)."""
        for a in self._model_actors:
            self.plotter.remove_actor(a, render=False)
        self._model_actors = []
        self.model = model
        if model:
            colours = colours or {}
            for part in model.parts:
                faces = np.hstack([np.full((len(part.faces), 1), 3), part.faces]).ravel()
                mesh = pv.PolyData(part.points, faces)
                mesh = mesh.compute_normals(auto_orient_normals=False, split_vertices=True, feature_angle=40)
                rgb, metal, rough, gem = colours.get(part.material, (part.base_color, part.metallic, part.roughness, False))
                kw = dict(color=rgb, smooth_shading=True, render=False)
                if self._pbr:
                    kw.update(pbr=True, metallic=0.0 if gem else metal, roughness=0.04 if gem else rough)
                else:
                    kw.update(specular=0.8, specular_power=40)
                if gem:
                    kw.update(opacity=0.85)
                a = self.plotter.add_mesh(mesh, **kw)
                a._part = part
                self._model_actors.append(a)
        self.apply_fit()
        self._rebuild_helpers()

    def update_colours(self, colours):
        """Re-apply vjson material looks without rebuilding the meshes."""
        for a in self._model_actors:
            part = a._part
            rgb, metal, rough, gem = colours.get(part.material, (part.base_color, part.metallic, part.roughness, False))
            prop = a.GetProperty()
            prop.SetColor(*rgb)
            if self._pbr:
                prop.SetMetallic(0.0 if gem else metal)
                prop.SetRoughness(0.04 if gem else rough)
            prop.SetOpacity(0.85 if gem else 1.0)
        self.plotter.render()

    def apply_fit(self):
        if not self.model:
            return
        lo, hi = self.model.bounds()
        m = self.fit.matrix(lo, hi)
        for a in self._model_actors:
            a.user_matrix = m
        self._rebuild_helpers()
        self.plotter.render()

    def model_bounds_display(self):
        """Model bounds after the display fit, in vjson coordinates."""
        if not self.model:
            return None
        lo, hi = self.model.bounds()
        m = self.fit.matrix(lo, hi)
        corners = np.array([[x, y, z, 1] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        w = corners @ m.T
        return w[:, :3].min(axis=0), w[:, :3].max(axis=0)

    # ---------- helpers: grid / axes / bbox ----------

    def _rebuild_helpers(self):
        for a in self._helper_actors.values():
            self.plotter.remove_actor(a, render=False)
        self._helper_actors = {}
        b = self.model_bounds_display()
        size = 4.0
        if b is not None:
            size = max(float(np.max(b[1] - b[0])) * 1.5, 1.0)
        if self.show_ground:
            self._add_ground(b)
        if self.show_axes:
            for d, c in (((1, 0, 0), "#ef4444"), ((0, 1, 0), "#22c55e"), ((0, 0, 1), "#3b82f6")):
                ln = pv.Line((0, 0, 0), tuple(x * size / 2 for x in d))
                self._helper_actors[f"axis{c}"] = self.plotter.add_mesh(ln, color=c, line_width=2, render=False, pickable=False)
        if self.show_bbox and b is not None:
            box = pv.Box(bounds=(b[0][0], b[1][0], b[0][1], b[1][1], b[0][2], b[1][2]))
            self._helper_actors["bbox"] = self.plotter.add_mesh(box, style="wireframe", color="#eab308",
                                                                render=False, pickable=False)
        self.plotter.render()

    def _add_ground(self, b):
        """Ground plane + grid at the model's base, centred on the world origin."""
        if b is not None:
            y = float(b[0][1])
            reach = float(max(abs(b[0][0]), abs(b[1][0]), abs(b[0][2]), abs(b[1][2])))
            extent = max(reach * 3.0, 1.0)
        else:
            y, extent = 0.0, 4.0
        g = sm.ground_grid(extent, y)
        half = g["half"]
        plane = pv.Plane(center=(0, y - half * 1e-4, 0), direction=(0, 1, 0), i_size=half * 2, j_size=half * 2)
        self._helper_actors["ground"] = self.plotter.add_mesh(
            plane, color="#1e1f22", opacity=0.45, lighting=False, render=False, pickable=False)
        style = {"minor": ("#5b5f66", 1, 0.35), "major": ("#7b8089", 1, 0.7),
                 "x_axis": ("#e5484d", 2, 0.95), "z_axis": ("#3b82f6", 2, 0.95)}
        for k, (color, width, opacity) in style.items():
            pts, cells = g[k]
            if len(pts):
                self._helper_actors[f"grid_{k}"] = self.plotter.add_mesh(
                    pv.PolyData(pts, lines=cells), color=color, line_width=width, opacity=opacity,
                    lighting=False, render=False, pickable=False)

    def _set_gizmo(self, on: bool):
        if on:
            if self._gizmo is None:
                # corner axis triad like a DCC app: follows the camera's orientation, never the picture
                self._gizmo = self.plotter.add_axes(interactive=False, line_width=3, viewport=(0, 0, 0.22, 0.22),
                                                    x_color="#e5484d", y_color="#22c55e", z_color="#3b82f6")
            else:
                self.plotter.show_axes()
        elif self._gizmo is not None:
            self.plotter.hide_axes()
        self.plotter.render()

    def set_toggle(self, name: str, on: bool):
        setattr(self, name, on)
        if name == "show_views":
            self.set_views(self._views, self._selected)
        elif name == "show_gizmo":
            self._set_gizmo(on)
        else:
            self._rebuild_helpers()

    # ---------- camera ----------

    def set_fov(self, fov: float):
        self.fov = float(fov)
        self._apply_fov()

    def _apply_fov(self):
        w, h = self.plotter.window_size
        fov = self.fov
        if self.aspect:
            fov, _ = sm.framing(w, h, self.aspect, self.fov)
        self.plotter.camera.view_angle = fov

    def camera(self) -> tuple[tuple, tuple]:
        c = self.plotter.camera
        return tuple(float(x) for x in c.position), tuple(float(x) for x in c.focal_point)

    def set_camera(self, pos, tgt, render=True):
        c = self.plotter.camera
        c.position = tuple(pos)
        c.focal_point = tuple(tgt)
        c.up = (0, 1, 0)
        self.plotter.reset_camera_clipping_range()
        if render:
            self.plotter.render()

    def fly_to(self, pos, tgt, duration_ms: float = 600, ease: str = "easeInOutSine", mode="spherical", done=None):
        a_pos, a_tgt = self.camera()
        self._anim_job = {"legs": [(a_pos, a_tgt, tuple(pos), tuple(tgt), max(duration_ms, 1), ease, mode, 0)],
                          "done": done}
        self._start_anim()

    def play(self, views: list[dict], duration_ms: float, ease: str, pause_ms: float, mode: str, done=None):
        legs = []
        prev = self.camera()
        for v in views:
            p = tuple(v["position"][k] for k in "xyz")
            t = tuple(v["target"][k] for k in "xyz")
            legs.append((prev[0], prev[1], p, t, max(duration_ms, 1), ease, mode, pause_ms))
            prev = (p, t)
        self._anim_job = {"legs": legs, "done": done}
        self._start_anim()

    def stop(self):
        self._anim.stop()
        self._anim_job = None

    @property
    def animating(self) -> bool:
        return self._anim.isActive()

    def _start_anim(self):
        self._anim_job["leg"] = 0
        self._anim_job["t0"] = time.perf_counter()
        self._anim.start(16)

    def _anim_step(self):
        job = self._anim_job
        if not job:
            self._anim.stop()
            return
        a_pos, a_tgt, b_pos, b_tgt, dur, ease, mode, pause = job["legs"][job["leg"]]
        elapsed = (time.perf_counter() - job["t0"]) * 1000
        t = min(elapsed / dur, 1.0)
        pos, tgt = sm.fly(a_pos, a_tgt, b_pos, b_tgt, sm.ease(ease, t), mode)
        self.set_camera(pos, tgt)
        if elapsed >= dur + pause:
            job["leg"] += 1
            job["t0"] = time.perf_counter()
            if job["leg"] >= len(job["legs"]):
                self._anim.stop()
                self._anim_job = None
                self.camera_moved.emit()
                if job["done"]:
                    job["done"]()

    # ---------- saved views as glyphs ----------

    def set_views(self, views: list[dict], selected: int = -1):
        self._views, self._selected = views, selected
        for a in self._view_actors:
            self.plotter.remove_actor(a, render=False)
        self._view_actors = []
        if self._label_actor is not None:
            self.plotter.remove_actor(self._label_actor, render=False)
            self._label_actor = None
        if self.show_views and views:
            b = self.model_bounds_display()
            ref = float(np.linalg.norm(b[1] - b[0])) if b is not None else 4.0
            aspect = self.aspect or 1.5
            label_pts, labels = [], []
            for i, v in enumerate(views):
                pos = [v["position"][k] for k in "xyz"]
                tgt = [v["target"][k] for k in "xyz"]
                depth = min(ref * 0.18, max(np.linalg.norm(np.subtract(tgt, pos)) * 0.25, 0.05))
                pts, lines = sm.frustum(pos, tgt, self.fov, aspect, depth)
                poly = pv.PolyData(pts, lines=lines)
                sel = i == selected
                a = self.plotter.add_mesh(poly, color=SELECTED_COLOR if sel else VIEW_COLOR,
                                          line_width=4 if sel else 2, render=False, pickable=True)
                a._view_index = i
                self._view_actors.append(a)
                label_pts.append(pts[0])
                labels.append(v.get("name") or f"view {i + 1}")
            self._label_actor = self.plotter.add_point_labels(
                np.array(label_pts), labels, font_size=12, text_color="white", point_size=6,
                point_color=VIEW_COLOR, shape_opacity=0.35, render=False, pickable=False, always_visible=False)
        self.plotter.render()

    # ---------- picking ----------

    def _on_press(self, obj, _evt):
        self._press = obj.GetEventPosition()

    def _on_release(self, obj, _evt):
        if self._press is None:
            return
        x, y = obj.GetEventPosition()
        px, py = self._press
        self._press = None
        if abs(x - px) + abs(y - py) > 3:
            return
        picker = vtk.vtkPropPicker()
        picker.Pick(x, y, 0, self.plotter.renderer)
        actor = picker.GetActor()
        for a in self._view_actors:
            if a is actor or (actor is not None and a.GetAddressAsString("") == actor.GetAddressAsString("")):
                self.view_clicked.emit(a._view_index)
                return

    # ---------- framing overlay ----------

    def set_aspect(self, aspect: float | None):
        self.aspect = aspect
        self._update_frame()
        self.set_views(self._views, self._selected)

    def _make_frame_actor(self):
        self._frame_pts = vtk.vtkPoints()
        for _ in range(4):
            self._frame_pts.InsertNextPoint(0, 0, 0)
        cells = vtk.vtkCellArray()
        cells.InsertNextCell(5)
        for i in (0, 1, 2, 3, 0):
            cells.InsertCellPoint(i)
        poly = vtk.vtkPolyData()
        poly.SetPoints(self._frame_pts)
        poly.SetLines(cells)
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        actor = vtk.vtkActor2D()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(1.0, 0.8, 0.2)
        actor.GetProperty().SetLineWidth(2)
        actor.VisibilityOff()
        self.plotter.renderer.AddViewProp(actor)
        self._frame_actor = actor

    def _update_frame(self):
        """Re-place the aspect frame and the fov for the current window size."""
        w, h = self.plotter.window_size
        self._apply_fov()
        if not self.aspect:
            self._frame_actor.VisibilityOff()
            return
        _, (x0, y0, x1, y1) = sm.framing(w, h, self.aspect, self.fov)
        for i, (px, py) in enumerate(((x0 + 1, y0 + 1), (x1 - 1, y0 + 1), (x1 - 1, y1 - 1), (x0 + 1, y1 - 1))):
            self._frame_pts.SetPoint(i, px, py, 0)
        self._frame_pts.Modified()
        self._frame_actor.VisibilityOn()

    def screenshot(self, path: str):
        self.plotter.screenshot(path)

    def close(self):
        self.stop()
        self.plotter.close()
        super().close()

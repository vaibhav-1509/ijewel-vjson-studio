"""Cameras: default camera, the camera-views table, viewport capture, playback."""
from __future__ import annotations

import copy
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QInputDialog, QLabel,
                               QPlainTextEdit, QSplitter, QVBoxLayout)

from ...model import cameras as cam
from ..widgets import Col, DataTable, Form, button, toolbar
from .base import Section


def _set_axis(which, axis):
    def fn(d, i, v):
        view = cam.views(d)[i]
        view[which][axis] = v
        cam.reorient(view)
    return fn


class CamerasSection(Section):
    title = "Cameras"
    key = "cameras"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.follow = True

    def count(self):
        return len(cam.views(self.ctx.data)) if self.ctx.doc else None

    # ---------- layout ----------

    def build(self, lay):
        d = self.ctx.data
        vp = self.ctx.viewport

        cols = [
            Col("Name", lambda v: v.get("name"), lambda d, i, s: cam.views(d)[i].__setitem__("name", s), width=110),
            *[Col(f"Pos {a.upper()}", lambda v, a=a: v["position"][a], _set_axis("position", a), "num", 92) for a in "xyz"],
            *[Col(f"Target {a.upper()}", lambda v, a=a: v["target"][a], _set_axis("target", a), "num", 92) for a in "xyz"],
            Col("Duration", lambda v: v.get("duration"), lambda d, i, n: cam.views(d)[i].__setitem__("duration", n), "num", 70),
            Col("Orientation (auto)", lambda v: ("q " + " ".join(f"{v['quaternion'][k]:.3f}" for k in "xyzw")
                                                 + ("  custom" if cam.has_custom_orientation(v) else ""))
                if v.get("quaternion") else "-", kind="ro", width=230),
        ]
        self.table = DataTable(self.ctx, cols)
        self.table.load(list(enumerate(cam.views(d))))
        self.table.row_activated.connect(self._row_activated)
        if 0 <= self.ctx.selected_view < self.table.rowCount():
            self.table.blockSignals(True)
            self.table.select_key(self.ctx.selected_view)
            self.table.blockSignals(False)

        follow = QCheckBox("Follow")
        follow.setChecked(self.follow)
        follow.setToolTip("Selecting or editing a view moves the viewport camera to it")
        follow.toggled.connect(lambda b: setattr(self, "follow", b))
        tools1 = toolbar(
            button("+ Add from viewport", self.add_from_viewport, "Capture the viewport camera as a new view (Ctrl+Shift+A)"),
            button("+ Add with name...", self.add_named),
            button("Update from viewport", self.update_from_viewport,
                   "Overwrite the selected view's position and target with the viewport camera (Ctrl+Shift+U)"),
            button("Go to", self.go_to, "Fly the viewport to the selected view (Ctrl+Shift+G)"),
            button("Set viewport = view", self.jump_to, "Put the viewport exactly at the selected view, no animation"),
            follow, "stretch")
        tools2 = toolbar(
            button("Duplicate", self.duplicate), button("Up", lambda: self.move(-1)), button("Down", lambda: self.move(1)),
            button("Delete", self.delete, danger=True), button("Bulk paste...", self.bulk_paste),
            button("Play all", self.play, "Fly through every view using the playback settings below"),
            button("Stop", lambda: vp and vp.view.stop()),
            "stretch", "Orientation (quaternion / up) is recomputed from position + target.")
        views_box = QGroupBox(f"Camera views - {len(cam.views(d))} saved")
        vl = QVBoxLayout(views_box)
        vl.addWidget(tools1)
        vl.addWidget(tools2)
        vl.addWidget(self.table)

        # default camera - only fields the file already has, so opening a page never adds keys
        dc = lambda d: d["scene"]["defaultCamera"]
        f = Form(self.ctx, "Default camera - the camera the scene opens with")
        f.form.addRow(toolbar(button("Set default camera from viewport", self.default_from_viewport),
                              button("Viewport = default camera", lambda: vp and vp.go_default()), "stretch"))
        f.vec3(lambda d: dc(d)["position"], "Position")
        f.vec3(lambda d: dc(d)["target"], "Target")
        cam_d = dc(d)
        if "camOptions" in cam_d:
            co = lambda d: d["scene"]["defaultCamera"]["camOptions"]
            for k, label in (("fov", "Field of view (deg, vertical)"), ("focus", "Focus distance"), ("zoom", "Zoom")):
                if k in cam_d["camOptions"]:
                    f.num(co, k, label)
        if "autoNearFar" in (cam_d.get("userData") or {}):
            f.bool(lambda d: dc(d)["userData"], "autoNearFar", "Auto near / far")
        if "camControls" in cam_d:
            cc = lambda d: d["scene"]["defaultCamera"]["camControls"]
            have = cam_d["camControls"]
            for k, label, kind in (("minDistance", "Min distance", "num"), ("maxDistance", "Max distance", "num"),
                                   ("minPolarAngle", "Min polar angle (deg)", "deg"),
                                   ("maxPolarAngle", "Max polar angle (deg)", "deg"),
                                   ("autoRotate", "Auto-rotate", "bool"), ("autoRotateSpeed", "Auto-rotate speed", "num"),
                                   ("enableZoom", "Zoom enabled", "bool"), ("enablePan", "Pan enabled", "bool"),
                                   ("enableRotate", "Rotate enabled", "bool"), ("enableDamping", "Damping", "bool"),
                                   ("dampingFactor", "Damping factor", "num"), ("zoomSpeed", "Zoom speed", "num"),
                                   ("rotateSpeed", "Rotate speed", "num"), ("panSpeed", "Pan speed", "num")):
                if k in have:
                    getattr(f, kind)(cc, k, label)

        playback = None
        if cam.camera_views_plugin(d):
            pv = lambda d: cam.camera_views_plugin(d)
            playback = Form(self.ctx, "Camera-views playback settings")
            playback.num(pv, "animDuration", "Animation duration (ms)")
            playback.num(pv, "viewPauseTime", "Pause between views (ms)")
            playback.num(pv, "rotationOffset", "Rotation offset")
            playback.choice(pv, "animEase", "Ease", cam.EASES)
            playback.choice(pv, "interpolateMode", "Interpolate mode", ["spherical", "linear"])
            playback.choice(pv, "splineCurve", "Spline curve", ["centripetal", "chordal", "catmullrom"])
            playback.bool(pv, "viewLooping", "Loop views")
            playback.bool(pv, "seekOnScroll", "Seek on scroll")

        split = QSplitter(Qt.Vertical)
        split.addWidget(views_box)
        split.addWidget(self.scroll(f, playback))
        split.setSizes([420, 380])
        lay.addWidget(split)

    # ---------- helpers ----------

    def _vp(self):
        vp = self.ctx.viewport
        if vp is None:
            self.ctx.toast("Open the 3D viewport first (View > 3D viewport)")
        return vp

    def _selected(self) -> int | None:
        k = self.table.current_key() if hasattr(self, "table") else None
        if k is None:
            k = self.ctx.selected_view if self.ctx.selected_view >= 0 else None
        if k is None or k >= len(cam.views(self.ctx.data)):
            self.ctx.toast("Select a camera view first")
            return None
        return k

    def _row_activated(self, key):
        if key is None:
            return
        self.ctx.select_view(key)
        if self.follow and self.ctx.viewport:
            self.jump_to(fly=True)

    def view_selected_externally(self, index: int):
        if hasattr(self, "table") and self.table.current_key() != index:
            self.table.blockSignals(True)
            self.table.select_key(index)
            self.table.blockSignals(False)

    def value_edited(self):
        """A number in the table changed; follow it in the viewport."""
        i = self.ctx.selected_view
        if self.follow and self.ctx.viewport and 0 <= i < len(cam.views(self.ctx.data)):
            v = cam.views(self.ctx.data)[i]
            self.ctx.viewport.view.set_camera(cam.xyz(v["position"]), cam.xyz(v["target"]))

    # ---------- actions ----------

    def _capture(self):
        vp = self._vp()
        if not vp:
            return None
        return vp.view.camera()

    def add_from_viewport(self, name: str | None = None):
        cap = self._capture()
        if not cap:
            return
        pos, tgt = cap

        def fn(d):
            n = name or cam.next_view_name(d)
            cam.camera_views_plugin(d, create=True)["cameraViews"].append(cam.make_view(n, pos, tgt))
            return len(cam.views(d)) - 1, n
        res = self.ctx.mutate(fn)
        if res:
            self.ctx.select_view(res[0])
            self.ctx.toast(f"Added {res[1]} from the viewport")

    def add_named(self):
        if not self._capture():
            return
        name, ok = QInputDialog.getText(self, "Add view from viewport", "View name:",
                                        text=cam.next_view_name(self.ctx.data))
        if ok:
            self.add_from_viewport(name.strip() or None)

    def update_from_viewport(self):
        i = self._selected()
        cap = self._capture() if i is not None else None
        if not cap:
            return
        pos, tgt = cap

        def fn(d):
            v = cam.views(d)[i]
            v["position"] = cam.v3(*pos)
            v["target"] = cam.v3(*tgt)
            cam.reorient(v)
            return v.get("name")
        name = self.ctx.mutate(fn)
        if name is not None:
            self.ctx.toast(f"{name} updated from the viewport")

    def default_from_viewport(self):
        cap = self._capture()
        if not cap:
            return
        pos, tgt = cap

        def fn(d):
            dc = cam.default_camera(d)
            dc["position"] = cam.v3(*pos)
            dc["target"] = cam.v3(*tgt)
        self.ctx.mutate(fn, "Default camera set from the viewport")

    def jump_to(self, fly=False):
        i = self._selected()
        vp = self._vp() if i is not None else None
        if not vp:
            return
        v = cam.views(self.ctx.data)[i]
        if fly:
            vp.view.fly_to(cam.xyz(v["position"]), cam.xyz(v["target"]), 450)
        else:
            vp.view.stop()
            vp.view.set_camera(cam.xyz(v["position"]), cam.xyz(v["target"]))

    def go_to(self):
        i = self._selected()
        vp = self._vp() if i is not None else None
        if not vp:
            return
        v = cam.views(self.ctx.data)[i]
        p = cam.camera_views_plugin(self.ctx.data) or {}
        vp.view.fly_to(cam.xyz(v["position"]), cam.xyz(v["target"]), p.get("animDuration", 1000),
                       p.get("animEase", "easeInOutSine"), p.get("interpolateMode", "spherical"))

    def play(self):
        vp = self._vp()
        views = cam.views(self.ctx.data)
        if not vp or not views:
            return
        p = cam.camera_views_plugin(self.ctx.data) or {}
        vp.view.play(copy.deepcopy(views), p.get("animDuration", 1000), p.get("animEase", "easeInOutSine"),
                     p.get("viewPauseTime", 200), p.get("interpolateMode", "spherical"))

    def duplicate(self):
        i = self._selected()
        if i is None:
            return

        def fn(d):
            vs = cam.views(d)
            c = copy.deepcopy(vs[i])
            c["name"] = cam.next_view_name(d)
            vs.insert(i + 1, c)
        self.ctx.mutate(fn, "Duplicated")
        self.ctx.select_view(i + 1)

    def move(self, step):
        i = self._selected()
        if i is None:
            return
        j = i + step
        if not 0 <= j < len(cam.views(self.ctx.data)):
            return

        def fn(d):
            vs = cam.views(d)
            vs[i], vs[j] = vs[j], vs[i]
        self.ctx.mutate(fn)
        self.ctx.select_view(j)

    def delete(self):
        keys = set(self.table.selected_keys()) if hasattr(self, "table") else set()
        if not keys:
            self.ctx.toast("Select views to delete first")
            return

        def fn(d):
            p = cam.camera_views_plugin(d)
            p["cameraViews"] = [v for i, v in enumerate(p["cameraViews"]) if i not in keys]
        self.ctx.select_view(-1)
        self.ctx.mutate(fn, f"Deleted {len(keys)} view(s)")

    def bulk_paste(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Bulk add camera views")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("One view per line: name, posX, posY, posZ, targetX, targetY, targetZ, duration\n"
                             "Comma, semicolon or tab separated - paste straight from Excel. Duration is optional."))
        ta = QPlainTextEdit()
        ta.setPlaceholderText("#front, 0, 3, 10, 0, 0, 0, 1\n#side, 10, 2, 0, 0, 0, 0, 1")
        lay.addWidget(ta)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        good, bad = [], []
        for line in filter(None, (l.strip() for l in ta.toPlainText().splitlines())):
            parts = [p.strip() for p in re.split(r"[\t;,]", line)]
            try:
                nums = [float(x) for x in parts[1:7]]
                if len(nums) != 6:
                    raise ValueError
                dur = float(parts[7]) if len(parts) > 7 and parts[7] else 1
                good.append((parts[0], nums[:3], nums[3:], dur))
            except ValueError:
                bad.append(line)

        def fn(d):
            p = cam.camera_views_plugin(d, create=True)
            for name, pos, tgt, dur in good:
                p["cameraViews"].append(cam.make_view(name or cam.next_view_name(d), pos, tgt, dur))
        if good:
            self.ctx.mutate(fn)
        self.ctx.toast(f"Added {len(good)} view(s)" + (f", skipped {len(bad)} unreadable line(s)" if bad else ""), 5000)

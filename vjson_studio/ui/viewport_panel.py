"""The 3D dock: GLB loading, display-only fit, toggles, framing overlay."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from ..model import cameras as cam
from ..model import materials as mat
from ..viewport import scene_math as sm
from ..viewport.glb import load_glb
from ..viewport.view import Viewport
from .widgets import NumberEdit

ASPECTS = [("No frame", None), ("1:1", 1.0), ("4:3", 4 / 3), ("3:2", 1.5), ("16:9", 16 / 9), ("9:16", 9 / 16),
           ("4:5", 0.8), ("Custom...", "custom")]


class ViewportPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.settings = QSettings("vjson-studio-3d", "vjson-studio-3d")
        self.glb_path: Path | None = None

        top = QHBoxLayout()
        self.load_btn = QPushButton("Load GLB...")
        self.load_btn.clicked.connect(self.pick_glb)
        self.info = QLabel("No model loaded - Ctrl+G or drop a .glb")
        self.info.setStyleSheet("color:#888")
        top.addWidget(self.load_btn)
        top.addWidget(self.info, 1)

        fit = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("iJewel auto-fit (approx.)", "ijewel")
        self.mode.addItem("Raw GLB coordinates", "raw")
        self.mode.setToolTip("iJewel centres a model and scales it to about radius 2 on load. "
                             "Display only - never written into the vjson.")
        self.mode.currentIndexChanged.connect(self._fit_changed)
        self.off = [NumberEdit(0.0, width=60) for _ in range(3)]
        self.scale = NumberEdit(1.0, width=60)
        for e in (*self.off, self.scale):
            e.committed.connect(lambda _v: self._fit_changed())
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset_fit)
        fit.addWidget(QLabel("Model:"))
        fit.addWidget(self.mode)
        fit.addWidget(QLabel("offset"))
        for e in self.off:
            fit.addWidget(e)
        fit.addWidget(QLabel("scale"))
        fit.addWidget(self.scale)
        fit.addWidget(reset)
        fit.addStretch()

        tog = QHBoxLayout()
        self.toggles = {}
        for name, label, on in (("show_views", "Cameras", True), ("show_ground", "Ground", True),
                                ("show_gizmo", "Axis gizmo", True), ("show_axes", "World axes", False),
                                ("show_bbox", "Bounds", False)):
            c = QCheckBox(label)
            c.setChecked(on)
            c.toggled.connect(lambda b, n=name: self.view.set_toggle(n, b))
            self.toggles[name] = c
            tog.addWidget(c)
        tog.addSpacing(12)
        tog.addWidget(QLabel("Frame:"))
        self.aspect = QComboBox()
        for label, val in ASPECTS:
            self.aspect.addItem(label, val)
        self.aspect.currentIndexChanged.connect(self._aspect_changed)
        tog.addWidget(self.aspect)
        self.custom_aspect = NumberEdit(1.0, width=60)
        self.custom_aspect.setVisible(False)
        self.custom_aspect.committed.connect(lambda v: self.view.set_aspect(max(float(v), 0.05)))
        tog.addWidget(self.custom_aspect)
        tog.addStretch()

        self.view = Viewport(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addLayout(fit)
        lay.addLayout(tog)
        lay.addWidget(self.view, 1)
        self.view.view_clicked.connect(self.ctx.select_view)
        self.ctx.view_selected.connect(lambda i: self.refresh_views())

    # ---------- GLB ----------

    def pick_glb(self):
        start = str(self.glb_path.parent) if self.glb_path else self.settings.value("last_glb_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, "Load GLB", start, "glTF binary (*.glb);;All files (*)")
        if path:
            self.load(path)

    def load(self, path: str):
        try:
            model = load_glb(path)
        except Exception as e:  # a broken file should explain itself, not crash the editor
            QMessageBox.warning(self, "Could not load GLB", f"{Path(path).name}\n\n{e}")
            return
        self.glb_path = Path(path)
        self.settings.setValue("last_glb_dir", str(self.glb_path.parent))
        self._restore_fit()
        self.view.set_model(model, self._colours())
        lo, hi = model.bounds()
        size = hi - lo
        warn = f"  |  {'; '.join(model.warnings)}" if model.warnings else ""
        self.info.setText(f"{self.glb_path.name}  |  {len(model.parts)} meshes, {model.triangles:,} triangles, "
                          f"size {size[0]:.3g} x {size[1]:.3g} x {size[2]:.3g}{warn}")
        self.info.setToolTip(str(self.glb_path))
        self.refresh_views()
        if self.ctx.doc:
            self.go_default()
        if not self.settings.value("coord_notice_shown", False, bool):
            self.settings.setValue("coord_notice_shown", True)
            QMessageBox.information(self, "About model position",
                                    "iJewel3D recentres and rescales a model when it loads it, so a raw GLB can sit "
                                    "somewhere other than where the saved camera views expect.\n\n"
                                    "The viewport applies the same kind of fit by default (centre + radius 2). If the "
                                    "camera frustums miss the model, nudge the model offset/scale at the top of this "
                                    "panel. That fit is display-only, remembered per GLB, and never written into the "
                                    "vjson.")
        self.ctx.toast(f"Loaded {self.glb_path.name}")

    def _colours(self):
        """GLB material name -> look, from the vjson material the configurator maps it to."""
        if not (self.ctx.doc and self.view.model):
            return {}
        d = self.ctx.data
        vs = mat.variations(d)
        mats = mat.materials(d)
        out = {}
        for name in {p.material for p in self.view.model.parts}:
            v = sm.material_for_part(name, vs)
            if not v or not v.get("materials"):
                continue
            idx = v.get("selectedIndex") or 0
            ref = v["materials"][idx] if isinstance(idx, int) and idx < len(v["materials"]) else v["materials"][0]
            m = mats.get(ref.get("uuid"))
            if not m or not isinstance(m.get("color"), int):
                continue
            gem = mat.is_diamond(m)
            out[name] = (sm.int_to_rgb(m["color"]), float(m.get("metalness", 1) or 0),
                         float(m.get("roughness", 0.2) or 0.05), gem)
        return out

    def recolour(self):
        if self.view.model:
            self.view.update_colours(self._colours())

    # ---------- display fit ----------

    def _fit_key(self):
        return "fit/" + str(self.glb_path).replace("\\", "/").lower() if self.glb_path else None

    def _restore_fit(self):
        raw = self.settings.value(self._fit_key(), "") if self._fit_key() else ""
        try:
            f = json.loads(raw) if raw else {}
        except ValueError:
            f = {}
        self.view.fit = sm.DisplayFit(f.get("mode", "ijewel"), tuple(f.get("offset", (0, 0, 0))), f.get("scale", 1.0))
        self._show_fit()

    def _show_fit(self):
        for w in (self.mode, *self.off, self.scale):
            w.blockSignals(True)
        self.mode.setCurrentIndex(max(self.mode.findData(self.view.fit.mode), 0))
        for e, v in zip(self.off, self.view.fit.offset):
            e.setText(str(v))
            e._like = v
        self.scale.setText(str(self.view.fit.scale))
        self.scale._like = self.view.fit.scale
        for w in (self.mode, *self.off, self.scale):
            w.blockSignals(False)

    def _fit_changed(self):
        try:
            off = tuple(float(e.text()) for e in self.off)
            scale = float(self.scale.text())
        except ValueError:
            return
        if scale <= 0:
            scale = 1.0
        self.view.fit = sm.DisplayFit(self.mode.currentData(), off, scale)
        if self._fit_key():
            self.settings.setValue(self._fit_key(), json.dumps({"mode": self.view.fit.mode, "offset": list(off),
                                                                "scale": scale}))
        self.view.apply_fit()
        self.refresh_views()

    def _reset_fit(self):
        self.view.fit = sm.DisplayFit()
        self._show_fit()
        self._fit_changed()

    def _aspect_changed(self):
        val = self.aspect.currentData()
        self.custom_aspect.setVisible(val == "custom")
        if val == "custom":
            val = max(float(self.custom_aspect.text() or 1), 0.05)
        self.view.set_aspect(val)

    # ---------- document ----------

    def doc_changed(self):
        if not self.ctx.doc:
            return
        self.view.set_fov(cam.default_fov(self.ctx.data))
        self.recolour()
        self.refresh_views()

    def refresh_views(self):
        views = cam.views(self.ctx.data) if self.ctx.doc else []
        self.view.set_views(views, self.ctx.selected_view)

    def go_default(self):
        dc = cam.default_camera(self.ctx.data)
        self.view.set_camera(cam.xyz(dc["position"]), cam.xyz(dc["target"]))

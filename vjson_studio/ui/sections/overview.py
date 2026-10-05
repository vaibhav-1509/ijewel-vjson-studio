from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ...model import cameras as cam
from ...model import materials as mat
from ..widgets import Form
from .base import Section


class OverviewSection(Section):
    title = "Overview"
    key = "overview"

    def __init__(self, ctx, go, parent=None):
        super().__init__(ctx, parent)
        self.go = go

    def build(self, lay):
        d = self.ctx.data
        doc = self.ctx.doc
        f = Form(self.ctx, "File")
        f.info("Name", doc.path.name if doc.path else "(unsaved)")
        f.info("Folder", str(doc.path.parent) if doc.path else "")
        f.info("Viewer version", str(d.get("version")))
        f.info("Type", str(d.get("type")))
        f.info("Generator", str((d.get("metadata") or {}).get("generator", "-")))
        f.info("Number style on save", "JavaScript (as iJewel writes)" if doc.style == "js" else "Python (as the file was written)")

        stats = QGroupBox("Contents")
        sl = QHBoxLayout(stats)
        for n, label, target in ((len(mat.materials(d)), "materials", "materials"),
                                 (len(mat.variations(d)), "configurator entries", "configurator"),
                                 (len(cam.views(d)), "camera views", "cameras"),
                                 (len(d["resources"].get("textures") or {}), "textures", "textures"),
                                 (len(d["plugins"]), "plugins / effects", "plugins")):
            b = QPushButton(f"{n}\n{label}")
            b.setMinimumHeight(56)
            b.clicked.connect(lambda _=False, t=target: self.go(t))
            sl.addWidget(b)

        plan = mat.standard_plan(d)
        qa = QGroupBox("Quick actions")
        ql = QVBoxLayout(qa)
        row = QHBoxLayout()
        std = QPushButton("Add standard material set...")
        std.clicked.connect(self.standard)
        val = QPushButton("Run validation")
        val.clicked.connect(lambda: self.go("validate"))
        row.addWidget(std)
        row.addWidget(val)
        row.addStretch()
        ql.addLayout(row)
        ql.addWidget(QLabel(f"Standard set = {plan['total']} names (4 metals + mainstone diamonds). "
                            f"In this file: {len(plan['add'])} missing, {len(plan['skip'])} already present."))

        how = QLabel(
            "<b>How this works</b><br>"
            "Tables edit like a spreadsheet: double-click or start typing in a cell, Enter commits and moves down.<br>"
            "UUIDs, camera orientation (quaternion / up) and configurator registration are filled in for you.<br>"
            "iJewel3D only shows a material that a Material Configurator entry points at - adding a material here "
            "registers it automatically.<br>"
            "Load any GLB in the 3D viewport (Ctrl+G) to place cameras; one vjson serves many models.<br>"
            "Nothing is written until you press <b>Save</b> (Ctrl+S). The first save keeps a <i>.bak</i> of the original.")
        how.setWordWrap(True)
        lay.addWidget(self.scroll(f, stats, qa, how))

    def standard(self):
        plan = mat.standard_plan(self.ctx.data)
        if not plan["add"]:
            self.ctx.toast("Every standard material is already in this file")
            return
        r = QMessageBox.question(self, "Add standard material set",
                                 f"Add {len(plan['add'])} materials ({len(plan['skip'])} already present are left "
                                 f"untouched)?\n\nDuplicates are never created - running this twice adds nothing.")
        if r == QMessageBox.Yes:
            self.ctx.mutate(mat.apply_standard, f"Added {len(plan['add'])} materials")

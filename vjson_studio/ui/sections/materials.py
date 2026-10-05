from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget)

from ...model import materials as mat
from ..widgets import Col, ColorEdit, DataTable, ParamEditor, button, toolbar
from .base import Section


def _m(d, u):
    return mat.materials(d)[u]


def _set(key):
    return lambda d, u, v: _m(d, u).__setitem__(key, v)


def _only(pred, key):
    return lambda m: m.get(key) if pred(m) else None


class MaterialsSection(Section):
    title = "Materials"
    key = "materials"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.type_filter = "all"
        self.text_filter = ""

    def count(self):
        return len(mat.materials(self.ctx.data)) if self.ctx.doc else None

    def build(self, lay):
        d = self.ctx.data
        std = lambda m: not mat.is_diamond(m)
        dia = mat.is_diamond

        def rename(d, u, s):
            if not s:
                raise ValueError("Name cannot be empty")
            if mat.rename_material(d, u, s):
                self.ctx.toast("Renamed - configurator title updated too")

        cols = [
            Col("Name", lambda m: m.get("name"), rename, width=230),
            Col("Type", mat.kind_of, kind="ro", width=90),
            Col("Colour", lambda m: m.get("color"), _set("color"), "color", 90),
            Col("Metalness", _only(std, "metalness"), lambda d, u, v: std(_m(d, u)) and _set("metalness")(d, u, v), "num", 80),
            Col("Roughness", _only(std, "roughness"), lambda d, u, v: std(_m(d, u)) and _set("roughness")(d, u, v), "num", 80),
            Col("Refractive idx", _only(dia, "refractiveIndex"),
                lambda d, u, v: dia(_m(d, u)) and _set("refractiveIndex")(d, u, v), "num", 90),
            Col("Env intensity", lambda m: m.get("envMapIntensity"), _set("envMapIntensity"), "num", 90),
            Col("Configurator entry", lambda m: self._usage_text(m), kind="ro", width=200),
            Col("UUID (auto)", lambda m: m.get("uuid"), kind="ro", width=270),
        ]
        self.table = DataTable(self.ctx, cols)
        self.table.row_activated.connect(self._show_detail)

        self.kind = QComboBox()
        for v, label in (("all", "All types"), ("metal", "Metal / PBR"), ("diamond", "Diamond"), ("unreg", "Not in configurator")):
            self.kind.addItem(label, v)
        self.kind.setCurrentIndex(self.kind.findData(self.type_filter))
        self.kind.currentIndexChanged.connect(lambda _i: (setattr(self, "type_filter", self.kind.currentData()), self.refresh()))
        flt = QLineEdit(self.text_filter)
        flt.setPlaceholderText("Filter name / uuid...")
        flt.textChanged.connect(lambda t: (setattr(self, "text_filter", t), self.table.filter(t)))
        self.count_label = QLabel()

        tools = toolbar(
            button("+ Add material", self.add), button("Bulk paste...", self.bulk),
            button("Standard set...", self.standard), button("Clone selected", self.clone),
            button("Delete selected", self.delete, danger=True),
            button("Register unlisted", lambda: self.ctx.mutate(
                lambda d: self.ctx.toast(f"Registered {mat.register_unlisted(d)} material(s)"))),
            flt, self.kind, self.count_label)

        self.detail = QWidget()
        QVBoxLayout(self.detail)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setSizes([900, 380])
        lay.addWidget(tools)
        lay.addWidget(split, 1)
        self._load()

    def _usage_text(self, m):
        u = mat.usage_of(self.ctx.data, m.get("uuid"))
        if not u:
            return "not registered"
        return u[0]["title"] if len(u) == 1 else f"{len(u)} entries"

    def _rows(self):
        d = self.ctx.data
        tf = self.type_filter
        out = []
        for u, m in mat.materials(d).items():
            if tf == "metal" and mat.is_diamond(m):
                continue
            if tf == "diamond" and not mat.is_diamond(m):
                continue
            if tf == "unreg" and mat.usage_of(d, u):
                continue
            out.append((u, m))
        return out

    def _load(self):
        rows = self._rows()
        self.table.load(rows)
        self.table.filter(self.text_filter)
        self.count_label.setText(f"{len(rows)} of {len(mat.materials(self.ctx.data))}")

    def _show_detail(self, u):
        lay = self.detail.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        m = mat.materials(self.ctx.data).get(u)
        if not m:
            lay.addWidget(QLabel("Select a row to edit every property of that material."))
            return
        uses = mat.usage_of(self.ctx.data, u)
        head = QLabel(f"<b>{m.get('name')}</b><br><span style='color:#888'>{u}</span><br>In configurator: "
                      + (", ".join(v["title"] for v in uses) if uses else "<span style='color:#d97706'>not registered</span>"))
        head.setWordWrap(True)
        head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(head)
        if not uses:
            lay.addWidget(button("Register in configurator", lambda: self.ctx.mutate(
                lambda d: mat.register_material(d, u), "Registered")))
        q = QLineEdit()
        q.setPlaceholderText("Filter parameters...")
        pe = ParamEditor(self.ctx, lambda d, u=u: mat.materials(d)[u], skip=("name", "userData.uuid"))
        q.textChanged.connect(pe.reload)
        lay.addWidget(q)
        lay.addWidget(pe)

    # ---------- actions ----------

    def add(self):
        d = self.ctx.data
        dlg = QDialog(self)
        dlg.setWindowTitle("Add material")
        form = QFormLayout(dlg)
        name = QLineEdit()
        name.setPlaceholderText("e.g. mainstone-cushion-red or metal-yellow")
        kind = QComboBox()
        kind.addItem("Diamond / gemstone", "diamond")
        kind.addItem("Metal (PBR)", "metal")
        colour = ColorEdit(0xFFFFFF)
        presets = QWidget()
        pl = QVBoxLayout(presets)
        pl.setContentsMargins(0, 0, 0, 0)

        def fill_presets():
            while pl.count():
                pl.takeAt(0).widget().deleteLater()
            row = QWidget()
            from PySide6.QtWidgets import QHBoxLayout
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            for label, c in mat.PRESETS[kind.currentData()]:
                b = QPushButton(label)
                b.setStyleSheet(f"background:{mat.to_hex(c)}; color:{'#000' if c > 0x888888 else '#fff'}")
                b.clicked.connect(lambda _=False, c=c: (colour._set(c)))
                rl.addWidget(b)
            pl.addWidget(row)
        kind.currentIndexChanged.connect(lambda _i: fill_presets())
        fill_presets()
        reg = QCheckBox("Register in Material Configurator (needed for iJewel3D to see it)")
        reg.setChecked(True)
        title = QLineEdit()
        title.setPlaceholderText("(same as name)")
        warn = QLabel()
        warn.setStyleSheet("color:#d97706")
        form.addRow("Material name", name)
        form.addRow("Kind", kind)
        form.addRow("Colour", colour)
        form.addRow("", presets)
        form.addRow(reg)
        form.addRow("Configurator title", title)
        form.addRow(warn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(bb)

        def check():
            t = (title.text().strip() or name.text().strip()) if reg.isChecked() else ""
            taken = bool(t) and mat.title_taken(d, t)
            warn.setText(f"A configurator entry called '{t}' already exists - pick another name." if taken else "")
            return taken
        name.textChanged.connect(check)
        title.textChanged.connect(check)
        reg.toggled.connect(check)

        def ok():
            if not name.text().strip():
                warn.setText("Give the material a name")
                return
            if check():
                return
            dlg.accept()
        bb.accepted.connect(ok)
        bb.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.Accepted:
            return
        n = name.text().strip()
        u = self.ctx.mutate(lambda d: mat.create_material(d, n, kind.currentData(), colour.value, reg.isChecked(),
                                                           title.text().strip() or n), f"Added '{n}'")
        if u:
            self.table.select_key(u)

    def bulk(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Bulk add materials")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("One per line: name, colour (#RRGGBB), type (metal or diamond - optional, guessed from the "
                             "name).\nPaste straight from Excel. Names that already have a configurator entry are skipped."))
        ta = QPlainTextEdit()
        ta.setPlaceholderText("mainstone-cushion-red, #FAC9C9, diamond\nmetal-bronze, #CD7F32, metal")
        lay.addWidget(ta)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        lines = [l.strip() for l in ta.toPlainText().splitlines() if l.strip()]
        result = {"ok": 0, "skip": 0, "bad": 0}

        def fn(d):
            for line in lines:
                p = [x.strip() for x in re.split(r"[\t;,]", line)]
                c = mat.from_hex(p[1] if len(p) > 1 and p[1] else "#ffffff")
                if not p[0] or c is None:
                    result["bad"] += 1
                    continue
                if mat.title_taken(d, p[0]):
                    result["skip"] += 1
                    continue
                t = (p[2] if len(p) > 2 else "").lower()
                kind = "metal" if t.startswith("metal") else "diamond" if t.startswith(("diamond", "gem")) else \
                    ("metal" if p[0].lower().startswith("metal") else "diamond")
                mat.create_material(d, p[0], kind, c, register=True)
                result["ok"] += 1
        self.ctx.mutate(fn)
        self.ctx.toast(f"Added {result['ok']}" + (f", skipped {result['skip']} duplicate(s)" if result["skip"] else "")
                       + (f", {result['bad']} unreadable line(s)" if result["bad"] else ""), 5000)

    def standard(self):
        plan = mat.standard_plan(self.ctx.data)
        if not plan["add"]:
            self.ctx.toast("Every standard material is already in this file")
            return
        if QMessageBox.question(self, "Add standard material set",
                                f"Add {len(plan['add'])} materials? {len(plan['skip'])} already present are left untouched."
                                ) == QMessageBox.Yes:
            self.ctx.mutate(mat.apply_standard, f"Added {len(plan['add'])} materials")

    def clone(self):
        keys = self.table.selected_keys()
        if not keys:
            self.ctx.toast("Select rows to clone first")
            return
        self.ctx.mutate(lambda d: [mat.clone_material(d, k) for k in keys], f"Cloned {len(keys)}")

    def delete(self):
        keys = self.table.selected_keys()
        if not keys:
            self.ctx.toast("Select rows to delete first")
            return
        if QMessageBox.question(self, "Delete materials",
                                f"Delete {len(keys)} material(s) and the configurator entries that only point at them? "
                                f"You can undo.") == QMessageBox.Yes:
            self.ctx.mutate(lambda d: mat.delete_materials(d, keys), f"Deleted {len(keys)}")

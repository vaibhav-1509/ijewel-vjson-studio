from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QSplitter, QVBoxLayout, QWidget)

from ...model import materials as mat
from ..widgets import Col, DataTable, button, toolbar
from .base import Section


def _var(d, i):
    return mat.variations(d)[i]


class ConfiguratorSection(Section):
    title = "Configurator"
    key = "configurator"

    def count(self):
        return len(mat.variations(self.ctx.data)) if self.ctx.doc else None

    def build(self, lay):
        d = self.ctx.data

        def names(v):
            ms = mat.materials(self.ctx.data)
            return ", ".join(ms[x["uuid"]].get("name", "?") if x.get("uuid") in ms else "MISSING"
                             for x in v.get("materials") or [])

        def set_sel(d, i, n):
            _var(d, i)["selectedIndex"] = int(n)

        def set_title(d, i, s):
            if not s:
                raise ValueError("Title cannot be empty")
            mat.rename_variation(d, _var(d, i), s)

        cols = [
            Col("Title (matched against material names on the model)", lambda v: v.get("title"), set_title, width=330),
            Col("Regex", lambda v: v.get("regex"), lambda d, i, b: _var(d, i).__setitem__("regex", b), "bool", 60),
            Col("Selected idx", lambda v: v.get("selectedIndex"), set_sel, "int", 90),
            Col("# mats", lambda v: len(v.get("materials") or []), kind="ro", width=60),
            Col("Materials", names, kind="ro", width=320),
        ]
        self.table = DataTable(self.ctx, cols)
        self.table.load(list(enumerate(mat.variations(d))))
        self.table.row_activated.connect(self._detail)
        flt = QLineEdit()
        flt.setPlaceholderText("Filter title / material...")
        flt.textChanged.connect(self.table.filter)
        tools = toolbar(button("+ Add entry", self.add), button("Delete selected", self.delete, danger=True), flt,
                        "An entry's title is matched (as regex) against material names on the model.")
        self.detail = QWidget()
        QVBoxLayout(self.detail)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setSizes([850, 380])
        lay.addWidget(tools)
        lay.addWidget(split, 1)

    def _detail(self, i):
        lay = self.detail.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        vs = mat.variations(self.ctx.data)
        if i is None or i >= len(vs):
            lay.addWidget(QLabel("Select an entry to manage its materials."))
            return
        v = vs[i]
        ms = mat.materials(self.ctx.data)
        lay.addWidget(QLabel(f"<b>{v.get('title')}</b><br><span style='color:#888'>Materials the viewer can apply for "
                             f"this entry. The first is used unless 'selected index' says otherwise.</span>"))
        for j, x in enumerate(v.get("materials") or []):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            star = " *" if v.get("selectedIndex") == j else ""
            m = ms.get(x.get("uuid"))
            rl.addWidget(QLabel(f"{j}{star}  " + (m.get("name", "?") if m else f"MISSING {x.get('uuid')}")), 1)

            def remove(_=False, j=j):
                self.ctx.mutate(lambda d: _var(d, i)["materials"].pop(j))
            rl.addWidget(button("Remove", remove, danger=True))
            lay.addWidget(row)
        opts = sorted(ms.values(), key=lambda m: (m.get("name") or "").lower())
        labels = [f"{m.get('name')}  ·  {m['uuid'][:8]}" for m in opts]
        add = QLineEdit()
        add.setPlaceholderText("type to search a material to add...")
        comp = QCompleter(labels)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        add.setCompleter(comp)

        def do_add():
            t = add.text().strip()
            mm = next((m for m, lab in zip(opts, labels) if lab == t), None) or next(
                (m for m in opts if m.get("name") == t), None)
            if not mm:
                self.ctx.toast("No material with that name")
                return

            def fn(d):
                var = _var(d, i)
                var.setdefault("materials", [])
                if not any(x.get("uuid") == mm["uuid"] for x in var["materials"]):
                    var["materials"].append({"uuid": mm["uuid"], "resource": "materials"})
            self.ctx.mutate(fn)
        add.returnPressed.connect(do_add)
        lay.addWidget(add)
        lay.addStretch()

    def add(self):
        d = self.ctx.data
        dlg = QDialog(self)
        dlg.setWindowTitle("Add configurator entry")
        form = QFormLayout(dlg)
        title = QLineEdit()
        title.setPlaceholderText("e.g. mainstone-round-blue")
        sel = QComboBox()
        sel.addItem("(no material yet)", None)
        for m in sorted(mat.materials(d).values(), key=lambda m: (m.get("name") or "").lower()):
            sel.addItem(f"{m.get('name')}  ·  {m['uuid'][:8]}", m["uuid"])
        form.addRow("Title", title)
        form.addRow("Material", sel)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() == QDialog.Accepted and title.text().strip():
            t = title.text().strip()
            self.ctx.mutate(lambda d: mat.add_variation(d, t, sel.currentData()), "Entry added")

    def delete(self):
        keys = set(self.table.selected_keys())
        if not keys:
            self.ctx.toast("Select rows to delete first")
            return
        self.ctx.mutate(lambda d: mat.delete_variations(d, [v for i, v in enumerate(mat.variations(d)) if i in keys]),
                        f"Deleted {len(keys)} entr{'ies' if len(keys) > 1 else 'y'} (materials kept)")

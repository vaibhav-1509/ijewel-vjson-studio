"""Textures & LUTs, Effects & Plugins, Validate, Raw JSON."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget)

from ...model.validate import ERR, WARN, validate
from ..widgets import Col, DataTable, ParamEditor, button, toolbar
from .base import Section


class TexturesSection(Section):
    title = "Textures & LUTs"
    key = "textures"

    def count(self):
        if not self.ctx.doc:
            return None
        r = self.ctx.data["resources"]
        return len(r.get("textures") or {}) + len(r.get("extras") or {})

    def _where(self, kind):
        return "textures" if kind == "Texture" else "extras"

    def build(self, lay):
        d = self.ctx.data
        res = d["resources"]

        def used_as(u):
            o = []
            if (d["scene"].get("environment") or {}).get("uuid") == u:
                o.append("scene environment")
            if (d["scene"].get("background") or {}).get("uuid") == u:
                o.append("scene background")
            dia = next((p for p in d["plugins"] if p.get("type") == "Diamond"), None)
            if dia and (dia.get("envMap") or {}).get("uuid") == u:
                o.append("gem env")
            return ", ".join(o) or "-"

        def set_src(d, key, s):
            if key[0] != "Texture":
                raise ValueError("Embedded LUT data is read-only")
            t = d["resources"]["textures"][key[1]]
            t["name"] = s
            if isinstance(t.get("userData"), dict) and "rootPath" in t["userData"]:
                t["userData"]["rootPath"] = s

        rows = [(("Texture", u), {**t, "_kind": "Texture"}) for u, t in (res.get("textures") or {}).items()]
        rows += [(("Extra / LUT", u), {**t, "_kind": "Extra / LUT"}) for u, t in (res.get("extras") or {}).items()]
        cols = [
            Col("Kind", lambda t: t["_kind"], kind="ro", width=90),
            Col("Source URL / file (editing swaps the environment)",
                lambda t: t.get("name") if t["_kind"] == "Texture" else ((t.get("url") or {}).get("path")
                                                                         or (t.get("userData") or {}).get("rootPath")
                                                                         or "(embedded)"),
                set_src, width=520),
            Col("Used as", lambda t: used_as(t.get("uuid")), kind="ro", width=150),
            Col("Mapping", lambda t: t.get("mapping"), kind="ro", width=70),
            Col("Colour space", lambda t: t.get("colorSpace"), kind="ro", width=100),
            Col("UUID", lambda t: t.get("uuid"), kind="ro", width=270),
        ]
        self.table = DataTable(self.ctx, cols)
        self.table.load(rows)
        self.table.row_activated.connect(self._detail)
        flt = QLineEdit()
        flt.setPlaceholderText("Filter...")
        flt.textChanged.connect(self.table.filter)
        self.detail = QWidget()
        QVBoxLayout(self.detail)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setSizes([900, 360])
        lay.addWidget(toolbar(flt, "Environments are referenced by URL (iJewel3D downloads them at load time). "
                                   "Embedded LUT data is shown read-only."))
        lay.addWidget(split, 1)

    def _detail(self, key):
        lay = self.detail.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not key:
            return
        where, u = self._where(key[0]), key[1]
        lay.addWidget(QLabel(f"<b>{key[0]} properties</b><br><span style='color:#888'>{u}</span>"))
        lay.addWidget(ParamEditor(self.ctx, lambda d: d["resources"][where][u], skip=("name", "userData.rootPath")))


class PluginsSection(Section):
    title = "Effects & Plugins"
    key = "plugins"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.current = None

    def count(self):
        return len(self.ctx.data["plugins"]) if self.ctx.doc else None

    def build(self, lay):
        d = self.ctx.data
        items = [(i, p) for i, p in enumerate(d["plugins"]) if p.get("type") and p.get("type") != "MaterialConfiguratorPlugin"]
        self.list = QListWidget()
        for i, p in items:
            on = p.get("enabled", (p.get("extension") or {}).get("enabled") if isinstance(p.get("extension"), dict) else None)
            it = QListWidgetItem(p["type"] + ("" if on is None else ("   [on]" if on else "   [off]")))
            it.setData(Qt.UserRole, i)
            self.list.addItem(it)
        flt = QLineEdit()
        flt.setPlaceholderText("Filter plugins...")
        flt.textChanged.connect(lambda t: [self.list.item(r).setHidden(t.lower() not in self.list.item(r).text().lower())
                                           for r in range(self.list.count())])
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(flt)
        ll.addWidget(self.list)
        self.right = QWidget()
        QVBoxLayout(self.right)
        self.list.currentItemChanged.connect(lambda it, _p: it and self._show(it.data(Qt.UserRole)))
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(self.right)
        split.setSizes([280, 900])
        lay.addWidget(split, 1)
        idx = next((r for r in range(self.list.count()) if self.list.item(r).data(Qt.UserRole) == self.current), 0)
        if self.list.count():
            self.list.setCurrentRow(idx)

    def _show(self, i):
        self.current = i
        lay = self.right.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        p = self.ctx.data["plugins"][i]
        q = QLineEdit()
        q.setPlaceholderText("Filter parameters...")
        pe = ParamEditor(self.ctx, lambda d, i=i: d["plugins"][i])
        q.textChanged.connect(pe.reload)
        lay.addWidget(QLabel(f"<b>{p.get('type')}</b> - every simple setting, edit in place"))
        lay.addWidget(q)
        lay.addWidget(pe)


class ValidateSection(Section):
    title = "Validate"
    key = "validate"

    def build(self, lay):
        issues = validate(self.ctx.data)
        box = QGroupBox(f"Validation - {len(issues)} finding(s)" if issues else "Validation - all clear")
        bl = QVBoxLayout(box)
        if not issues:
            bl.addWidget(QLabel("No problems found. Every configurator entry is unique, every link resolves, "
                                "every colour is valid."))
        colours = {ERR: "#dc2626", WARN: "#d97706"}
        for i in issues:
            row = QWidget()
            rl = QHBoxLayout(row)
            tag = QLabel({ERR: "Error", WARN: "Warning"}.get(i.sev, "Info"))
            tag.setStyleSheet(f"color:white; background:{colours.get(i.sev, '#6b7280')}; padding:2px 6px; border-radius:3px")
            tag.setFixedWidth(70)
            msg = QLabel(f"<b>{i.msg}</b><br><span style='color:#888'>{i.detail}</span>")
            msg.setWordWrap(True)
            rl.addWidget(tag)
            rl.addWidget(msg, 1)
            if i.fix:
                rl.addWidget(button(i.fix_label, lambda _=False, fix=i.fix: self.ctx.mutate(fix, "Fixed")))
            bl.addWidget(row)
        lay.addWidget(self.scroll(box))


class RawSection(Section):
    title = "Raw JSON"
    key = "raw"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.part = "scene"

    def build(self, lay):
        sel = QComboBox()
        parts = ["scene", "resources.materials", "resources.textures", "resources.extras", "plugins", "renderManager",
                 "metadata"]
        sel.addItems(parts)
        sel.setCurrentText(self.part)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Consolas", 9))

        def show():
            self.part = sel.currentText()
            o = self.ctx.data
            for k in self.part.split("."):
                o = (o or {}).get(k)

            def short(x):
                if isinstance(x, dict):
                    return {k: short(v) for k, v in x.items()}
                if isinstance(x, list):
                    return [short(v) for v in x]
                if isinstance(x, str) and len(x) > 200:
                    return x[:80] + f"...[{len(x)} chars]"
                return x
            txt.setPlainText(json.dumps(short(o), indent=2, ensure_ascii=False))
        sel.currentTextChanged.connect(lambda _t: show())
        copy = button("Copy", lambda: QApplication.clipboard().setText(txt.toPlainText()))
        lay.addWidget(toolbar(sel, copy, "Read-only. Long data strings are shortened here but untouched in the file."))
        lay.addWidget(txt)
        show()

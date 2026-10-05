"""Reusable editing widgets.

Every editor reads and writes through a *getter on the document*, never a
captured dict: undo swaps in a different dict, so a captured reference would
silently edit a copy nobody sees.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QWidget)

from ..model.materials import from_hex, to_hex

Getter = Callable[[dict], Any]


def fmt_num(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    return repr(float(v)) if abs(v) >= 1e-4 or v == 0 else f"{v:.12g}"


def parse_num(s: str, like=None):
    s = s.strip()
    if not s:
        raise ValueError("Enter a number")
    v = float(s)
    if not math.isfinite(v):
        raise ValueError("Enter a finite number")
    if isinstance(like, int) and not isinstance(like, bool) and v.is_integer() and "." not in s and "e" not in s.lower():
        return int(v)
    return v


def is_color_key(key: str, v) -> bool:
    return (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 0xFFFFFF
            and re.search(r"(^|[a-z])(color|bgcolor|emissive)$", key, re.I) is not None)


def is_vec(v) -> bool:
    return isinstance(v, dict) and any(v.get(k) is True for k in ("isVector3", "isVector2", "isEuler", "isQuaternion"))


def is_rgb(v) -> bool:
    return isinstance(v, dict) and v.get("isColor") is True


# ---------- single fields ----------

class NumberEdit(QLineEdit):
    """A number field that keeps full double precision (spin boxes round)."""
    committed = Signal(object)

    def __init__(self, value=None, parent=None, width=110):
        super().__init__(parent)
        self._like = value
        self.setText(fmt_num(value))
        self.setCursorPosition(0)          # show the sign and leading digits, not the tail
        self.setFixedWidth(width)
        self.editingFinished.connect(self._done)

    def _done(self):
        old = fmt_num(self._like)
        if self.text().strip() == old:
            return
        try:
            v = parse_num(self.text(), self._like)
        except ValueError:
            self.setText(old)
            return
        self._like = v
        self.committed.emit(v)


class ColorEdit(QWidget):
    """Integer colour (as iJewel stores it) shown as a swatch + hex text."""
    committed = Signal(int)

    def __init__(self, value: int, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.btn = QPushButton()
        self.btn.setFixedSize(28, 22)
        self.txt = QLineEdit()
        self.txt.setFixedWidth(80)
        lay.addWidget(self.btn)
        lay.addWidget(self.txt)
        self._set(value)
        self.btn.clicked.connect(self._pick)
        self.txt.editingFinished.connect(self._typed)

    def _set(self, n: int):
        self.value = int(n)
        self.txt.setText(to_hex(n))
        self.btn.setStyleSheet(f"background:{to_hex(n)}; border:1px solid #888; border-radius:3px")

    def _pick(self):
        c = QColorDialog.getColor(QColor(to_hex(self.value)), self, "Colour")
        if c.isValid():
            n = int(c.name()[1:], 16)
            if n != self.value:
                self._set(n)
                self.committed.emit(n)

    def _typed(self):
        n = from_hex(self.txt.text())
        if n is None:
            self._set(self.value)
        elif n != self.value:
            self._set(n)
            self.committed.emit(n)


# ---------- forms ----------

class Form(QGroupBox):
    """A titled card of labelled fields bound to the document."""

    def __init__(self, ctx, title: str, parent=None):
        super().__init__(title, parent)
        self.ctx = ctx
        self.form = QFormLayout(self)
        self.form.setLabelAlignment(Qt.AlignRight)

    def _commit(self, obj: Getter, key, value):
        self.ctx.mutate(lambda d: obj(d).__setitem__(key, value), rebuild=False)

    def num(self, obj: Getter, key: str, label: str, after: Callable[[dict], None] | None = None):
        o = obj(self.ctx.data)
        e = NumberEdit(o.get(key))

        def commit(v):
            def fn(d):
                obj(d)[key] = v
                if after:
                    after(d)
            self.ctx.mutate(fn, rebuild=False)
        e.committed.connect(commit)
        self.form.addRow(label, e)
        return e

    def deg(self, obj: Getter, key: str, label: str):
        o = obj(self.ctx.data)
        e = NumberEdit(round(math.degrees(o.get(key) or 0), 6))
        e.committed.connect(lambda v: self._commit(obj, key, math.radians(v)))
        self.form.addRow(label, e)

    def bool(self, obj: Getter, key: str, label: str):
        o = obj(self.ctx.data)
        c = QCheckBox()
        c.setChecked(bool(o.get(key)))
        c.toggled.connect(lambda b: self._commit(obj, key, b))
        self.form.addRow(label, c)

    def text(self, obj: Getter, key: str, label: str):
        o = obj(self.ctx.data)
        e = QLineEdit(str(o.get(key) or ""))
        e.editingFinished.connect(lambda: e.isModified() and self._commit(obj, key, e.text()))
        self.form.addRow(label, e)

    def choice(self, obj: Getter, key: str, label: str, options: list, labels: list | None = None):
        o = obj(self.ctx.data)
        cb = QComboBox()
        for i, opt in enumerate(options):
            cb.addItem(labels[i] if labels else str(opt), opt)
        cur = o.get(key)
        if cur not in options:
            cb.addItem(f"{cur} (current)", cur)
        cb.setCurrentIndex(max(cb.findData(cur), 0))
        cb.currentIndexChanged.connect(lambda _i: self._commit(obj, key, cb.currentData()))
        self.form.addRow(label, cb)

    def vec3(self, obj: Getter, label: str, keys=("x", "y", "z"), degrees=False, after=None):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        o = obj(self.ctx.data)
        for k in keys:
            v = o.get(k, 0)
            e = NumberEdit(round(math.degrees(v), 6) if degrees else v)
            e.setToolTip(k)

            def commit(val, k=k):
                def fn(d):
                    obj(d)[k] = math.radians(val) if degrees else val
                    if after:
                        after(d)
                self.ctx.mutate(fn, rebuild=False)
            e.committed.connect(commit)
            lay.addWidget(e)
        lay.addStretch()
        self.form.addRow(label, row)

    def color(self, obj: Getter, key: str, label: str):
        o = obj(self.ctx.data)
        c = ColorEdit(o.get(key, 0))
        c.committed.connect(lambda n: self._commit(obj, key, n))
        self.form.addRow(label, c)

    def info(self, label: str, value: str):
        lab = QLabel(value)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.form.addRow(label, lab)


# ---------- spreadsheet-like table ----------

@dataclass
class Col:
    label: str
    get: Callable[[Any], Any]                       # row -> value
    set: Optional[Callable[[dict, Any, Any], None]] = None   # (doc, key, value)
    kind: str = "text"                              # text | num | int | color | bool | ro
    width: int = 0


class DataTable(QTableWidget):
    """Excel-like editing: type into a cell, Enter commits and moves down."""
    row_activated = Signal(object)      # key of the current row

    def __init__(self, ctx, cols: list[Col], parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.cols = cols
        self._keys: list = []
        self._loading = False
        self.setColumnCount(len(cols))
        self.setHorizontalHeaderLabels([c.label for c in cols])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                             | QAbstractItemView.AnyKeyPressed)
        self.verticalHeader().setDefaultSectionSize(24)
        self.setAlternatingRowColors(True)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for i, c in enumerate(cols):
            if c.width:
                self.setColumnWidth(i, c.width)
        self.itemChanged.connect(self._edited)
        self.cellDoubleClicked.connect(self._double)
        self.currentCellChanged.connect(lambda r, *_: self._emit_active(r))

    def load(self, rows: list[tuple[Any, Any]]):
        """rows: (key, row object). Keeps the current row when its key survives."""
        cur = self.current_key()
        self._loading = True
        self.setRowCount(len(rows))
        self._keys = [k for k, _ in rows]
        for r, (_key, obj) in enumerate(rows):
            for c, col in enumerate(self.cols):
                v = col.get(obj)
                it = QTableWidgetItem()
                editable = col.set is not None and col.kind != "ro"
                flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
                if col.kind == "bool":
                    it.setFlags(flags | (Qt.ItemIsUserCheckable if editable else Qt.NoItemFlags))
                    it.setCheckState(Qt.Checked if v else Qt.Unchecked)
                elif col.kind == "color":
                    it.setFlags(flags)
                    if isinstance(v, int):
                        it.setText(to_hex(v))
                        it.setBackground(QBrush(QColor(to_hex(v))))
                        lum = ((v >> 16) & 255) * 0.3 + ((v >> 8) & 255) * 0.59 + (v & 255) * 0.11
                        it.setForeground(QBrush(QColor("#000" if lum > 140 else "#fff")))
                    else:
                        it.setText("" if v is None else str(v))
                else:
                    it.setText(fmt_num(v) if col.kind in ("num", "int") and v is not None else ("" if v is None else str(v)))
                    it.setFlags(flags | (Qt.ItemIsEditable if editable else Qt.NoItemFlags))
                    if not editable:
                        it.setForeground(QBrush(QColor("#888")))
                it.setData(Qt.UserRole, v)
                self.setItem(r, c, it)
        self._loading = False
        if cur in self._keys:
            self.setCurrentCell(self._keys.index(cur), max(self.currentColumn(), 0))

    def key_at(self, row: int):
        return self._keys[row] if 0 <= row < len(self._keys) else None

    def current_key(self):
        return self.key_at(self.currentRow())

    def selected_keys(self) -> list:
        rows = sorted({i.row() for i in self.selectedIndexes()})
        return [self._keys[r] for r in rows if r < len(self._keys)]

    def select_key(self, key):
        if key in self._keys:
            self.setCurrentCell(self._keys.index(key), max(self.currentColumn(), 0))

    def filter(self, text: str):
        t = text.lower().strip()
        for r in range(self.rowCount()):
            hit = not t or any(t in (self.item(r, c).text() or "").lower()
                               for c in range(self.columnCount()) if self.item(r, c))
            self.setRowHidden(r, not hit)

    def _emit_active(self, row):
        if not self._loading:
            self.row_activated.emit(self.key_at(row))

    def _edited(self, it: QTableWidgetItem):
        if self._loading:
            return
        col = self.cols[it.column()]
        key = self.key_at(it.row())
        if col.set is None:
            return
        try:
            if col.kind == "bool":
                v = it.checkState() == Qt.Checked
            elif col.kind in ("num", "int"):
                v = parse_num(it.text(), it.data(Qt.UserRole))
                if col.kind == "int":
                    v = int(v)
            else:
                v = it.text().strip()
        except ValueError as e:
            self.ctx.toast(str(e))
            self._loading = True
            it.setText(fmt_num(it.data(Qt.UserRole)))
            self._loading = False
            return
        if v == it.data(Qt.UserRole):
            return
        self._loading = True
        it.setData(Qt.UserRole, v)
        self._loading = False
        self.ctx.mutate(lambda d: col.set(d, key, v), rebuild=False)

    def _double(self, row, column):
        col = self.cols[column]
        if col.kind == "color" and col.set:
            it = self.item(row, column)
            cur = it.data(Qt.UserRole)
            c = QColorDialog.getColor(QColor(to_hex(cur if isinstance(cur, int) else 0xFFFFFF)), self, "Colour")
            if c.isValid():
                n = int(c.name()[1:], 16)
                key = self.key_at(row)
                self.ctx.mutate(lambda d: col.set(d, key, n), rebuild=False)
                self._loading = True
                it.setText(to_hex(n))
                it.setData(Qt.UserRole, n)
                it.setBackground(QBrush(QColor(to_hex(n))))
                self._loading = False

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.state() != QAbstractItemView.EditingState:
            r = self.currentRow() + 1
            while r < self.rowCount() and self.isRowHidden(r):
                r += 1
            if r < self.rowCount():
                self.setCurrentCell(r, self.currentColumn())
            return
        if e.matches(QKeySequence.Copy):
            rows = sorted({i.row() for i in self.selectedIndexes()})
            text = "\n".join("\t".join(self.item(r, c).text() if self.item(r, c) else "" for c in range(self.columnCount()))
                             for r in rows)
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            return
        super().keyPressEvent(e)

    def closeEditor(self, editor, hint):
        # Enter inside a cell commits and moves down, like a spreadsheet
        super().closeEditor(editor, hint)
        if hint == QAbstractItemView.SubmitModelCache:
            r = self.currentRow() + 1
            if r < self.rowCount():
                self.setCurrentCell(r, self.currentColumn())


# ---------- generic parameter editor ----------

def leaves(obj: dict, path=(), depth=0, out=None, skip_top=("type", "uuid", "metadata")):
    out = [] if out is None else out
    for k, v in obj.items():
        if not path and k in skip_top:
            continue
        p = path + (k,)
        if v is None or not isinstance(v, (dict, list)):
            out.append((p, v, "plain"))
        elif is_rgb(v):
            out.append((p, v, "rgb"))
        elif is_vec(v):
            out.append((p, v, "vec"))
        elif isinstance(v, list) and len(v) <= 16 and all(isinstance(x, (int, float, str)) for x in v):
            out.append((p, v, "arr"))
        elif isinstance(v, dict) and depth < 5:
            leaves(v, p, depth + 1, out, skip_top)
    return out


def get_at(o, path):
    for k in path:
        o = o[k]
    return o


def set_at(o, path, v):
    get_at(o, path[:-1])[path[-1]] = v


class ParamEditor(QTableWidget):
    """Every simple setting inside an object, editable in place."""

    def __init__(self, ctx, root: Getter, skip=(), parent=None, after=None):
        super().__init__(parent)
        self.ctx, self.root, self.skip, self.after = ctx, root, set(skip), after
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.horizontalHeader().setStretchLastSection(True)
        self.setColumnWidth(0, 260)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(24)
        self._rows: list = []
        self._loading = False
        self.itemChanged.connect(self._edited)
        self.cellDoubleClicked.connect(self._double)
        self.reload()

    def reload(self, query: str = ""):
        self._loading = True
        obj = self.root(self.ctx.data)
        rows = [r for r in leaves(obj) if ".".join(map(str, r[0])) not in self.skip
                and (not query or query.lower() in ".".join(map(str, r[0])).lower())]
        self._rows = rows
        self.setRowCount(len(rows))
        for i, (path, v, kind) in enumerate(rows):
            name = QTableWidgetItem(".".join(map(str, path)))
            name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.setItem(i, 0, name)
            it = QTableWidgetItem()
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if isinstance(v, bool):
                it.setFlags(flags | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if v else Qt.Unchecked)
            elif kind == "plain" and is_color_key(str(path[-1]), v):
                it.setText(to_hex(v) + "   (double-click)")
                it.setBackground(QBrush(QColor(to_hex(v))))
                it.setFlags(flags)
            elif kind == "rgb":
                h = "#%02X%02X%02X" % tuple(round(max(0, min(1, v[c])) * 255) for c in "rgb")
                it.setText(f"{v['r']:.4g}, {v['g']:.4g}, {v['b']:.4g}   {h}")
                it.setBackground(QBrush(QColor(h)))
                it.setFlags(flags | Qt.ItemIsEditable)
            elif kind == "vec":
                ks = [c for c in "xyzw" if c in v]
                it.setText(", ".join(fmt_num(v[c]) for c in ks))
                it.setFlags(flags | Qt.ItemIsEditable)
            elif kind == "arr":
                it.setText(json.dumps(v))
                it.setFlags(flags | Qt.ItemIsEditable)
            elif isinstance(v, str) and len(v) > 240:
                it.setText(f"({len(v)} chars of data - not editable here)")
                it.setFlags(flags)
                it.setForeground(QBrush(QColor("#888")))
            elif v is None:
                it.setText("null")
                it.setFlags(flags)
                it.setForeground(QBrush(QColor("#888")))
            else:
                it.setText(fmt_num(v) if isinstance(v, (int, float)) else str(v))
                it.setFlags(flags | Qt.ItemIsEditable)
            self.setItem(i, 1, it)
        self._loading = False

    def _commit(self, path, value):
        def fn(d):
            set_at(self.root(d), path, value)
            if self.after:
                self.after(d, path, value)
        self.ctx.mutate(fn, rebuild=False)

    def _edited(self, it: QTableWidgetItem):
        if self._loading or it.column() != 1:
            return
        path, v, kind = self._rows[it.row()]
        try:
            if isinstance(v, bool):
                nv = it.checkState() == Qt.Checked
            elif kind == "vec":
                ks = [c for c in "xyzw" if c in v]
                nums = [parse_num(x) for x in it.text().split(",")]
                if len(nums) != len(ks):
                    raise ValueError(f"Enter {len(ks)} numbers separated by commas")
                nv = {**v, **dict(zip(ks, nums))}
            elif kind == "rgb":
                nums = [parse_num(x) for x in it.text().split("#")[0].split(",")]
                if len(nums) != 3:
                    raise ValueError("Enter r, g, b (0-1)")
                nv = {**v, "r": nums[0], "g": nums[1], "b": nums[2]}
            elif kind == "arr":
                nv = json.loads(it.text())
                if not isinstance(nv, list):
                    raise ValueError("Must be a JSON array")
            elif isinstance(v, (int, float)):
                nv = parse_num(it.text(), v)
            else:
                nv = it.text()
        except (ValueError, json.JSONDecodeError) as e:
            self.ctx.toast(f"{'.'.join(map(str, path))}: {e}")
            self.reload()
            return
        self._rows[it.row()] = (path, nv, kind)
        self._commit(path, nv)

    def _double(self, row, col):
        path, v, kind = self._rows[row]
        if kind == "plain" and is_color_key(str(path[-1]), v):
            c = QColorDialog.getColor(QColor(to_hex(v)), self, ".".join(map(str, path)))
            if c.isValid():
                self._commit(path, int(c.name()[1:], 16))
                self.reload()
        elif kind == "rgb":
            h = "#%02X%02X%02X" % tuple(round(max(0, min(1, v[c])) * 255) for c in "rgb")
            c = QColorDialog.getColor(QColor(h), self, ".".join(map(str, path)))
            if c.isValid():
                self._commit(path, {**v, "r": c.redF(), "g": c.greenF(), "b": c.blueF()})
                self.reload()


def button(text: str, fn, tip: str = "", danger=False) -> QPushButton:
    b = QPushButton(text)
    b.clicked.connect(fn)
    if tip:
        b.setToolTip(tip)
    if danger:
        b.setProperty("danger", True)
    return b


def toolbar(*widgets) -> QWidget:
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 4)
    for x in widgets:
        if x == "stretch":
            lay.addStretch()
        elif isinstance(x, str):
            lab = QLabel(x)
            lab.setStyleSheet("color:#888")
            lay.addWidget(lab)
        else:
            lay.addWidget(x)
    return w

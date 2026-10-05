"""Main window: section navigation, file handling, undo, the 3D dock."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPalette, QColor
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QStackedWidget, QStyleFactory, QWidget)

from ..model.document import Document, NotAVjson
from .context import Context
from .sections.cameras import CamerasSection
from .sections.configurator import ConfiguratorSection
from .sections.environment import EnvironmentSection
from .sections.materials import MaterialsSection
from .sections.other import PluginsSection, RawSection, TexturesSection, ValidateSection
from .sections.overview import OverviewSection
from .viewport_panel import ViewportPanel

APP = "vjson Studio 3D"
GROUPS = [(None, ["overview"]), ("Scene", ["environment", "cameras", "textures"]),
          ("Materials", ["materials", "configurator"]), ("Advanced", ["plugins", "validate", "raw"])]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("vjson-studio-3d", "vjson-studio-3d")
        self.ctx = Context()
        self.resize(1600, 950)
        self.setAcceptDrops(True)

        self.sections = {s.key: s for s in (
            OverviewSection(self.ctx, self.go), EnvironmentSection(self.ctx), CamerasSection(self.ctx),
            TexturesSection(self.ctx), MaterialsSection(self.ctx), ConfiguratorSection(self.ctx),
            PluginsSection(self.ctx), ValidateSection(self.ctx), RawSection(self.ctx))}
        self.nav = QListWidget()
        self.nav.setFixedWidth(190)
        self.stack = QStackedWidget()
        self.empty = QLabel("Open a .vjson to start  (Ctrl+O, or drop a file here)\n\n"
                            "Load a .glb in the 3D viewport to place cameras (Ctrl+G)")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color:#888; font-size:15px")
        self.stack.addWidget(self.empty)
        for s in self.sections.values():
            self.stack.addWidget(s)
        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.nav)
        cl.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.nav.currentItemChanged.connect(self._nav_changed)

        self.viewport = ViewportPanel(self.ctx)
        self.ctx.viewport = self.viewport
        self.dock = QDockWidget("3D viewport", self)
        self.dock.setObjectName("viewport")
        self.dock.setWidget(self.viewport)
        self.dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                              | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.resizeDocks([self.dock], [720], Qt.Horizontal)

        self._menus()
        self.ctx.changed.connect(self._changed)
        self.ctx.message.connect(lambda m, ms: self.statusBar().showMessage(m, ms))
        self.ctx.view_selected.connect(self.sections["cameras"].view_selected_externally)
        self.ctx.view_selected.connect(lambda i: self.go("cameras") if i >= 0 and self.current_key() != "cameras" else None)
        self._build_nav()
        self._update_chrome()
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
            self.restoreState(self.settings.value("state"))

    # ---------- menus ----------

    def _menus(self):
        def act(menu, text, fn, shortcut=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(fn)
            menu.addAction(a)
            return a
        f = self.menuBar().addMenu("&File")
        act(f, "Open vjson...", self.open_dialog, QKeySequence.Open)
        act(f, "Load GLB into viewport...", self.viewport.pick_glb, "Ctrl+G")
        f.addSeparator()
        self.save_act = act(f, "Save", self.save, QKeySequence.Save)
        self.save_as_act = act(f, "Save as...", self.save_as, QKeySequence.SaveAs)
        f.addSeparator()
        act(f, "Quit", self.close, QKeySequence.Quit)
        e = self.menuBar().addMenu("&Edit")
        self.undo_act = act(e, "Undo", self.undo, QKeySequence.Undo)
        self.redo_act = act(e, "Redo", self.redo, QKeySequence.Redo)
        v = self.menuBar().addMenu("&View")
        v.addAction(self.dock.toggleViewAction())
        self.dark_act = act(v, "Dark theme", self.toggle_theme)
        self.dark_act.setCheckable(True)
        self.dark_act.setChecked(self.settings.value("dark", False, bool))
        self.apply_theme(self.dark_act.isChecked())
        c = self.menuBar().addMenu("&Cameras")
        cs = lambda: self.sections["cameras"]
        # window-wide, so they work while the 3D viewport has focus
        act(c, "Add view from viewport", lambda: self.ctx.doc and cs().add_from_viewport(), "Ctrl+Shift+A")
        act(c, "Update selected view from viewport", lambda: self.ctx.doc and cs().update_from_viewport(), "Ctrl+Shift+U")
        act(c, "Go to selected view", lambda: self.ctx.doc and cs().go_to(), "Ctrl+Shift+G")
        act(c, "Play all views", lambda: self.ctx.doc and cs().play(), "Ctrl+Shift+P")
        act(c, "Stop playback", self.viewport.view.stop, "Esc")

    # ---------- navigation ----------

    def _build_nav(self):
        cur = self.current_key() or "overview"
        self.nav.blockSignals(True)
        self.nav.clear()
        for group, keys in GROUPS:
            if group:
                h = QListWidgetItem(group.upper())
                h.setFlags(Qt.NoItemFlags)
                h.setForeground(QColor("#888"))
                self.nav.addItem(h)
            for k in keys:
                s = self.sections[k]
                n = s.count() if self.ctx.doc else None
                it = QListWidgetItem(f"   {s.title}" + (f"   ({n})" if n is not None else ""))
                it.setData(Qt.UserRole, k)
                if not self.ctx.doc:
                    it.setFlags(Qt.NoItemFlags)
                self.nav.addItem(it)
                if k == cur:
                    self.nav.setCurrentItem(it)
        self.nav.blockSignals(False)

    def current_key(self):
        it = self.nav.currentItem()
        return it.data(Qt.UserRole) if it else None

    def go(self, key):
        for r in range(self.nav.count()):
            if self.nav.item(r).data(Qt.UserRole) == key:
                self.nav.setCurrentRow(r)
                return

    def _nav_changed(self, it, _prev):
        if not it or not self.ctx.doc:
            return
        s = self.sections[it.data(Qt.UserRole)]
        if s.stale:
            s.refresh()
        self.stack.setCurrentWidget(s)

    # ---------- document ----------

    def _changed(self, rebuild: bool):
        for s in self.sections.values():
            s.stale = True
        cur = self.sections.get(self.current_key())
        if cur is not None:
            if rebuild or cur.key in ("validate", "raw", "overview"):
                QTimer.singleShot(0, cur.refresh)       # not inside the signal that is editing it
            else:
                cur.stale = False
                if cur.key == "cameras":
                    cur.value_edited()
        self.viewport.doc_changed()
        self._build_nav()
        self._update_chrome()

    def _update_chrome(self):
        doc = self.ctx.doc
        name = (doc.path.name if doc and doc.path else "untitled") if doc else ""
        self.setWindowTitle(f"{'* ' if doc and doc.dirty else ''}{name}{' - ' if name else ''}{APP}")
        for a in (self.save_act, self.save_as_act):
            a.setEnabled(doc is not None)
        self.undo_act.setEnabled(bool(doc and doc.can_undo()))
        self.redo_act.setEnabled(bool(doc and doc.can_redo()))

    def open_dialog(self):
        if not self._maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open vjson", self.settings.value("last_dir", ""),
                                              "iJewel3D scene (*.vjson *.json);;All files (*)")
        if path:
            self.open(path)

    def open(self, path: str):
        try:
            doc = Document.open(path)
        except (OSError, ValueError, NotAVjson) as e:
            QMessageBox.warning(self, "Could not open file", f"{Path(path).name}\n\n{e}")
            return
        self.settings.setValue("last_dir", str(Path(path).parent))
        self.ctx.doc = doc
        self.ctx.selected_view = -1
        for s in self.sections.values():
            s.stale = True
        self._build_nav()
        self.go("overview")
        self._nav_changed(self.nav.currentItem(), None)
        self.viewport.doc_changed()
        if self.viewport.view.model:
            self.viewport.go_default()
        self._update_chrome()
        self.ctx.toast(f"Opened {Path(path).name}")

    def save(self):
        doc = self.ctx.doc
        if not doc:
            return False
        if not doc.path:
            return self.save_as()
        return self._write(None)

    def save_as(self):
        doc = self.ctx.doc
        if not doc:
            return False
        start = str(doc.path.with_name(doc.path.stem + "_edited.vjson")) if doc.path else ""
        path, _ = QFileDialog.getSaveFileName(self, "Save vjson as", start, "iJewel3D scene (*.vjson)")
        return self._write(path) if path else False

    def _write(self, path):
        from ..model.validate import ERR, validate
        errors = [i for i in validate(self.ctx.data) if i.sev == ERR]
        try:
            out = self.ctx.doc.save(path)
        except OSError as e:
            QMessageBox.warning(self, "Could not save", str(e))
            return False
        self._update_chrome()
        self.ctx.toast(f"Saved {out.name}" + (f"  ({len(errors)} validation error(s) - see Validate)" if errors else ""), 6000)
        return True

    def undo(self):
        if self.ctx.doc and self.ctx.doc.undo():
            self.ctx.changed.emit(True)
            self.ctx.toast("Undone")

    def redo(self):
        if self.ctx.doc and self.ctx.doc.redo():
            self.ctx.changed.emit(True)
            self.ctx.toast("Redone")

    def _maybe_save(self) -> bool:
        doc = self.ctx.doc
        if not doc or not doc.dirty:
            return True
        r = QMessageBox.question(self, "Unsaved changes", f"Save changes to {doc.path.name if doc.path else 'the file'}?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    # ---------- theme ----------

    def toggle_theme(self):
        self.settings.setValue("dark", self.dark_act.isChecked())
        self.apply_theme(self.dark_act.isChecked())

    def apply_theme(self, dark: bool):
        app = QApplication.instance()
        app.setStyle(QStyleFactory.create("Fusion"))
        if not dark:
            app.setPalette(app.style().standardPalette())
            return
        p = QPalette()
        for role, c in ((QPalette.Window, "#2b2d31"), (QPalette.WindowText, "#e5e7eb"), (QPalette.Base, "#1f2023"),
                        (QPalette.AlternateBase, "#27292d"), (QPalette.Text, "#e5e7eb"), (QPalette.Button, "#34363b"),
                        (QPalette.ButtonText, "#e5e7eb"), (QPalette.Highlight, "#3b82f6"),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#34363b"),
                        (QPalette.ToolTipText, "#e5e7eb"), (QPalette.PlaceholderText, "#8b8f97")):
            p.setColor(role, QColor(c))
        app.setPalette(p)

    # ---------- window events ----------

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".glb"):
                self.viewport.load(p)
            elif p.lower().endswith((".vjson", ".json")) and self._maybe_save():
                self.open(p)

    def closeEvent(self, e):
        if not self._maybe_save():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        self.viewport.view.close()
        e.accept()

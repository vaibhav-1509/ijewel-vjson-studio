"""Shared state between the main window, the sections and the viewport."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

from ..model.document import Document


class Context(QObject):
    # rebuild=True: structure changed (rows added/removed, undo) - sections redraw.
    # rebuild=False: a value edited in place - the editing widget already shows it.
    changed = Signal(bool)
    doc_opened = Signal()
    message = Signal(str, int)
    view_selected = Signal(int)          # camera view index, -1 for none

    def __init__(self):
        super().__init__()
        self.doc: Document | None = None
        self.viewport = None               # ViewportPanel, set by the main window
        self.selected_view = -1

    @property
    def data(self) -> dict:
        return self.doc.data

    def toast(self, msg: str, ms: int = 3500):
        self.message.emit(msg, ms)

    def mutate(self, fn: Callable[[dict], object], toast: str | None = None, rebuild: bool = True):
        """Run one undoable edit. Errors become a message and change nothing."""
        if not self.doc:
            return None
        try:
            result = self.doc.mutate(fn)
        except ValueError as e:
            self.toast(str(e), 6000)
            self.changed.emit(True)        # put the edited widget back to the real value
            return None
        if toast:
            self.toast(toast)
        self.changed.emit(rebuild)
        return result

    def select_view(self, index: int):
        self.selected_view = index
        self.view_selected.emit(index)

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget


class Section(QWidget):
    """One page of the editor. ``build`` recreates its contents from the document."""
    title = ""
    key = ""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(8, 8, 8, 8)
        self._body: QWidget | None = None
        self.stale = True

    def count(self) -> int | None:
        return None

    def refresh(self):
        if self._body is not None:
            self._body.setParent(None)
            self._body.deleteLater()
        self._body = QWidget()
        lay = QVBoxLayout(self._body)
        lay.setContentsMargins(0, 0, 0, 0)
        if self.ctx.doc:
            self.build(lay)
        self._outer.addWidget(self._body)
        self.stale = False

    def build(self, lay: QVBoxLayout):
        raise NotImplementedError

    @staticmethod
    def scroll(*widgets) -> QScrollArea:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        for w in widgets:
            if w is not None:
                lay.addWidget(w)
        lay.addStretch()
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(inner)
        return sa

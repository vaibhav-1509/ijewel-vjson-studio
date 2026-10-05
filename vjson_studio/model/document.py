"""An open .vjson: data, file path, save style, undo/redo and dirty state."""
from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path
from typing import Callable

from . import jsonio

UNDO_LIMIT = 40


class NotAVjson(ValueError):
    pass


class Document:
    def __init__(self, data: dict, path: Path | None = None, style: str = jsonio.JS,
                 newline: str = "\n", bom: bool = False):
        self.data = data
        self.path = path
        self.style = style
        self.newline = newline        # kept from the file, so a save never rewrites every line ending
        self.bom = bom
        self.dirty = False
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._backed_up = False

    # ---------- files ----------

    @classmethod
    def open(cls, path: str | os.PathLike) -> "Document":
        p = Path(path)
        raw = p.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        newline = "\r\n" if "\r\n" in text else "\n"
        data, style = jsonio.loads(text.replace("\r\n", "\n"))
        if not isinstance(data, dict) or not all(k in data for k in ("resources", "plugins", "scene")):
            raise NotAVjson("This does not look like an iJewel3D .vjson (missing scene / plugins / resources).")
        data["resources"].setdefault("materials", {})
        return cls(data, p, style, newline, bom)

    def text(self) -> str:
        """The exact text a save writes: the file's number style, line endings and BOM."""
        out = jsonio.dumps(self.data, self.style)
        if self.newline != "\n":
            out = out.replace("\n", self.newline)
        return ("﻿" if self.bom else "") + out

    def save(self, path: str | os.PathLike | None = None) -> Path:
        """Write in the style the file was read in. The first save over the
        original keeps a ``.bak`` of it next to the file."""
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("No file name - use Save As")
        if target.exists() and not self._backed_up and target == self.path:
            bak = target.with_suffix(target.suffix + ".bak")
            if not bak.exists():
                shutil.copy2(target, bak)
            self._backed_up = True
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(self.text(), encoding="utf-8", newline="")
        os.replace(tmp, target)                 # never leave a half-written file
        self.path = target
        self.dirty = False
        return target

    # ---------- undo ----------

    def mutate(self, fn: Callable[[dict], object]):
        """Run ``fn(data)`` as one undoable step. If it raises, nothing changes."""
        before = copy.deepcopy(self.data)
        try:
            result = fn(self.data)
        except Exception:
            self.data = before
            raise
        self._undo.append(before)
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()
        self.dirty = True
        return result

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.data)
        self.data = self._undo.pop()
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.data)
        self.data = self._redo.pop()
        self.dirty = True
        return True

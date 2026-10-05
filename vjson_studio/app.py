"""Entry point: ``vjson-studio [file.vjson] [model.glb]`` or ``python -m vjson_studio``.

``--smoke`` opens the window (and any files given), then quits with exit code 0
after a moment - used to check that a packaged build starts.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "vjson-studio-3d"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_crash(exc_type, exc, tb):
    """A packaged app has no console, so an error would vanish - write it down instead."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        (log_dir() / "error.log").open("a", encoding="utf-8").write(text + "\n")
    except OSError:
        pass
    sys.__excepthook__(exc_type, exc, tb)


def main(argv=None) -> int:
    sys.excepthook = _log_crash
    try:
        return _run(argv)
    except Exception:
        _log_crash(*sys.exc_info())
        return 1


def _run(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    smoke = "--smoke" in argv
    argv = [a for a in argv if a != "--smoke"]
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from . import __version__
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("vjson Studio 3D")
    app.setApplicationVersion(__version__)
    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("resources") / "icon.png")))
    w = MainWindow()
    w.show()
    for a in argv:
        if a.lower().endswith(".glb"):
            w.viewport.load(a)
        elif a.lower().endswith((".vjson", ".json")):
            w.open(a)
    if smoke:
        def finish():
            if w.ctx.doc:
                w.ctx.doc.dirty = False
            print(f"smoke ok: vjson Studio 3D {__version__}", flush=True)
            w.close()
            app.quit()
        QTimer.singleShot(2500, finish)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

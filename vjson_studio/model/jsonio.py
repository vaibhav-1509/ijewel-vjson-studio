"""Load and save .vjson text so that an unedited save is byte-identical.

iJewel3D writes with JavaScript's ``JSON.stringify(d, null, 2)``. Python's
``json.dumps`` formats some floats differently (``3.9e-05`` vs ``0.000039``),
so files written by iJewel need a JavaScript-style number writer. Files that
an earlier Python script wrote use Python's style. The style a file was read
in is detected on load and reused on save.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

JS = "js"
PYTHON = "python"


def js_number(f: float | int) -> str:
    """ECMA-262 Number::toString for a finite double."""
    if isinstance(f, bool):
        return "true" if f else "false"
    if isinstance(f, int):
        return str(f)
    if not math.isfinite(f):
        return "null"                       # what JSON.stringify writes
    if f == 0:
        return "0"
    sign = "-" if f < 0 else ""
    # repr gives the shortest round-trip digits, the same digits JS chooses
    mant, _, exp = repr(abs(f)).partition("e")
    ip, _, fp = mant.partition(".")
    if fp == "0":
        fp = ""
    raw = ip + fp
    digits = raw.lstrip("0")
    lead = len(raw) - len(digits)
    n = len(ip) - lead + (int(exp) if exp else 0)   # decimal point position
    d = digits.rstrip("0")
    k = len(d)
    if k <= n <= 21:
        s = d + "0" * (n - k)
    elif 0 < n <= 21:
        s = d[:n] + "." + d[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * (-n) + d
    else:
        e = n - 1
        s = d[0] + ("." + d[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + s


def _dump_js(o: Any, ind: int, w: Callable[[str], None]) -> None:
    if isinstance(o, dict):
        if not o:
            w("{}")
            return
        pad = "\n" + "  " * (ind + 1)
        w("{")
        for i, (k, v) in enumerate(o.items()):
            w(("," if i else "") + pad + json.dumps(k, ensure_ascii=False) + ": ")
            _dump_js(v, ind + 1, w)
        w("\n" + "  " * ind + "}")
    elif isinstance(o, list):
        if not o:
            w("[]")
            return
        pad = "\n" + "  " * (ind + 1)
        w("[")
        for i, v in enumerate(o):
            w(("," if i else "") + pad)
            _dump_js(v, ind + 1, w)
        w("\n" + "  " * ind + "]")
    elif isinstance(o, str):
        w(json.dumps(o, ensure_ascii=False))
    elif o is None:
        w("null")
    else:
        w(js_number(o))


def dumps(data: Any, style: str = JS) -> str:
    if style == PYTHON:
        return json.dumps(data, indent=2, ensure_ascii=False)
    out: list[str] = []
    _dump_js(data, 0, out.append)
    return "".join(out)


def detect_style(text: str, data: Any) -> str:
    """The writer that reproduces ``text`` exactly; JS when neither does."""
    if dumps(data, JS) == text:
        return JS
    if dumps(data, PYTHON) == text:
        return PYTHON
    return JS


def loads(text: str) -> tuple[Any, str]:
    data = json.loads(text)
    return data, detect_style(text, data)

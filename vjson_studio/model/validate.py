"""Consistency checks, each with an optional one-click fix."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from . import cameras as cam
from . import materials as mat

ERR, WARN, INFO = "err", "warn", "info"


@dataclass
class Issue:
    sev: str
    msg: str
    detail: str = ""
    fix: Optional[Callable[[dict], None]] = None
    fix_label: str = ""


def _counts(items):
    out: dict = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return {k: n for k, n in out.items() if n > 1}


def validate(doc: dict) -> list[Issue]:
    issues: list[Issue] = []
    mats, vs = mat.materials(doc), mat.variations(doc)

    dup = _counts(v.get("title") for v in vs)
    if dup:
        def keep_first(d):
            seen, cf = set(), mat.configurator(d, True)
            cf["variations"] = [v for v in cf["variations"] if not (v.get("title") in seen or seen.add(v.get("title")))]
        issues.append(Issue(ERR, f"{len(dup)} duplicate configurator title(s)",
                            ", ".join(f"{t} x{n}" for t, n in list(dup.items())[:12]), keep_first, "Keep first of each"))

    missing = [v for v in vs if any(x.get("uuid") not in mats for x in v.get("materials") or [])]
    if missing:
        def drop_broken(d):
            m = mat.materials(d)
            for v in mat.variations(d):
                v["materials"] = [x for x in v.get("materials") or [] if x.get("uuid") in m]
        issues.append(Issue(ERR, f"{len(missing)} configurator entr{'ies' if len(missing) > 1 else 'y'} point at missing materials",
                            ", ".join(v.get("title", "") for v in missing[:12]), drop_broken, "Remove broken links"))

    refd = {x.get("uuid") for v in vs for x in v.get("materials") or []}
    ground = mat.ground_material_uuid(doc)
    unreg = [m for u, m in mats.items() if u not in refd and u != ground]
    if unreg:
        issues.append(Issue(WARN, f"{len(unreg)} material(s) are not in the Material Configurator",
                            "iJewel3D ignores these. " + ", ".join(m.get("name", "") for m in unreg[:10]),
                            mat.register_unlisted, "Register them"))

    key_bad = [(k, m) for k, m in mats.items() if m.get("uuid") != k]
    if key_bad:
        def fix_keys(d):
            for k, m in mat.materials(d).items():
                if m.get("uuid") != k:
                    m["uuid"] = k
                    if m.get("userData"):
                        m["userData"]["uuid"] = k
        issues.append(Issue(ERR, f"{len(key_bad)} material(s) whose key differs from their uuid",
                            ", ".join(m.get("name", "") for _, m in key_bad[:8]), fix_keys, "Fix uuids"))

    bad_color = [m for m in mats.values() if "color" in m and not (
        isinstance(m["color"], int) and not isinstance(m["color"], bool) and 0 <= m["color"] <= 0xFFFFFF)]
    if bad_color:
        issues.append(Issue(ERR, f"{len(bad_color)} material(s) with an invalid colour value",
                            ", ".join(m.get("name", "") for m in bad_color[:8])))

    dup_n = _counts(m.get("name") for m in mats.values())
    if dup_n:
        issues.append(Issue(INFO, f"{len(dup_n)} material name(s) used more than once",
                            ", ".join(f"{n} x{c}" for n, c in list(dup_n.items())[:8])
                            + " - harmless (original packs share names), but renaming makes them easier to tell apart."))

    tex = doc["resources"].get("textures") or {}

    def ref_ok(ref, label):
        if ref and ref.get("uuid") and ref["uuid"] not in tex:
            issues.append(Issue(ERR, f"{label} points at a texture that is not in the file", ref["uuid"]))
    ref_ok(doc["scene"].get("environment"), "Scene environment")
    ref_ok(doc["scene"].get("background"), "Scene background")
    dia = next((p for p in doc["plugins"] if p.get("type") == "Diamond"), None)
    if dia:
        ref_ok(dia.get("envMap"), "Gem env map")
    if ground and ground not in mats:
        issues.append(Issue(ERR, "Ground material is missing", ground))

    views = cam.views(doc)
    dc = _counts(v.get("name") for v in views)
    if dc:
        issues.append(Issue(WARN, "Camera views share a name", ", ".join(f"{n} x{c}" for n, c in dc.items())))
    custom = [v for v in views if cam.has_custom_orientation(v)]
    if custom:
        issues.append(Issue(INFO, f"{len(custom)} camera view(s) have a custom orientation (roll / different aim)",
                            "Editing their position or target recomputes orientation to look straight at the target."))
    return issues

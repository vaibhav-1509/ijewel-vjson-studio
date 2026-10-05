"""Materials and the Material Configurator.

iJewel3D only shows a material when a MaterialConfiguratorPlugin variation
references it, so every operation here keeps that rule: adding a material
registers a variation, renaming keeps a 1:1 variation title in sync, and
deleting drops variations that pointed only at the deleted materials.

All functions take the document dict and change it in place. They are the
operations the UI calls (through undo), and the ones a CSV import will call.
"""
from __future__ import annotations

import copy
import re
import uuid as _uuid

BUILTIN = {
    "metal": {"metadata": {"version": 4.6001, "type": "Material", "generator": "Material.toJSON"}, "uuid": "",
              "type": "MeshStandardMaterial2", "name": "", "color": 12763843, "roughness": 0, "metalness": 1,
              "sheen": 0, "sheenColor": 0, "sheenRoughness": 1, "emissive": 0, "specularIntensity": 1,
              "specularColor": 16777215, "clearcoat": 0, "clearcoatRoughness": 0, "dispersion": 0,
              "iridescence": 0, "iridescenceIOR": 1.3, "iridescenceThicknessRange": [100, 400], "anisotropy": 0,
              "anisotropyRotation": 0, "envMapRotation": [0, 0, 0, "XYZ"], "envMapIntensity": 1,
              "reflectivity": 0.5, "transmission": 0, "thickness": 0, "attenuationDistance": 0,
              "attenuationColor": 16777215, "side": 2, "blendColor": 0, "fog": False,
              "userData": {"gltfExtensions": {}}},
    "diamond": {"metadata": {"version": 4.6001, "type": "DiamondMaterial", "generator": "DiamondMaterial.toJSON"},
                "name": "", "uuid": "", "color": 16777215, "envMapIntensity": 1.3, "envMapIndex": 0,
                "envMapRotationOffset": 0, "envMapRotationOffsetX": 0, "envMapRotationOffsetY": 0,
                "envMapRotationOffsetZ": 0, "dispersion": 0, "squashFactor": 0.98, "geometryFactor": 0.5,
                "gammaFactor": 1, "absorptionFactor": 1, "reflectivity": 0.5, "refractiveIndex": 2.6,
                "rayBounces": 5, "diamondOrientedEnvMap": 0, "boostFactors": {"x": 1, "y": 1, "z": 1, "isVector3": True},
                "transmission": 0, "isDiamondMaterialParameters": True,
                "userData": {"separateEnvMapIntensity": True}, "type": "DiamondMaterial"},
}

PRESETS = {
    "metal": [("Yellow", 0xE5B377), ("Rose", 0xF2AF83), ("White", 0xC2C2C3), ("Black", 0x262626)],
    "diamond": [("White", 0xFFFFFF), ("Yellow", 0xFFFF00), ("Pink", 0xF9DFEC), ("Blue", 0xBCE6FE),
                ("Green", 0xBCFED8), ("Red", 0xFAC9C9), ("Black", 0x262626)],
}

# standard set (name.csv): 4 metals + mainstone-<shape>-<colour>
STD_METALS = {"metal-yellow": 0xE5B377, "metal-rose": 0xF2AF83, "metal-white": 0xC2C2C3, "metal-black": 0x262626}
STD_LOCATIONS = ["mainstone"]
STD_SHAPES = ["asscher", "baguette", "baguette_Straight", "briolette", "calf", "cushion", "cushion_Square", "emerald",
              "emerald_square", "french", "half_moon", "heart", "hexagon", "marquise", "octagon", "oldEuropean", "oval",
              "pear", "peruzzi", "princess", "radiant", "radiant_square", "round", "sphere", "table",
              "tapered_baguette", "triangle", "trillion_curved", "trillion_straight"]
STD_COLORS = {"white": 0xFFFFFF, "black": 0x262626, "green": 0xBCFED8, "pink": 0xF9DFEC, "blue": 0xBCE6FE,
              "red": 0xFAC9C9, "yellow": 0xFFFF00}


def new_uuid() -> str:
    return str(_uuid.uuid4())


def to_hex(n: int) -> str:
    return "#%06X" % (int(n) & 0xFFFFFF)


def from_hex(s: str) -> int | None:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(s).strip())
    return int(m.group(1), 16) if m else None


# ---------- lookups ----------

def materials(doc: dict) -> dict:
    return doc["resources"].setdefault("materials", {})


def configurator(doc: dict, create: bool = False) -> dict | None:
    p = next((p for p in doc["plugins"] if p.get("type") == "MaterialConfiguratorPlugin"), None)
    if p is None and create:
        p = {"applyOnLoad": True, "variations": [], "type": "MaterialConfiguratorPlugin"}
        doc["plugins"].append(p)
    return p


def variations(doc: dict) -> list[dict]:
    p = configurator(doc)
    return p.get("variations", []) if p else []


def title_taken(doc: dict, title: str) -> bool:
    return any(v.get("title") == title for v in variations(doc))


def usage_of(doc: dict, mat_uuid: str) -> list[dict]:
    return [v for v in variations(doc) if any(m.get("uuid") == mat_uuid for m in v.get("materials") or [])]


def kind_of(m: dict) -> str:
    if m.get("type") == "DiamondMaterial":
        return "Diamond"
    if re.search(r"Standard|Physical", m.get("type", "")):
        return "Metal / PBR"
    return m.get("type", "?")


def is_diamond(m: dict) -> bool:
    return m.get("type") == "DiamondMaterial"


def find_by_name(doc: dict, name: str) -> list[dict]:
    return [m for m in materials(doc).values() if m.get("name") == name]


def unique_title(doc: dict, base: str) -> str:
    t, i = base, 2
    while title_taken(doc, t):
        t, i = f"{base}-{i}", i + 1
    return t


def _variation(title: str, mat_uuid: str | None) -> dict:
    return {"uuid": title, "title": title, "preview": "generate:sphere",
            "materials": [{"uuid": mat_uuid, "resource": "materials"}] if mat_uuid else [],
            "regex": True, "selectedIndex": 0 if mat_uuid else None}


# ---------- operations ----------

def template_for(doc: dict, kind: str) -> dict:
    allm = list(materials(doc).values())
    if kind == "diamond":
        t = next((m for m in allm if is_diamond(m) and m.get("color") == 0xFFFFFF and "dmat" in (m.get("name") or "")), None) \
            or next((m for m in allm if is_diamond(m)), None)
    else:
        t = next((m for m in allm if m.get("type") == "MeshStandardMaterial2" and m.get("metalness") == 1
                  and "whitegold" in (m.get("name") or "")), None) \
            or next((m for m in allm if m.get("type") == "MeshStandardMaterial2" and m.get("metalness") == 1), None)
    return t or BUILTIN[kind]


def create_material(doc: dict, name: str, kind: str, color: int, register: bool = True,
                    title: str | None = None) -> str:
    m = copy.deepcopy(template_for(doc, kind))
    u = new_uuid()
    keep = {k: m["userData"][k] for k in ("gltfExtensions", "separateEnvMapIntensity") if k in (m.get("userData") or {})}
    m["uuid"], m["name"], m["color"] = u, name, int(color)
    m["userData"] = {**keep, "label": name, "cloneId": "0_1", "cloneCount": 0, "uuid": u}
    materials(doc)[u] = m
    if register:
        configurator(doc, create=True)["variations"].append(_variation(title or name, u))
    return u


def clone_material(doc: dict, mat_uuid: str) -> str:
    src = materials(doc)[mat_uuid]
    base = (src.get("name") or "material") + "-copy"
    name = unique_title(doc, base)
    u = new_uuid()
    c = copy.deepcopy(src)
    c["uuid"], c["name"] = u, name
    c["userData"] = {**(c.get("userData") or {}), "label": name, "uuid": u}
    materials(doc)[u] = c
    configurator(doc, create=True)["variations"].append(_variation(name, u))
    return u


def rename_material(doc: dict, mat_uuid: str, new_name: str) -> int:
    """Rename; a variation that was 1:1 with the old name follows. Returns variations synced."""
    m = materials(doc)[mat_uuid]
    old = m.get("name")
    if old == new_name:
        return 0
    m["name"] = new_name
    if (m.get("userData") or {}).get("label") == old:
        m["userData"]["label"] = new_name
    synced = 0
    for v in variations(doc):
        mats = v.get("materials") or []
        if v.get("title") == old and len(mats) == 1 and mats[0].get("uuid") == mat_uuid and not title_taken(doc, new_name):
            if v.get("uuid") == v.get("title"):
                v["uuid"] = new_name
            v["title"] = new_name
            synced += 1
    return synced


def delete_materials(doc: dict, uuids) -> None:
    gone = set(uuids)
    cf = configurator(doc)
    if cf:
        keep = []
        for v in cf.get("variations", []):
            had = len(v.get("materials") or [])
            v["materials"] = [x for x in v.get("materials") or [] if x.get("uuid") not in gone]
            if not (had > 0 and not v["materials"]):     # drop variations left pointing at nothing
                keep.append(v)
        cf["variations"] = keep
    for u in gone:
        materials(doc).pop(u, None)


def register_material(doc: dict, mat_uuid: str) -> str:
    t = unique_title(doc, materials(doc)[mat_uuid].get("name") or mat_uuid)
    configurator(doc, create=True)["variations"].append(_variation(t, mat_uuid))
    return t


def register_unlisted(doc: dict) -> int:
    refd = {x.get("uuid") for v in variations(doc) for x in v.get("materials") or []}
    ground = ground_material_uuid(doc)
    todo = [u for u in materials(doc) if u not in refd and u != ground]
    for u in todo:
        register_material(doc, u)
    return len(todo)


def add_variation(doc: dict, title: str, mat_uuid: str | None = None) -> None:
    if title_taken(doc, title):
        raise ValueError(f"A configurator entry called '{title}' already exists")
    configurator(doc, create=True)["variations"].append(_variation(title, mat_uuid))


def rename_variation(doc: dict, var: dict, new_title: str) -> None:
    if new_title != var.get("title") and title_taken(doc, new_title):
        raise ValueError(f"'{new_title}' already exists - titles must be unique")
    if var.get("uuid") == var.get("title"):
        var["uuid"] = new_title
    var["title"] = new_title


def delete_variations(doc: dict, vars_to_drop) -> None:
    ids = {id(v) for v in vars_to_drop}
    cf = configurator(doc)
    if cf:
        cf["variations"] = [v for v in cf.get("variations", []) if id(v) not in ids]


def ground_material_uuid(doc: dict) -> str | None:
    g = next((p for p in doc["plugins"] if p.get("type") == "Ground"), None)
    return ((g or {}).get("material") or {}).get("uuid")


# ---------- standard set ----------

def standard_wanted() -> list[dict]:
    w = [{"name": n, "kind": "metal", "color": c} for n, c in STD_METALS.items()]
    for loc in STD_LOCATIONS:
        for s in STD_SHAPES:
            for cn, c in STD_COLORS.items():
                w.append({"name": f"{loc}-{s}-{cn}", "kind": "diamond", "color": c})
    return w


def standard_plan(doc: dict) -> dict:
    wanted = standard_wanted()
    titles = {v.get("title") for v in variations(doc)}
    return {"add": [x for x in wanted if x["name"] not in titles],
            "skip": [x for x in wanted if x["name"] in titles], "total": len(wanted)}


def apply_standard(doc: dict) -> dict:
    """Idempotent: running it twice adds nothing the second time."""
    plan = standard_plan(doc)
    refd = {x.get("uuid") for v in variations(doc) for x in v.get("materials") or []}
    names = {x["name"] for x in standard_wanted()}
    # unreferenced leftovers carrying a wanted name are invisible in iJewel; replace them
    for u, m in list(materials(doc).items()):
        if m.get("name") in names and u not in refd:
            del materials(doc)[u]
    for x in plan["add"]:
        create_material(doc, x["name"], x["kind"], x["color"], register=True)
    return plan

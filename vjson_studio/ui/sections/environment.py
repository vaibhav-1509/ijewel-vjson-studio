from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel

from ..widgets import Form
from .base import Section


def _plugin(t):
    return lambda d: next(p for p in d["plugins"] if p.get("type") == t)


class EnvironmentSection(Section):
    title = "Environment"
    key = "environment"

    def build(self, lay):
        d = self.ctx.data
        S = d["scene"]
        sc = lambda d: d["scene"]
        tex = d["resources"].get("textures") or {}

        f = Form(self.ctx, "Scene environment & background")
        for k, label in (("environmentIntensity", "Environment intensity"), ("backgroundIntensity", "Background intensity"),
                         ("envMapIntensity", "Env-map intensity")):
            if k in S:
                f.num(sc, k, label)
        if "fixedEnvMapDirection" in S:
            f.bool(sc, "fixedEnvMapDirection", "Fixed env-map direction")
        for k, label in (("environmentRotation", "Environment rotation (deg)"), ("backgroundRotation", "Background rotation (deg)")):
            if isinstance(S.get(k), dict):
                f.vec3(lambda d, k=k: d["scene"][k], label, degrees=True)
        if isinstance(S.get("backgroundColor"), dict):
            f.vec3(lambda d: d["scene"]["backgroundColor"], "Background colour (RGB 0-1)", keys=("r", "g", "b"))

        def tex_select(holder, key, label):
            cb = QComboBox()
            cb.addItem("(none)", None)
            for u, t in tex.items():
                cb.addItem((t.get("name") or u).split("/")[-1][:60], u)
            cur = (holder(d).get(key) or {}).get("uuid")
            cb.setCurrentIndex(max(cb.findData(cur), 0))

            def changed(_i):
                u = cb.currentData()
                self.ctx.mutate(lambda d: holder(d).__setitem__(key, {"uuid": u, "resource": "textures"} if u else None),
                                rebuild=False)
            cb.currentIndexChanged.connect(changed)
            f.form.addRow(label, cb) if holder is sc else None
            return cb

        if "environment" in S:
            tex_select(sc, "environment", "Environment texture")
        if "background" in S:
            tex_select(sc, "background", "Background texture")

        types = {p.get("type") for p in d["plugins"]}
        cards = [f]
        if "SimpleBackgroundEnvUiPlugin2" in types:
            g = _plugin("SimpleBackgroundEnvUiPlugin2")
            e = Form(self.ctx, "Background / environment plugin")
            have = g(d)
            for k, label, kind in (("sceneEnvironmentRotation", "Env rotation (plugin)", "num"),
                                   ("sceneEnvironmentIntensity", "Env intensity (plugin)", "num"),
                                   ("sceneEnvironmentFixedDirection", "Fixed direction", "bool"),
                                   ("tonemapBackground", "Tonemap background", "bool"),
                                   ("tonemapGround", "Tonemap ground", "bool")):
                if k in have:
                    getattr(e, kind)(g, k, label)
            cards.append(e)
        if "Tonemap" in types:
            g = _plugin("Tonemap")
            t = Form(self.ctx, "Tone mapping")
            if "enabled" in g(d):
                t.bool(g, "enabled", "Enabled")
            ext = g(d).get("extension")
            if isinstance(ext, dict):
                ge = lambda d: _plugin("Tonemap")(d)["extension"]
                for k, label in (("exposure", "Exposure"), ("saturation", "Saturation"), ("contrast", "Contrast"),
                                 ("toneMapping", "Tone-mapping mode (4 = ACES)")):
                    if k in ext:
                        t.num(ge, k, label)
            cards.append(t)
        if "Ground" in types:
            g = _plugin("Ground")
            gr = Form(self.ctx, "Ground")
            have = g(d)
            for k, label, kind in (("visible", "Visible", "bool"), ("size", "Size", "num"), ("yOffset", "Y offset", "num"),
                                   ("bakedShadows", "Baked shadows", "bool"), ("groundReflection", "Reflection", "bool")):
                if k in have:
                    getattr(gr, kind)(g, k, label)
            cards.append(gr)
        if "Diamond" in types:
            g = _plugin("Diamond")
            dm = Form(self.ctx, "Gem environment map")
            if "envMap" in g(d):
                cb = tex_select(g, "envMap", "")
                dm.form.addRow("Diamond env texture", cb)
            if "forceSceneEnvMap" in g(d):
                dm.bool(g, "forceSceneEnvMap", "Force scene env map")
            cards.append(dm)
        note = QLabel("Every other effect (bloom, SSAO, lights, vignette...) is in Effects & Plugins. "
                      "HDR/EXR source URLs are in Textures & LUTs.")
        note.setStyleSheet("color:#888")
        lay.addWidget(self.scroll(*cards, note))

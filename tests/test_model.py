import glob
import json
import os
from pathlib import Path

import pytest

from vjson_studio.model import cameras as cam
from vjson_studio.model import jsonio
from vjson_studio.model import materials as mat
from vjson_studio.model.document import Document
from vjson_studio.model.validate import validate

ROOT = Path(__file__).resolve().parents[1]
REAL_VJSON = ROOT / "test.vjson"                      # a real iJewel3D file, kept out of the repo
TEST_VJSON = REAL_VJSON if REAL_VJSON.exists() else ROOT / "tests" / "fixtures" / "sample.vjson"
# more real files, tested when VJSON_SAMPLES points at a folder of them
EXTERNAL = sorted(glob.glob(os.path.join(os.environ["VJSON_SAMPLES"], "**", "*.vjson"), recursive=True)) \
    if os.environ.get("VJSON_SAMPLES") else []
SAMPLES = [TEST_VJSON] + [Path(p) for p in EXTERNAL]


@pytest.fixture
def doc():
    return Document.open(TEST_VJSON)


# ---------- round trip ----------

@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_unedited_save_is_byte_identical(path):
    d = Document.open(path)
    assert d.text().encode("utf-8") == path.read_bytes()


@pytest.mark.parametrize("newline,bom", [("\r\n", False), ("\n", True), ("\r\n", True)])
def test_line_endings_and_bom_survive_a_save(tmp_path, newline, bom):
    text = TEST_VJSON.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\n", newline)
    raw = (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")
    p = tmp_path / "x.vjson"
    p.write_bytes(raw)
    d = Document.open(p)
    d.save()
    assert p.read_bytes() == raw


def test_save_writes_backup_and_same_bytes(tmp_path):
    src = tmp_path / "scene.vjson"
    src.write_bytes(TEST_VJSON.read_bytes())
    d = Document.open(src)
    d.save()
    assert src.read_bytes() == TEST_VJSON.read_bytes()
    assert (tmp_path / "scene.vjson.bak").read_bytes() == TEST_VJSON.read_bytes()


@pytest.mark.parametrize("value,expected", [
    (1e-7, "1e-7"), (0.000001, "0.000001"), (3.975625024199159e-05, "0.00003975625024199159"),
    (1e21, "1e+21"), (1e20, "100000000000000000000"), (1.5, "1.5"), (-0.25, "-0.25"),
    (100.0, "100"), (0.0, "0"), (-0.0, "0"), (5e-324, "5e-324"), (123456.789, "123456.789"),
])
def test_js_number_matches_javascript(value, expected):
    assert jsonio.js_number(value) == expected


def test_reject_non_vjson(tmp_path):
    p = tmp_path / "x.vjson"
    p.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        Document.open(p)


# ---------- cameras ----------

def _orient_error(v):
    o = cam.look_at_orient(cam.xyz(v["position"]), cam.xyz(v["target"]))
    return max([abs(o["quaternion"][k] - v["quaternion"][k]) for k in "xyzw"]
               + [abs(o["up"][k] - v["up"][k]) for k in "xyz"])


@pytest.mark.skipif(not REAL_VJSON.exists(), reason="needs a real iJewel3D test.vjson")
def test_look_at_orient_reproduces_ijewel_exactly():
    # test.vjson #view1 and #view2 were captured at rest in iJewel3D; its values are reproduced
    data = json.loads(REAL_VJSON.read_text(encoding="utf-8"))
    by_name = {v["name"]: v for v in cam.views(data)}
    for name in ("#view1", "#view2"):
        assert _orient_error(by_name[name]) < 1e-12, name


@pytest.mark.skipif(not EXTERNAL, reason="external sample folder not present")
def test_look_at_orient_across_samples():
    # Views fall into three groups: exact look-at (< 1e-12), saved while orbit
    # damping was still settling (~1e-5), and real custom aim/roll (> 1e-3).
    errs = [_orient_error(v) for p in SAMPLES for v in cam.views(json.loads(p.read_text(encoding="utf-8")))]
    exact = [e for e in errs if e < 1e-12]
    assert len(exact) >= 30
    assert not [e for e in errs if 1e-12 <= e < 1e-7], "near-misses suggest a maths error, not drift"


def test_next_view_name_and_make_view(doc):
    assert cam.next_view_name(doc.data) == "#view5"
    v = cam.make_view("#view5", (0, 2, 5), (0, 0, 0))
    assert v["serializableClassId"] == "CameraView" and v["quaternion"]["isQuaternion"]
    assert not cam.has_custom_orientation(v)


def test_look_straight_down_does_not_crash():
    q = cam.look_at_orient((0, 5, 0), (0, 0, 0))["quaternion"]
    assert abs(sum(q[k] ** 2 for k in "xyzw") - 1) < 1e-12


# ---------- materials ----------

def test_create_material_registers_variation(doc):
    u = doc.mutate(lambda d: mat.create_material(d, "mainstone-round-red", "diamond", 0xFAC9C9))
    m = mat.materials(doc.data)[u]
    assert m["uuid"] == u and m["userData"]["uuid"] == u and m["color"] == 0xFAC9C9
    v = mat.usage_of(doc.data, u)
    assert len(v) == 1 and v[0]["title"] == v[0]["uuid"] == "mainstone-round-red"


def test_rename_syncs_one_to_one_title(doc):
    u = mat.create_material(doc.data, "a-name", "metal", 0xE5B377)
    assert mat.rename_material(doc.data, u, "b-name") == 1
    assert mat.title_taken(doc.data, "b-name") and not mat.title_taken(doc.data, "a-name")


def test_delete_drops_orphan_variations(doc):
    u = mat.create_material(doc.data, "temp-mat", "metal", 0)
    mat.delete_materials(doc.data, [u])
    assert u not in mat.materials(doc.data) and not mat.title_taken(doc.data, "temp-mat")


def test_duplicate_variation_title_is_refused(doc):
    with pytest.raises(ValueError):
        mat.add_variation(doc.data, "metal-main")


def test_standard_set_is_idempotent(doc):
    first = mat.apply_standard(doc.data)
    assert first["total"] == 207
    n_mats, n_vars = len(mat.materials(doc.data)), len(mat.variations(doc.data))
    second = mat.apply_standard(doc.data)
    assert second["add"] == []
    assert (len(mat.materials(doc.data)), len(mat.variations(doc.data))) == (n_mats, n_vars)
    titles = [v["title"] for v in mat.variations(doc.data)]
    assert len(titles) == len(set(titles))


def test_hex_helpers():
    assert mat.from_hex("#e5b377") == 0xE5B377 and mat.from_hex("zz") is None
    assert mat.to_hex(0xE5B377) == "#E5B377"


# ---------- undo ----------

def test_undo_redo(doc):
    before = json.dumps(doc.data, sort_keys=True)
    doc.mutate(lambda d: cam.camera_views_plugin(d)["cameraViews"].append(cam.make_view("#x", (1, 1, 1), (0, 0, 0))))
    assert doc.dirty and doc.can_undo()
    doc.undo()
    assert json.dumps(doc.data, sort_keys=True) == before
    doc.redo()
    assert cam.views(doc.data)[-1]["name"] == "#x"


def test_failed_mutation_changes_nothing(doc):
    before = json.dumps(doc.data, sort_keys=True)
    with pytest.raises(ValueError):
        doc.mutate(lambda d: (mat.create_material(d, "zz", "metal", 0), mat.add_variation(d, "zz")))
    assert json.dumps(doc.data, sort_keys=True) == before and not doc.can_undo()


# ---------- validate ----------

def test_validate_runs_and_fixes_apply(doc):
    issues = validate(doc.data)
    for i in issues:
        if i.fix:
            doc.mutate(i.fix)
    assert not [i for i in validate(doc.data) if i.sev == "err"]


# ---------- viewport maths ----------

def test_ground_grid_layout():
    from vjson_studio.viewport import scene_math as sm
    assert [sm.nice_step(x) for x in (0.07, 0.3, 0.9, 1.0, 3.2, 7.0)] == [0.1, 0.5, 1, 1, 5, 10]
    g = sm.ground_grid(6.0, y=-0.6)
    pts, _ = g["x_axis"]
    assert pts[:, 1].tolist() == [-0.6, -0.6] and pts[:, 2].tolist() == [0, 0]       # X axis along x at z=0
    pts, _ = g["z_axis"]
    assert pts[:, 0].tolist() == [0, 0]                                              # Z axis along z at x=0
    assert g["half"] >= 6.0
    n_lines = sum(len(g[k][1]) // 3 for k in ("minor", "major", "x_axis", "z_axis"))
    n = round(g["half"] / g["step"])
    assert n_lines == 2 * (2 * n + 1)                                                # every grid line, once

"""End-to-end: the real window, a real GLB and vjson, driven like a person would.

Screenshots of every section land in tests/_screens/ for review.
"""
import json
import shutil
from pathlib import Path

import pytest

from vjson_studio.model import cameras as cam

ROOT = Path(__file__).resolve().parents[1]
SCREENS = ROOT / "tests" / "_screens"
GLB = ROOT / "ref.glb" if (ROOT / "ref.glb").exists() else ROOT / "tests" / "fixtures" / "sample_ring.glb"
SAMPLE = ROOT / "test.vjson" if (ROOT / "test.vjson").exists() else ROOT / "tests" / "fixtures" / "sample.vjson"


@pytest.fixture
def win(qtbot, tmp_path):
    from vjson_studio.ui.main_window import MainWindow
    src = tmp_path / "scene.vjson"
    shutil.copy(SAMPLE, src)
    w = MainWindow()
    w.settings.setValue("coord_notice_shown", True)      # no modal during the test
    qtbot.addWidget(w)
    w.resize(1600, 950)
    w.show()
    w.open(str(src))
    if GLB.exists():
        w.viewport.load(str(GLB))
    qtbot.wait(200)
    yield w
    w.ctx.doc.dirty = False
    w.close()


def _views(w):
    return cam.views(w.ctx.data)


def test_every_section_opens_without_error(win, qtbot):
    SCREENS.mkdir(exist_ok=True)
    for key in win.sections:
        win.go(key)
        qtbot.wait(80)
        assert win.stack.currentWidget() is win.sections[key]
        win.grab().save(str(SCREENS / f"{key}.png"))
    assert not win.ctx.doc.dirty, "opening sections must not change the file"
    assert win.ctx.doc.text() == SAMPLE.read_text(encoding="utf-8")


@pytest.mark.skipif(not GLB.exists(), reason="ref.glb not present")
def test_add_update_go_undo_save(win, qtbot, tmp_path):
    vp = win.viewport.view
    win.go("cameras")
    cams = win.sections["cameras"]
    n0 = len(_views(win))

    # orbit somewhere new, then capture
    vp.set_camera((3.0, 2.5, 4.0), (0.1, -0.2, 0.0))
    cams.add_from_viewport()
    qtbot.wait(50)
    assert len(_views(win)) == n0 + 1
    v = _views(win)[-1]
    assert v["name"] == f"#view{n0 + 1}"
    assert cam.xyz(v["position"]) == pytest.approx((3.0, 2.5, 4.0))
    assert cam.xyz(v["target"]) == pytest.approx((0.1, -0.2, 0.0))
    o = cam.look_at_orient(cam.xyz(v["position"]), cam.xyz(v["target"]))
    assert all(abs(o["quaternion"][k] - v["quaternion"][k]) < 1e-12 for k in "xyzw")
    assert win.ctx.selected_view == n0

    # update view 1 from a new viewport position: only that view changes
    before = json.dumps(_views(win))
    win.ctx.select_view(0)
    cams.table.select_key(0)
    vp.stop()
    vp.set_camera((-5.0, 1.0, 2.0), (0.0, 0.0, 0.0))
    cams.update_from_viewport()
    after = _views(win)
    assert cam.xyz(after[0]["position"]) == pytest.approx((-5.0, 1.0, 2.0))
    assert json.dumps(after[1:]) == json.dumps(json.loads(before)[1:])

    # go to moves the viewport to the view
    cams.table.select_key(1)
    cams.go_to()
    qtbot.waitUntil(lambda: not vp.animating, timeout=5000)
    assert vp.camera()[0] == pytest.approx(cam.xyz(_views(win)[1]["position"]), abs=1e-6)

    # undo reverts the update, undo again removes the added view
    win.undo()
    assert json.dumps(_views(win)) == before
    win.undo()
    assert len(_views(win)) == n0
    win.redo()
    win.redo()

    # save, reopen: the same views come back (compare values: 3.0 is written as 3, as JavaScript does)
    saved = json.loads(json.dumps(_views(win)))
    assert win.save()
    win.open(str(win.ctx.doc.path))
    assert _views(win) == saved
    assert win.ctx.doc.path.with_suffix(".vjson.bak").exists()


def test_table_edit_reorients_and_follows(win, qtbot):
    win.go("cameras")
    cams = win.sections["cameras"]
    t = cams.table
    cams.table.select_key(0)
    col = [c.label for c in t.cols].index("Pos Y")
    t.item(0, col).setText("4.5")
    v = _views(win)[0]
    assert v["position"]["y"] == 4.5
    o = cam.look_at_orient(cam.xyz(v["position"]), cam.xyz(v["target"]))
    assert abs(o["quaternion"]["w"] - v["quaternion"]["w"]) < 1e-12
    if GLB.exists():
        assert win.viewport.view.camera()[0][1] == pytest.approx(4.5)


def test_material_edit_and_configurator_rules(win, qtbot):
    from vjson_studio.model import materials as mat
    win.go("materials")
    d = win.ctx.data
    u = win.ctx.mutate(lambda d: mat.create_material(d, "mainstone-oval-blue", "diamond", 0xBCE6FE))
    assert mat.title_taken(win.ctx.data, "mainstone-oval-blue")
    # a duplicate title is refused and changes nothing
    before = json.dumps(win.ctx.data, sort_keys=True)
    win.ctx.mutate(lambda d: mat.add_variation(d, "mainstone-oval-blue"))
    assert json.dumps(win.ctx.data, sort_keys=True) == before
    win.undo()
    assert u not in mat.materials(win.ctx.data)

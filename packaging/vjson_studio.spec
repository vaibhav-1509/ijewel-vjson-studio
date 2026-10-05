# PyInstaller spec - build with:  .venv\Scripts\pyinstaller packaging\vjson_studio.spec --noconfirm
# Produces dist\vjson Studio 3D\ (a folder app; the Inno Setup script installs that folder).
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

hidden = (
    collect_submodules("vtkmodules")        # pyvista imports VTK classes lazily, by name
    + collect_submodules("pyvista")
    + ["pyvistaqt", "DracoPy", "pygltflib"]
)
datas = collect_data_files("pyvista") + [("../vjson_studio/resources/icon.png", "vjson_studio/resources")]
binaries = collect_dynamic_libs("DracoPy")

a = Analysis(
    ["launch.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "IPython", "jupyter", "pytest", "trame", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="vjson Studio 3D",
    icon="icon.ico",
    console=False,
    version="version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, name="vjson Studio 3D")

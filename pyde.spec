# PyInstaller build recipe. Run via scripts/build_dmg.sh on macOS, which makes
# dist/Pyde.app, or scripts/build_windows.ps1 on Windows, which makes dist/Pyde.

import sys
from importlib.metadata import version

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

APP_NAME = "Pyde"

a = Analysis(
    ["src/pyde/__main__.py"],
    # The package's non-Python files, plus its metadata so the app can read its
    # own version at runtime.
    datas=collect_data_files("pyde") + copy_metadata("pyde"),
    # QtWebEngine links against Qt Quick, which makes PyInstaller pull in every
    # QML plugin and the ~110 frameworks behind them. Pyde uses no QML, and
    # leaving these bindings out drops about 100 MB from the app.
    excludes=["PySide6.QtQml", "PySide6.QtQuick"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    # On macOS PySide6 ships universal binaries; this strips the unused Intel
    # half. Elsewhere the build is for whatever it runs on.
    target_arch="arm64" if sys.platform == "darwin" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        bundle_identifier="io.github.johnkntran.pyde",
        version=version("pyde"),
        info_plist={"LSMinimumSystemVersion": "14.0"},
    )

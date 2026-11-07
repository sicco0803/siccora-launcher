# PyInstaller-Bauplan fuer den Siccora Launcher (Ordner-Paket, keine Einzel-exe:
# startet schneller und wird seltener von Virenscannern faelschlich gemeldet).
# Aufruf ueber build.ps1.
import os

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.abspath(SPECPATH)
APP = os.path.join(HERE, "..", "app")

a = Analysis(
    [os.path.join(APP, "entry.py")],
    pathex=[APP],
    datas=[(os.path.join(APP, "ui"), "ui")],
    # Legendary und unsere Hintergrund-Module werden teils erst zur Laufzeit geladen
    hiddenimports=collect_submodules("legendary") + collect_submodules("backend") + ["main"],
    excludes=["tkinter", "PIL", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SiccoraLauncher",
    icon=os.path.join(HERE, "siccora.ico"),
    version=os.path.join(HERE, "version_info.txt"),
    console=False,  # Fenster-Anwendung, keine Konsole
    upx=False,      # UPX-Kompression loest haeufig Virenscanner-Fehlalarme aus
)
coll = COLLECT(exe, a.binaries, a.datas, name="SiccoraLauncher", upx=False)

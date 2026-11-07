"""Engines und DevKits starten - mit denselben Startparametern wie der Epic Launcher.

Woher die Startdaten kommen:
  - von Legendary installiert: installed.json (executable + launch_parameters)
  - vom Epic Launcher installiert: dessen .item-Manifeste (LaunchExecutable + LaunchCommand)
  - Engine ohne Angaben: Engine\\Binaries\\Win64\\UnrealEditor.exe
DevKits brauchen ihre Parameter (z. B. ShooterGame.uproject -Installed ...), sonst
oeffnet der Editor ohne Projekt.

Zuletzt Gestartetes merkt sich launches.json (fuer die Startseite).
"""
import glob
import json
import os
import subprocess
import tempfile
import time

from .downloads import BRIDGE, LEGENDARY, NO_WINDOW
from .epic import _load, _save, legendary_dir

HISTORY = "launches.json"
EGL_MANIFESTS = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Epic", "EpicGamesLauncher", "Data",
                             "Manifests")


def _inside(path, root):
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(path)),
                                   os.path.normcase(os.path.abspath(root))]) == os.path.normcase(os.path.abspath(root))
    except ValueError:
        return False


def _from_legendary(app):
    try:
        with open(os.path.join(legendary_dir(), "installed.json"), encoding="utf-8") as f:
            ig = json.load(f).get(app)
    except (OSError, ValueError):
        return None
    if ig and ig.get("executable"):
        return ig["executable"], ig.get("launch_parameters") or ""
    return None


def _from_egl(app):
    for item in glob.glob(os.path.join(EGL_MANIFESTS, "*.item")):
        try:
            with open(item, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if data.get("AppName") == app and data.get("LaunchExecutable"):
            return data["LaunchExecutable"], data.get("LaunchCommand") or ""
    return None


def target(app, install_path):
    """(Programm, Parameter) oder None. Das Programm muss im Installationsordner liegen."""
    found = _from_legendary(app) or _from_egl(app)
    if not found:
        exe = os.path.join("Engine", "Binaries", "Win64", "UnrealEditor.exe")
        found = (exe, "") if os.path.isfile(os.path.join(install_path, exe)) else None
    if not found:
        return None
    exe = os.path.abspath(os.path.join(install_path, found[0]))
    if not _inside(exe, install_path) or not os.path.isfile(exe):
        return None
    return exe, found[1]


def start(app, title, kind, install_path):
    tgt = target(app, install_path)
    if not tgt:
        return False
    exe, params = tgt
    # eine Befehlszeile wie beim Epic Launcher; Arbeitsordner = Installationsordner
    subprocess.Popen(f'"{exe}" {params}'.strip(), cwd=install_path, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    record(app, title, kind)
    return True


# Update-Pruefung uebernimmt die Startseite; ein veraltetes Spiel soll trotzdem starten koennen
LAUNCH_ARGS = ["--skip-version-check"]


def _run(cmd):
    """Befehl ausfuehren. Ausgabe in eine Datei: ein Spiel erbt sonst evtl. die Pipe, und
    wir warteten, bis es beendet wird. -> (Exit-Code, Ausgabe)"""
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    with tempfile.TemporaryFile() as out:
        code = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                              creationflags=NO_WINDOW, timeout=300).returncode
        out.seek(0)
        return code, out.read().decode("utf-8", "replace")


def start_game(app, title, source):
    """Spiele laufen ueber Legendary (Anmeldung beim Spielstart). Vom Epic Launcher Installiertes
    wird dafuer zuerst uebernommen - nur Verwaltungsdaten, keine Spieldateien. -> Fehlertext oder None"""
    if source == "egl":
        code, text = _run(BRIDGE + ["import", app])
        if code != 0:
            return text.strip().splitlines()[-1] if text.strip() else "import failed"
    code, text = _run(LEGENDARY + ["launch", app] + LAUNCH_ARGS)
    if code != 0:
        problems = [line for line in text.splitlines() if "ERROR" in line or "CRITICAL" in line or "FATAL" in line]
        return (problems or text.strip().splitlines() or ["launch failed"])[-1]
    record(app, title, "game")
    return None


def record(app, title, kind):
    hist = [h for h in _load(HISTORY, []) if h.get("appName") != app]
    hist.insert(0, {"appName": app, "title": title, "kind": kind, "time": time.time()})
    _save(HISTORY, hist[:20])


def history():
    return _load(HISTORY, [])

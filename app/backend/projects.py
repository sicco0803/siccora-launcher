"""Unreal-Projekte finden - wie die Projektliste im Epic Launcher.

Quellen (alles nur lesend):
  - zuletzt geoeffnete Projekte aus den Editor-Einstellungen jeder UE-Version
    (%LOCALAPPDATA%\\UnrealEngine\\<Version>\\Saved\\Config\\Windows*\\EditorSettings.ini)
  - Projektordner, in denen Editor bzw. Epic Launcher Projekte angelegt haben
    (CreatedProjectPaths) und "Dokumente\\Unreal Projects"
  - Projekte installierter Engines/DevKits (<Engine>\\Projects\\*)
  - selbst hinzugefuegte Projekte/Ordner und vom Launcher erstellte Projekte (projects.json)

Durchsucht wird je Ordner nur eine Ebene tief (<Ordner>\\<Projekt>\\<Projekt>.uproject),
genau wie der Epic Launcher - ein Laufwerk wird also nie komplett durchkaemmt.
"""
import base64
import glob
import json
import os
import re
import subprocess
import threading
import time
import winreg
from concurrent.futures import ThreadPoolExecutor

from .epic import DATA_DIR, _load, _save

STATE_FILE = "projects.json"  # {"added": [...], "folders": [...], "hidden": [...], "aliases": {...}}
MAX_NAME = 60
LOCAL = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
_RECENT = re.compile(r'^RecentlyOpenedProjectFiles=\(ProjectName="([^"]+)",LastOpenTime=([\d.\-]+)\)', re.I)
_CREATED = re.compile(r"^CreatedProjectPaths=(.+)$", re.I)
_lock = threading.Lock()
_cache = {"time": 0, "items": []}


def _nice(path):
    """Laufwerksbuchstaben gross schreiben (j: -> J:), nur fuer die Anzeige."""
    path = os.path.abspath(path)
    return path[0].upper() + path[1:] if len(path) > 1 and path[1] == ":" else path


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _state():
    s = _load(STATE_FILE, {})
    state = {k: list(s.get(k) or []) for k in ("added", "folders", "hidden")}
    state["aliases"] = dict(s.get("aliases") or {})  # eigene Anzeigenamen: Projektdatei -> Name
    return state


def _read_lines(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _documents():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return os.path.expandvars(winreg.QueryValueEx(k, "Personal")[0])
    except OSError:
        return os.path.join(os.path.expanduser("~"), "Documents")


def _sources():
    """({Schluessel: (uproject, zuletzt geoeffnet als Unix-Zeit)}, zu durchsuchende Ordner)"""
    recent, folders = {}, [os.path.join(_documents(), "Unreal Projects")]
    inis = glob.glob(os.path.join(LOCAL, "UnrealEngine", "*", "Saved", "Config", "Windows*", "EditorSettings.ini"))
    inis += glob.glob(os.path.join(LOCAL, "EpicGamesLauncher", "Saved", "Config", "Windows*", "GameUserSettings.ini"))
    for ini in inis:
        for line in _read_lines(ini):
            m = _RECENT.match(line.strip())
            if m:
                try:
                    ts = time.mktime(time.strptime(m.group(2), "%Y.%m.%d-%H.%M.%S"))
                except ValueError:
                    ts = 0
                k = _key(m.group(1))
                recent[k] = (m.group(1), max(recent.get(k, ("", 0))[1], ts))
                continue
            m = _CREATED.match(line.strip())
            if m:
                folders.append(m.group(1).strip())
    return recent, folders


def _uprojects_in(folder):
    """<Ordner>\\*.uproject und <Ordner>\\<Unterordner>\\*.uproject"""
    found = []
    folder = folder.rstrip("\\/") + os.sep  # "K:" -> "K:\" (sonst aktueller Ordner von K:)
    try:
        with os.scandir(folder) as it:
            entries = list(it)
    except OSError:
        return found
    for e in entries:
        try:
            if e.is_file() and e.name.lower().endswith(".uproject"):
                found.append(e.path)
            elif e.is_dir() and not e.name.startswith(("$", ".")):
                with os.scandir(e.path) as sub:
                    found += [s.path for s in sub if s.name.lower().endswith(".uproject") and s.is_file()]
        except OSError:
            continue
    return found


def _engine_builds():
    """Selbst gebaute/registrierte Engines (DevKits): {GUID: Pfad}, Launcher-Engines: {"5.5": Pfad}"""
    builds, versions = {}, {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Epic Games\Unreal Engine\Builds") as k:
            for i in range(winreg.QueryInfoKey(k)[1]):
                name, value, _ = winreg.EnumValue(k, i)
                builds[name.strip("{}").upper()] = value
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EpicGames\Unreal Engine") as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                ver = winreg.EnumKey(k, i)
                try:
                    with winreg.OpenKey(k, ver) as sub:
                        versions[ver] = winreg.QueryValueEx(sub, "InstalledDirectory")[0]
                except OSError:
                    continue
    except OSError:
        pass
    return builds, versions


def _editor(engine_dir, project_name=None):
    """Editor-Programm der Engine. DevKits bringen oft einen eigenen Editor mit
    (z. B. ShooterGameEditor.exe statt UnrealEditor.exe)."""
    names = ["UnrealEditor.exe", "UE4Editor.exe"] + ([f"{project_name}Editor.exe"] if project_name else [])
    for n in names:
        exe = os.path.join(engine_dir or "", "Engine", "Binaries", "Win64", n)
        if os.path.isfile(exe):
            return exe
    return None


def engine_version(engine_dir):
    """UE-Version einer Engine bzw. eines DevKits ("5.8") aus Engine/Build/Build.version."""
    try:
        with open(os.path.join(engine_dir or "", "Engine", "Build", "Build.version"), encoding="utf-8-sig") as f:
            data = json.load(f)
        return f'{int(data["MajorVersion"])}.{int(data["MinorVersion"])}'
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _resolve_engine(uproject, assoc, engines, builds, versions):
    name = os.path.splitext(os.path.basename(uproject))[0]
    """Welche Engine oeffnet dieses Projekt? -> (Pfad, Anzeigename, appName fuer Fab oder None)"""
    by_path = {_key(e["path"]): e for e in engines if e.get("path")}
    path = None
    if re.fullmatch(r"\d+\.\d+", assoc):
        lib = next((e for e in engines if e["appName"] == f"UE_{assoc}" and e.get("path")), None)
        path = lib["path"] if lib else versions.get(assoc)
    elif assoc:
        path = builds.get(assoc.strip("{}").upper())
    else:
        # leer = Projekt liegt in der Engine selbst (z. B. DevKit\Projects\ShooterGame)
        d = os.path.dirname(os.path.dirname(os.path.abspath(uproject)))
        for _ in range(4):
            if _editor(d, name):
                path = d
                break
            d = os.path.dirname(d)
    lib = by_path.get(_key(path)) if path else None
    if lib:
        label = lib["title"]
    elif re.fullmatch(r"\d+\.\d+", assoc):
        label = f"UE {assoc}"
    elif path:
        label = os.path.basename(path.rstrip("\\/"))
    else:
        label = ""
    fab_engine = f"UE_{assoc}" if re.fullmatch(r"\d+\.\d+", assoc) else None
    return path, label, fab_engine


def _thumbnail(project_dir, name):
    for p in (os.path.join(project_dir, "Saved", "AutoScreenshot.png"), os.path.join(project_dir, f"{name}.png")):
        if os.path.isfile(p):
            return p
    return None


def _created(path):
    try:
        return os.path.getctime(path)  # unter Windows: Anlegezeitpunkt
    except OSError:
        return 0


def _project(uproject, recent, engines, builds, versions, origin):
    try:
        with open(uproject, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    folder = os.path.dirname(os.path.abspath(uproject))
    name = os.path.splitext(os.path.basename(uproject))[0]
    assoc = str(data.get("EngineAssociation") or "")
    engine_path, engine_label, fab_engine = _resolve_engine(uproject, assoc, engines, builds, versions)
    # DevKits haben keine Versionsangabe im Projekt - dann zaehlt die Version der Engine dahinter
    ue_version = assoc if re.fullmatch(r"\d+\.\d+", assoc) else engine_version(engine_path)
    fab_engine = fab_engine or (f"UE_{ue_version}" if ue_version else None)
    try:
        modified = os.path.getmtime(uproject)
    except OSError:
        modified = 0
    return {
        "uproject": _nice(uproject), "dir": _nice(folder), "name": name, "displayName": name,
        "association": assoc, "engine": fab_engine, "ueVersion": ue_version, "engineLabel": engine_label,
        "enginePath": engine_path, "canOpen": bool(_editor(engine_path, name)),
        "lastOpened": recent.get(_key(uproject), ("", 0))[1], "modified": modified,
        "created": _created(uproject),
        "hasThumb": bool(_thumbnail(folder, name)), "origin": origin,
        "description": str(data.get("Description") or "")[:200],
    }


def scan(engines, protected=()):
    """Alle Projekte suchen. engines: installierte Engines/DevKits aus der Bibliothek,
    protected: Ordner installierter Spiele/Engines/DevKits (fuer die Loesch-Sperre)."""
    st = _state()
    recent, folders = _sources()
    folders += st["folders"]
    folders += [os.path.join(e["path"], "Projects") for e in engines if e.get("path")]
    candidates = {}  # Schluessel -> (Pfad, Herkunft)
    for k, (p, _) in recent.items():
        candidates.setdefault(k, (p, "recent"))
    for p in st["added"]:
        candidates.setdefault(_key(p), (p, "added"))
    unique = list(dict.fromkeys(_key(f) for f in folders if f))
    with ThreadPoolExecutor(16) as pool:
        for found in pool.map(_uprojects_in, unique):
            for p in found:
                candidates.setdefault(_key(p), (p, "folder"))
    hidden = {_key(p) for p in st["hidden"]}
    builds, versions = _engine_builds()
    items, hidden_items = [], []
    for k, (p, origin) in candidates.items():
        if not os.path.isfile(p):
            continue
        # Vorlagen und Beispiele innerhalb einer Engine sind keine eigenen Projekte
        low = k.replace("/", "\\")
        if origin == "folder" and any(f"\\{x}\\" in low for x in ("templates", "samples", "featurepacks", "engine")):
            continue
        proj = _project(p, recent, engines, builds, versions, origin)
        if proj:
            proj["deleteBlock"] = block_reason(proj, protected)
            proj["displayName"] = st["aliases"].get(k) or proj["name"]
            (hidden_items if k in hidden else items).append(proj)
    items.sort(key=lambda x: (-(x["lastOpened"] or x["modified"]), x["name"].lower()))
    with _lock:
        _cache.update(time=time.time(), items=items, hidden=hidden_items)
    return items


def cached():
    with _lock:
        return list(_cache["items"])


def targets():
    """Moegliche Ziele fuer Fab-Assets - auch aus der Liste ausgeblendete Projekte (z. B. DevKits)."""
    with _lock:
        return list(_cache["items"]) + list(_cache.get("hidden") or [])


def describe(uproject, engines):
    """Angaben zu einem beliebigen Projekt (auch ausserhalb der Liste)."""
    builds, versions = _engine_builds()
    return _project(uproject, {}, engines, builds, versions, "added")


def find(uproject):
    """Nur Projekte aus der aktuellen Liste - die Oberflaeche darf keine beliebigen Pfade oeffnen."""
    k = _key(uproject or "")
    return next((p for p in cached() if _key(p["uproject"]) == k), None)


def _update_state(field, value, add=True):
    with _lock:
        st = _state()
        keys = {_key(x) for x in st[field]}
        if add and _key(value) not in keys:
            st[field].append(os.path.abspath(value))
        elif not add:
            st[field] = [x for x in st[field] if _key(x) != _key(value)]
        _save(STATE_FILE, st)


def rename(uproject, name):
    """Anzeigename nur fuer den Launcher - Ordner und Projektdatei bleiben unveraendert.
    Leer oder gleich dem echten Namen = Anzeigename entfernen."""
    proj = find(uproject)
    if not proj:
        return False
    name = " ".join(str(name or "").split())[:MAX_NAME]
    key = _key(proj["uproject"])
    with _lock:
        st = _state()
        if name and name != proj["name"]:
            st["aliases"][key] = name
        else:
            st["aliases"].pop(key, None)
        _save(STATE_FILE, st)
        for p in _cache["items"]:
            if _key(p["uproject"]) == key:
                p["displayName"] = name or p["name"]
    return True


def add_project(uproject):
    _update_state("hidden", uproject, add=False)
    _update_state("added", uproject)


def add_folder(folder):
    _update_state("folders", folder)


def hide(uproject):
    _update_state("added", uproject, add=False)
    _update_state("hidden", uproject)


def register_created(target, project_name):
    """Vom Launcher erstelltes Projekt (Fab "Projekt erstellen") in die Liste aufnehmen."""
    folder = os.path.join(target, project_name or "")
    for p in glob.glob(os.path.join(glob.escape(folder), "*.uproject")):
        add_project(p)


def thumbnail(uproject):
    """Vorschaubild als data:-URL (die Oberflaeche kann keine lokalen Dateien laden)."""
    proj = find(uproject)
    path = proj and _thumbnail(proj["dir"], proj["name"])
    if not path or os.path.getsize(path) > 4 * 1024 * 1024:
        return None
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


def open_project(uproject):
    proj = find(uproject)
    if not proj:
        return False
    exe = _editor(proj["enginePath"], proj["name"])
    if exe:
        subprocess.Popen([exe, proj["uproject"]], close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        os.startfile(proj["uproject"])  # Windows fragt ueber den Unreal Version Selector
    return proj


# --- Projekt loeschen ---------------------------------------------------------
# Absichtlich streng: geloescht werden NUR reine Unreal-Projekte einer normalen
# Launcher-Engine ("EngineAssociation": "5.5"). Nie DevKit-/ModKit-Projekte, nie
# etwas in oder um eine Engine/ein installiertes Spiel, nie Laufwerke oder
# Benutzerordner, nie ein Ordner, in dem noch weitere Projekte liegen.
# Geloescht wird in den Papierkorb.

def _inside(path, root):
    try:
        return os.path.commonpath([_key(path), _key(root)]) == _key(root)
    except ValueError:  # anderes Laufwerk
        return False


def _shell_folders():
    home = os.path.expanduser("~")
    out = {home, _documents(), os.path.join(_documents(), "Unreal Projects")}
    for name in ("Desktop", "Downloads", "OneDrive", "Pictures", "Videos", "Music"):
        out.add(os.path.join(home, name))
    for var in ("OneDrive", "USERPROFILE", "PUBLIC", "ProgramFiles", "ProgramFiles(x86)", "ProgramData",
                "SystemRoot", "LOCALAPPDATA", "APPDATA"):
        if os.environ.get(var):
            out.add(os.environ[var])
    return [p for p in out if p]


def _engine_roots(protected):
    builds, versions = _engine_builds()
    return [p for p in list(protected) + list(builds.values()) + list(versions.values()) if p]


def block_reason(proj, protected):
    """Warum dieses Projekt NICHT geloescht werden darf (deutscher Schluessel) - None = erlaubt."""
    if not re.fullmatch(r"\d+\.\d+", proj.get("association") or ""):
        return "Nur reine Unreal-Engine-Projekte können gelöscht werden – keine DevKit- oder ModKit-Projekte."
    d = proj["dir"]
    if os.path.dirname(os.path.abspath(d)) == os.path.abspath(d):
        return "Das Projekt liegt direkt auf einem Laufwerk."
    for root in _engine_roots(protected):
        if _inside(d, root) or _inside(root, d):
            return "Das Projekt liegt in oder um eine installierte Engine, ein DevKit oder ein Spiel."
    for f in _shell_folders():
        if _key(d) == _key(f) or _inside(f, d):
            return "Der Projektordner ist ein geschützter Windows-Ordner."
    # Ordner ohne Engine-Programm darunter (ein Projekt ist keine Engine)
    if _editor(d, proj["name"]) or os.path.isdir(os.path.join(d, "Engine", "Binaries")):
        return "Der Projektordner enthält eine Engine."
    if not (os.path.isdir(os.path.join(d, "Content")) or os.path.isdir(os.path.join(d, "Config"))):
        return "Der Ordner sieht nicht wie ein Unreal-Projekt aus (kein Content- oder Config-Ordner)."
    return None


def delete_info(uproject, protected):
    """Pruefen + Groesse ermitteln (fuer die Rueckfrage). Liest nur."""
    proj = find(uproject)
    if not proj:
        return {"error": "Projekt nicht gefunden."}
    reason = block_reason(proj, protected)
    if reason:
        return {"blocked": reason}
    root = proj["dir"]
    size = files = 0
    others = []
    for cur, dirs, names in os.walk(root):
        for n in names:
            p = os.path.join(cur, n)
            if n.lower().endswith(".uproject") and _key(p) != _key(proj["uproject"]):
                others.append(p)
            try:
                size += os.path.getsize(p)
            except OSError:
                pass
            files += 1
    if others:
        return {"blocked": "Im Projektordner liegen weitere Projekte – zum Schutz wird nicht gelöscht.",
                "others": [_nice(p) for p in others[:10]]}
    try:
        top = sorted(os.listdir(root))
    except OSError:
        top = []
    return {"name": proj["name"], "displayName": proj.get("displayName") or proj["name"], "dir": root, "engineLabel": proj["engineLabel"],
            "sizeMb": round(size / 1048576, 1), "files": files, "top": top[:20], "topMore": max(0, len(top) - 20)}


def _recycle(path):
    """Ordner in den Papierkorb verschieben (Windows-Shell). Passt er nicht hinein,
    fragt Windows selbst nach, ob endgueltig geloescht werden soll."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_WANTNUKEWARNING = 3, 0x4, 0x10, 0x40, 0x4000
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=os.path.abspath(path) + "\0\0",
                         fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_WANTNUKEWARNING)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc == 0 and not op.fAnyOperationsAborted


def delete(uproject, protected):
    """Projektordner in den Papierkorb. Alle Pruefungen laufen hier noch einmal."""
    info = delete_info(uproject, protected)
    if "error" in info or "blocked" in info:
        return info
    root = info["dir"]
    # Geoeffnetes Projekt (Editor haelt Dateien) erkennen: Umbenennen klappt dann nicht
    probe = root + ".siccora-check"
    try:
        os.rename(root, probe)
        os.rename(probe, root)
    except OSError:
        if os.path.isdir(probe) and not os.path.exists(root):
            os.rename(probe, root)
        return {"blocked": "Das Projekt ist gerade geöffnet oder Dateien sind gesperrt – bitte den Editor schließen."}
    if not _recycle(root) or os.path.exists(root):
        return {"error": "Löschen abgebrochen oder fehlgeschlagen."}
    _update_state("added", uproject, add=False)
    with _lock:
        _cache["items"] = [p for p in _cache["items"] if _key(p["uproject"]) != _key(uproject)]
    return {"ok": True, "sizeMb": info["sizeMb"]}


def engine_use(engines):
    """{Engine-Ordner (normcase): zuletzt geoeffnet} aus der Editor-Historie - auch fuer
    ausgeblendete Projekte, denn hier geht es darum, welche Engine/welches DevKit genutzt wurde."""
    recent, _ = _sources()
    builds, versions = _engine_builds()
    use = {}
    for _, (path, ts) in recent.items():
        if not ts or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as f:
                assoc = str((json.load(f) or {}).get("EngineAssociation") or "")
        except (OSError, ValueError, AttributeError):
            continue
        engine_path = _resolve_engine(path, assoc, engines, builds, versions)[0]
        if engine_path:
            k = _key(engine_path)
            use[k] = max(use.get(k, 0), ts)
    return use

"""Stand einer Installation vollstaendig und sicher an den Epic Launcher melden.

Hintergrund (Vorfall 14.11.2026): Legendarys eigener Export schreibt die gewaehlten Komponenten nur
als "InstallTags". Der heutige Epic Launcher liest die Auswahl aber aus "InstallComponents" (interne
IDs) - die blieben leer. Beim naechsten Update im Epic Launcher galt dann "nur Grundpaket", und er
hat alle optionalen Karten eines DevKits geloescht. Ausserdem fehlten Version und Dateiliste in
seinen Feldern, und ein altes, abgebrochenes Update stand noch als "ausstehend" drin.

Darum hier, nach Legendarys Export:
  - InstallComponents: die bisherige Auswahl des Epic Launchers bleibt erhalten; passt unsere
    Auswahl zu einer, die der Epic Launcher selbst schon einmal benutzt hat (aus seinen
    Protokollen gelernt), wird genau diese eingetragen
  - CompleteVersion / CompleteManifestPath auf den neuen Stand, kein "ausstehendes" Update mehr
  - LauncherInstalled.dat (Sammelliste) mit der neuen Version
  - vorher eine Sicherung aller geaenderten Dateien
Laeuft der Epic Launcher, wird NICHTS geschrieben - er wuerde seinen alten Stand beim Beenden
zurueckschreiben. Dann meldet der Aufrufer es spaeter erneut.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time

PROGRAMDATA = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
ITEMS_DIR = os.path.join(PROGRAMDATA, "Epic", "EpicGamesLauncher", "Data", "Manifests")
PENDING_DIR = os.path.join(ITEMS_DIR, "Pending")
INSTALLED_DAT = os.path.join(PROGRAMDATA, "Epic", "UnrealEngineLauncher", "LauncherInstalled.dat")
EGL_SAVED = os.path.join(os.environ.get("LOCALAPPDATA", ""), "EpicGamesLauncher", "Saved")
BACKUP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SiccoraLauncher", "egl-backup")

RE_COMPONENTS = re.compile(r"BinaryId \[[0-9a-f]+:[0-9a-f]+:([0-9A-Za-z_.\-]+):[^\]]*\] .{1,3} using validated components: \[([^\]]*)\]")
RE_TAGS = re.compile(r"BinaryId \[[0-9a-f]+:[0-9a-f]+:([0-9A-Za-z_.\-]+):[^\]]*\] .{1,3} resolved tags: \[([^\]]*)\]")


def egl_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EpicGamesLauncher.exe", "/NH"], capture_output=True,
                             text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # im Zweifel annehmen, er laeuft -> nichts schreiben
    return "epicgameslauncher.exe" in out.lower()


def valid_guid(guid):
    """Kennungen des Epic Launchers sind immer 32 Hex-Zeichen. Alles andere (z. B. "..\\x" in einer
    manipulierten Datei unter ProgramData) wird nie zu einem Dateipfad zusammengesetzt."""
    return bool(re.fullmatch(r"[0-9A-Fa-f]{32}", str(guid or "")))


def _tagset(tags):
    return frozenset(t.strip() for t in tags if t and t.strip())


STORE = os.path.join(os.path.dirname(BACKUP_DIR), "egl_components.json")


def learned_components(app_name, saved_dir=EGL_SAVED, store=None):
    """[(Komponenten-IDs, Tags)] - welche Auswahl der Epic Launcher fuer diese App schon benutzt hat.
    Gelernt aus seinen Protokollen ("using validated components" + "resolved tags") und dauerhaft
    gemerkt - seine Protokolle werden nach einer Weile geloescht."""
    store = store or STORE
    try:
        with open(store, encoding="utf-8") as f:
            known = json.load(f)
    except (OSError, ValueError):
        known = {}
    pairs = [(list(c), _tagset(t)) for c, t in known.get(app_name, [])]
    before = len(pairs)
    files = glob.glob(os.path.join(saved_dir, "Logs", "*.log")) + \
        glob.glob(os.path.join(saved_dir, "Crashes", "*", "*.log"))
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        pending = None
        for line in text.splitlines():
            m = RE_COMPONENTS.search(line)
            if m and m.group(1) == app_name:
                pending = [c.strip() for c in m.group(2).split(",") if c.strip()]
                continue
            m = RE_TAGS.search(line)
            if m and m.group(1) == app_name and pending is not None:
                pair = (pending, _tagset(m.group(2).split(",")))
                if pair not in pairs:
                    pairs.append(pair)
                pending = None
    if len(pairs) > before:
        known[app_name] = [[c, sorted(t)] for c, t in pairs]
        try:
            os.makedirs(os.path.dirname(store), exist_ok=True)
            _write(store, known)
        except OSError:
            pass
    return pairs


def remember_all(saved_dir=EGL_SAVED, items_dir=ITEMS_DIR):
    """Fuer alle Installationen des Epic Launchers seine Auswahl merken, solange die Protokolle noch da sind."""
    for path in glob.glob(os.path.join(items_dir, "*.item")):
        try:
            app = _read(path).get("AppName")
        except (OSError, ValueError):
            continue
        if app:
            learned_components(app, saved_dir)


def choose_components(app_name, our_tags, previous, saved_dir=EGL_SAVED):
    """Welche InstallComponents eingetragen werden. -> (Liste, Begruendung)"""
    wanted = _tagset(our_tags)
    for comps, tags in learned_components(app_name, saved_dir):
        if tags == wanted:
            return comps, "aus der Auswahl des Epic Launchers"
    if previous:
        return list(previous), "bisherige Auswahl des Epic Launchers beibehalten"
    return [], "keine bekannte Auswahl"


def egl_is_newer(app_name, version, install_path, lgd_dir, items_dir=ITEMS_DIR):
    """Hat der Epic Launcher fuer dieselbe Installation einen anderen, spaeter geschriebenen Stand?"""
    path = find_item(app_name, items_dir)
    if not path:
        return False
    try:
        item = _read(path)
    except (OSError, ValueError):
        return False
    if not item.get("AppVersionString") or item["AppVersionString"] == version:
        return False
    if os.path.normcase(os.path.abspath(item.get("InstallLocation") or "")) != os.path.normcase(os.path.abspath(install_path)):
        return False
    ours = glob.glob(os.path.join(lgd_dir, "manifests", f"{glob.escape(app_name)}_*_{glob.escape(version)}.manifest"))
    ours_time = max((os.path.getmtime(f) for f in ours), default=0)
    return os.path.getmtime(path) > ours_time


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, data):
    tmp = path + ".siccora-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)


def find_item(app_name, items_dir=ITEMS_DIR):
    for path in glob.glob(os.path.join(items_dir, "*.item")):
        try:
            if _read(path).get("AppName") == app_name:
                return path
        except (OSError, ValueError):
            continue
    return None


def snapshot(app_name, items_dir=ITEMS_DIR):
    """Stand VOR Legendarys Export (dessen Export ueberschreibt die Komponenten)."""
    path = find_item(app_name, items_dir)
    if not path:
        return {}
    try:
        return _read(path)
    except (OSError, ValueError):
        return {}


def _backup(paths, backup_dir=BACKUP_DIR):
    target = os.path.join(backup_dir, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(target, exist_ok=True)
    for p in paths:
        if p and os.path.isfile(p):
            shutil.copy2(p, os.path.join(target, os.path.basename(p)))
    return target


EGI_DIR = os.path.join(PROGRAMDATA, "Epic", "EpicOnlineServicesShared", "InstallHelper", "InstalledItems")
EMPTY_MANIFEST_DATA = {"version": "", "launchCommand": "", "launchExe": "", "prereqSHA1Hash": "", "buildSize": 0}


def update_egi(guid, version, tags, egi_dir=EGI_DIR, backup_dir=BACKUP_DIR, log=print, install_path=None):
    """Das eigentliche Gedaechtnis des Epic Launchers (Install-Helfer, *.egi): Version, gewaehlte
    Komponenten (hier direkt als Tags) und kein halbfertiges Update mehr. Ohne diesen Schritt
    "setzt" er alte Updates fort oder aktualisiert mit leerer Auswahl - und loescht dabei Karten."""
    if not valid_guid(guid):
        return False
    path = os.path.join(egi_dir, f"{guid}.egi")
    if not os.path.isfile(path):
        return False
    data = _read(path)
    info = data.get("v4")
    if not isinstance(info, dict):
        log("EGL_SYNC unbekanntes Format des Install-Helfers - nicht angefasst")
        return False
    _backup([path], backup_dir)
    revisions = []
    for other in glob.glob(os.path.join(egi_dir, "*.egi")):
        try:
            revisions.append(int(str(_read(other).get("v4", {}).get("revision", "0")), 16))
        except (OSError, ValueError):
            continue
    info["state"] = "Installed"
    info["tags"] = [""] + sorted({t for t in tags if t})
    info["pendingTags"] = []
    info["stagedVersion"] = ""
    info["manifestData"] = {**(info.get("manifestData") or EMPTY_MANIFEST_DATA), "version": version}
    info["pendingManifestData"] = dict(EMPTY_MANIFEST_DATA)
    if install_path:  # z. B. nach dem Verschieben: alle Pfade auf den neuen Ort
        meta = os.path.join(install_path, ".egstore")
        info["dir"] = install_path
        info["metaDir"] = meta
        info["manifestPath"] = os.path.join(meta, f"{guid}.manifest")
        info["pendingManifestPath"] = os.path.join(meta, "Pending", f"{guid}.manifest")
    width = len(str(info.get("revision") or "")) or 32
    info["revision"] = format(max(revisions, default=0) + 1, f"0{width}X")
    _write(path, data)
    log(f"EGL_SYNC Install-Helfer: {version}, {len(info['tags']) - 1} optionale Komponenten, nichts ausstehend")
    return True


def needs_sync(app_name, version, install_path, tags, lgd_dir, items_dir=ITEMS_DIR, egi_dir=EGI_DIR):
    """Kennt der Epic Launcher diese Installation mit falschem Stand (andere Version, andere Auswahl,
    halbfertiges Update)? Nur wenn UNSER Stand der neuere ist - hat der Epic Launcher zuletzt selbst
    etwas geaendert, gilt seiner (den uebernimmt der Launcher vor dem naechsten Auftrag)."""
    item_path = find_item(app_name, items_dir)
    if not item_path:
        return False
    try:
        item = _read(item_path)
    except (OSError, ValueError):
        return False
    if os.path.normcase(os.path.abspath(item.get("InstallLocation") or "")) != os.path.normcase(os.path.abspath(install_path)):
        return False
    guid = item.get("InstallationGuid") or ""
    if not valid_guid(guid):
        return False
    egi_path = os.path.join(egi_dir, f"{guid}.egi")
    ours = glob.glob(os.path.join(lgd_dir, "manifests", f"{glob.escape(app_name)}_*_{glob.escape(version)}.manifest"))
    ours_time = max((os.path.getmtime(f) for f in ours), default=0)
    theirs_time = os.path.getmtime(egi_path) if os.path.isfile(egi_path) else os.path.getmtime(item_path)
    wanted = _tagset(tags)
    if os.path.isfile(egi_path):
        try:
            info = _read(egi_path).get("v4") or {}
        except (OSError, ValueError):
            info = {}
        wrong = info.get("state") != "Installed" or (info.get("manifestData") or {}).get("version") != version \
            or _tagset(info.get("tags") or []) != wanted or (info.get("pendingManifestData") or {}).get("version")
    else:
        wrong = item.get("AppVersionString") != version or bool(item.get("PendingManifestPath"))
    wrong = wrong or os.path.isfile(os.path.join(items_dir, "Pending", f"{guid}.item"))
    return bool(wrong) and ours_time >= theirs_time


def finish_export(app_name, version, install_path, our_tags, previous, items_dir=ITEMS_DIR, installed_dat=INSTALLED_DAT,
                  saved_dir=EGL_SAVED, backup_dir=BACKUP_DIR, log=print, egi_dir=EGI_DIR):
    """Nach Legendarys egl_export: die Felder setzen, die der Epic Launcher wirklich benutzt."""
    item_path = find_item(app_name, items_dir)
    if not item_path:
        log("EGL_SYNC kein Eintrag beim Epic Launcher")
        return False
    item = _read(item_path)
    guid = item.get("InstallationGuid") or os.path.splitext(os.path.basename(item_path))[0]
    if not valid_guid(guid):
        log("EGL_SYNC unerwartete Kennung im Eintrag des Epic Launchers - nichts geschrieben")
        return False
    egstore = os.path.join(install_path, ".egstore")
    manifest = os.path.join(egstore, f"{guid}.manifest")
    pending_manifest = os.path.join(egstore, "Pending", f"{guid}.manifest")
    pending_item = os.path.join(items_dir, "Pending", f"{guid}.item")
    _backup([item_path, installed_dat, pending_item], backup_dir)

    comps, why = choose_components(app_name, our_tags, previous.get("InstallComponents") or [], saved_dir)
    item["InstallComponents"] = comps
    item["AppVersionString"] = version
    if os.path.isfile(manifest):
        item["CompleteVersion"] = version
        item["CompleteManifestPath"] = manifest
    item["PendingManifestPath"] = ""
    item["bIsIncompleteInstall"] = False
    item["bNeedsValidation"] = False
    _write(item_path, item)
    log(f"EGL_SYNC Komponenten: {len(comps)} ({why})")
    update_egi(guid, version, our_tags, egi_dir, backup_dir, log, install_path=install_path)

    # ein altes, abgebrochenes Update des Epic Launchers wuerde er sonst "fortsetzen"
    for stale in (pending_item, pending_manifest):
        if os.path.isfile(stale):
            moved = os.path.join(backup_dir, "pending-" + time.strftime("%Y%m%d-%H%M%S") + "-" + os.path.basename(stale))
            os.makedirs(backup_dir, exist_ok=True)
            shutil.move(stale, moved)
            log(f"EGL_SYNC altes ausstehendes Update beiseitegelegt: {os.path.basename(stale)}")

    try:
        dat = _read(installed_dat)
        changed = False
        for e in dat.get("InstallationList", []):
            if e.get("AppName") == app_name:
                if e.get("AppVersion") != version:
                    e["AppVersion"] = version
                    changed = True
                if os.path.normcase(os.path.abspath(e.get("InstallLocation") or "")) != os.path.normcase(os.path.abspath(install_path)):
                    e["InstallLocation"] = install_path  # verschoben
                    changed = True
        if changed:
            _write(installed_dat, dat)
            log("EGL_SYNC Sammelliste aktualisiert")
    except (OSError, ValueError) as e:
        log(f"EGL_SYNC Sammelliste nicht aktualisiert: {e}")
    return True

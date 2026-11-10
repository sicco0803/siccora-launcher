"""Speicher aufraeumen: nur Ordner, die Unreal selbst wieder erzeugt oder die reine Protokolle sind.

Bewusst nicht dabei: Autosaves, Config, Content, Intermediate, Binaries. Liegt ein Projekt in einer
installierten Engine oder einem DevKit, bleibt jede Datei aus Epics Dateiliste unangetastet; laesst
sich die Liste nicht lesen, wird das Projekt gar nicht angeboten.

Geloescht wird nur, was der letzte Suchlauf gefunden hat (die Oberflaeche uebergibt nur dessen IDs).
"""
import gc
import os
import re
import subprocess

# id -> Unterordner des Projekts
CATEGORIES = {
    "logs": ["Saved/Logs"],
    "crashes": ["Saved/Crashes"],
    "worldpartition": ["Saved/WorldPartition"],
    "shaderdebug": ["Saved/ShaderDebugInfo"],
    "materialstats": ["Saved/MaterialStats", "Saved/MaterialStatsDebug"],
    "ddc": ["DerivedDataCache"],
}
# liegen direkt im DevKit-Ordner, nicht im Projekt (lokale Cooks der ARK-DevKits)
KIT_CATEGORIES = {"localcook": ["ModTools/Output"]}
MIN_BYTES = 10 * 1024 * 1024  # Kleinkram wuerde die Liste nur fuellen
RE_EDITOR = re.compile(r"^\"?(UnrealEditor|UE4Editor|UE5Editor|[A-Za-z0-9_]*GameEditor)(-[A-Za-z0-9_-]+)?\.exe\"?", re.I | re.M)
_found = {}  # letzter Suchlauf: id -> {"root", "folders", "protected", "bytes", "project", "category"}
# Live-Stand fuer die Oberflaeche (wird waehrend scan/clean aus einem zweiten Aufruf gelesen)
progress = {"phase": "", "done": 0, "total": 0, "project": "", "category": "", "files": 0, "step": ""}


def _progress(**kw):
    progress.update(kw)


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _inside(path, root):
    try:
        return os.path.commonpath([_key(path), _key(root)]) == _key(root)
    except ValueError:  # anderes Laufwerk
        return False


def _is_link(path):
    return os.path.islink(path) or os.path.isjunction(path)


def _files(folder):
    """Alle Dateien unterhalb - ohne Verknuepfungen zu folgen (sonst liefe das Loeschen aus dem Ordner heraus)."""
    if not os.path.isdir(folder) or _is_link(folder):
        return
    for cur, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not _is_link(os.path.join(cur, d))]
        for name in names:
            yield os.path.join(cur, name)


def editor_running():
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    return bool(RE_EDITOR.search(out))


def kit_projects(root):
    """Projekte, die in einer Engine oder einem DevKit liegen (z. B. Projects/ShooterGame)."""
    found = []
    for parent in (root, os.path.join(root, "Projects")):
        try:
            subdirs = [e.path for e in os.scandir(parent) if e.is_dir()]
        except OSError:
            continue
        for sub in subdirs:
            try:
                project = next((f for f in os.listdir(sub) if f.lower().endswith(".uproject")), None)
            except OSError:
                continue
            if project:
                found.append({"dir": sub, "name": project[:-9], "displayName": project[:-9]})
    return found


def _protected_names(manifest, root, project_dir, subs):
    """Dateien in den Zielordnern (kleingeschrieben, relativ zum Projekt), die Epic mitgeliefert hat."""
    base = os.path.relpath(project_dir, root).replace("\\", "/").lower()
    base = "" if base == "." else base + "/"
    prefixes = tuple(base + s.lower() + "/" for s in subs)
    return {name[len(base):] for name in (f.filename.replace("\\", "/").lower() for f in manifest.file_manifest_list.elements)
            if name.startswith(prefixes)}


def scan(projects, installs, load_manifest, kits=()):
    """projects: [{dir, name, displayName}], kits: dasselbe fuer Engine-/DevKit-Ordner,
    installs: {appName: Ordner}, load_manifest(appName) -> Manifest oder None."""
    _found.clear()
    items, seen = [], set()
    _progress(phase="scan", done=0, total=0, project="", category="", files=0, step="")
    manifests = {}  # je Installation nur einmal laden: grosse DevKits haben ueber eine Million Eintraege

    def manifest_of(app):
        if app not in manifests:
            manifests[app] = load_manifest(app)
        return manifests[app]

    targets = [(p, CATEGORIES) for p in projects] + [(k, KIT_CATEGORIES) for k in kits]
    _progress(total=len(targets))
    for n, (proj, categories) in enumerate(targets):
        folder = proj["dir"]
        _progress(done=n, project=proj.get("displayName") or proj["name"], category="", step="")
        mark = (_key(folder), categories is KIT_CATEGORIES)
        if mark in seen or not os.path.isdir(folder):
            continue
        seen.add(mark)
        subs_all = [s for subs in categories.values() for s in subs]
        if not any(os.path.isdir(os.path.join(folder, *s.split("/"))) for s in subs_all):
            continue
        protected = set()
        # bei mehreren Treffern (Plugins teilen sich den Engine-Ordner) gibt es je Ordner nur eine Dateiliste
        owners = sorted((a for a, p in installs.items() if _inside(folder, p)), key=len)
        if owners:
            _progress(step="manifest")  # grosse DevKits: das dauert
            manifest = manifest_of(owners[0])
            if manifest is None:
                continue  # ohne Dateiliste nichts anbieten
            protected = _protected_names(manifest, installs[owners[0]], folder, subs_all)
        for cat, subs in categories.items():
            _progress(category=cat, step="measure")
            folders = [os.path.join(folder, *s.split("/")) for s in subs]
            size = count = 0
            for path in folders:
                for f in _files(path):
                    if os.path.relpath(f, folder).replace("\\", "/").lower() in protected:
                        continue
                    try:
                        size += os.path.getsize(f)
                        count += 1
                    except OSError:
                        pass
            if size < MIN_BYTES:
                continue
            ident = f"{len(_found)}-{cat}"
            _found[ident] = {"root": folder, "folders": folders, "protected": protected, "bytes": size,
                             "project": proj.get("displayName") or proj["name"], "category": cat}
            items.append({"id": ident, "project": proj.get("displayName") or proj["name"], "dir": folder,
                          "category": cat, "mb": size / 1048576, "files": count})
    manifests.clear()
    gc.collect()
    _progress(phase="", done=len(targets))
    return {"items": items, "editorRunning": editor_running()}


def clean(ids):
    """Geloeschte Groesse, Dateien und uebersprungene (gesperrte) Dateien. Endgueltig, kein Papierkorb."""
    if editor_running():
        return {"blocked": True}
    freed = files = skipped = 0
    entries = [e for e in (_found.pop(i, None) for i in ids) if e]
    done = 0  # Bytes, ob geloescht oder uebersprungen - fuer den Balken
    _progress(phase="clean", done=0, total=sum(e["bytes"] for e in entries), files=0, step="")
    for entry in entries:
        _progress(project=entry["project"], category=entry["category"])
        root = entry["root"]
        for folder in entry["folders"]:
            if not _inside(folder, root):
                continue
            for f in list(_files(folder)):
                if os.path.relpath(f, root).replace("\\", "/").lower() in entry["protected"]:
                    continue
                size = 0
                try:
                    size = os.path.getsize(f)
                    os.remove(f)
                    freed += size
                    files += 1
                except OSError:  # gerade in Benutzung
                    skipped += 1
                done += size
                _progress(done=done, files=files)
            if os.path.isdir(folder) and not _is_link(folder):
                for cur, dirs, names in os.walk(folder, topdown=False):
                    for d in dirs:
                        path = os.path.join(cur, d)
                        if not _is_link(path):
                            try:
                                os.rmdir(path)  # nur leere Unterordner
                            except OSError:
                                pass
    _progress(phase="", done=progress["total"])
    return {"freedMb": freed / 1048576, "files": files, "skipped": skipped}

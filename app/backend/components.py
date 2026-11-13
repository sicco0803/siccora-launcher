"""Optionale Komponenten (z. B. DLC-Maps, Hi-Res-Texturen) - wie "Optionen" im Epic Launcher.

analyse() liest nur. Die Dateien werden nach ihrer Komponenten-Kombination
gruppiert (viele Dateien gehoeren zu mehreren Komponenten). Daraus kann die
Oberflaeche fuer jede Auswahl exakt berechnen:
  - Download = fehlende Dateien aller Gruppen, die eine gewaehlte Komponente beruehren
               (plus fehlende Basisdateien - Legendary ergaenzt die mit)
  - frei     = vorhandene Dateien aller Gruppen, die eine JETZT ABGEWAEHLTE Komponente
               beruehren und keine gewaehlte. Dateien von Komponenten, die nie gewaehlt
               waren (z. B. einzelne Android-Dateien einer Engine), bleiben unangetastet.
Geloescht wird spaeter genau nach dieser Regel (egl_bridge.py prune).

Bei DevKits dauert die Pruefung (1,7 Mio. Dateien) bis zu 2 Minuten - das
Ergebnis wird deshalb je Element gespeichert und erst neu berechnet, wenn sich
Version, Ordner oder Auswahl geaendert haben, nach jeder Aenderung ueber den
Launcher (im Hintergrund) oder auf Wunsch ("Neu pruefen").
"""
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .epic import DATA_DIR, _load, _save, write_json
from .i18n import tr
from .preview import _installed_manifest

CACHE_DIR = os.path.join(DATA_DIR, "components")
_running = threading.Lock()  # nie zwei Pruefungen gleichzeitig (Platte + Arbeitsspeicher)


def _cache_path(app_name):
    return os.path.join(CACHE_DIR, f"{app_name}.json")


def _fingerprint(service, app_name, local):
    """Woran man erkennt, dass der gespeicherte Stand noch gilt."""
    tags = None
    if local["source"] == "legendary":
        igame = service.core.lgd.get_installed_game(app_name)
        tags = sorted(t for t in (igame.install_tags or []) if t)
    return {"path": local["path"], "version": local["version"], "source": local["source"], "tags": tags}


def refresh_options(service):
    """Im Hintergrund: welche installierten Engines/DevKits ueberhaupt optionale Inhalte haben.
    Ergebnis je Version in options.json - die Oberflaeche zeigt "Optionen" nur, wo es etwas gibt.
    Liest nur die installierte Dateiliste (kein Netz, keine Pruefung der Platte)."""
    if not _running.acquire(blocking=False):
        return  # laeuft gerade eine Komponenten-Pruefung - beim naechsten Mal
    try:
        known = _load("options.json", {})
        installed = service.installed()
        for item in service.library()["items"]:
            local = installed.get(item["appName"])
            if item["kind"] not in ("engine", "tool") or not local:
                continue
            if known.get(item["appName"], {}).get("version") == local["version"]:
                continue
            try:
                manifest = _installed_manifest(service, item["appName"], local)
            except Exception:
                manifest = None
            if manifest is None:
                continue  # unbekannt lassen -> Button bleibt sichtbar
            has = any(fm.install_tags for fm in manifest.file_manifest_list.elements)
            del manifest
            known[item["appName"]] = {"version": local["version"], "has": has}
            _save("options.json", known)
    finally:
        _running.release()


def forget(app_name):
    try:
        os.remove(_cache_path(app_name))
    except OSError:
        pass


def analyse(service, app_name, refresh=False):
    local = service.installed().get(app_name)
    if not local:
        forget(app_name)
        return {"error": tr("Nicht installiert.")}
    service.core.lgd._installed = None  # Download-Prozesse schreiben installed.json - frisch lesen
    fp = _fingerprint(service, app_name, local)
    if not refresh:
        try:
            with open(_cache_path(app_name), encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("fingerprint") == fp:
                cached["freeSpace"] = shutil.disk_usage(local["path"]).free
                return cached
        except (OSError, ValueError):
            pass
    with _running:
        result = _scan(service, app_name, local)
    if "error" not in result:
        result["fingerprint"], result["checked"] = fp, time.time()
        write_json(_cache_path(app_name), result)
    return result


def _scan(service, app_name, local):
    core = service.core
    manifest = _installed_manifest(service, app_name, local)
    if manifest is None:
        return {"error": tr("Dateiliste der installierten Version nicht gefunden - Vorschau nicht möglich.")}

    root = local["path"]
    elements = manifest.file_manifest_list.elements
    present = _exists_parallel(root, [fm.filename for fm in elements])
    groups, base, base_missing = {}, 0, 0
    for fm, exists in zip(elements, present):
        if not fm.install_tags:
            base += fm.file_size
            if not exists:
                base_missing += fm.file_size
            continue
        key = tuple(sorted(set(fm.install_tags)))
        g = groups.setdefault(key, {"tags": list(key), "files": 0, "present": 0, "presentSize": 0, "missingSize": 0})
        g["files"] += 1
        if exists:
            g["present"] += 1
            g["presentSize"] += fm.file_size
        else:
            g["missingSize"] += fm.file_size
    return _result(service, app_name, local, manifest.meta.build_version, groups, base, base_missing)


def _exists_parallel(root, names, threads=16, chunk=4000):
    """Existenz vieler Dateien pruefen - parallel, weil jede Pruefung auf die Platte wartet
    (gemessen beim DevKit: ~120 s einzeln, ~20 s mit 16 Threads)."""
    def check(part):
        return [os.path.exists(os.path.join(root, n)) for n in part]
    parts = [names[i:i + chunk] for i in range(0, len(names), chunk)]
    with ThreadPoolExecutor(threads) as pool:
        return [hit for part in pool.map(check, parts) for hit in part]


def _result(service, app_name, local, version, groups, base, base_missing):
    # Was gilt als installiert? Nach Uebernahme kennt Legendary die Auswahl genau,
    # sonst zaehlt (wie bei der Update-Erkennung), ob mehr als die Haelfte da ist.
    selected = None
    if local["source"] == "legendary":
        igame = service.core.lgd.get_installed_game(app_name)
        selected = [t for t in (igame.install_tags or []) if t]
    root = local["path"]
    return {
        "appName": app_name,
        "path": root,
        "version": version,
        "source": local["source"],
        "baseSize": base,
        "baseMissing": base_missing,
        "components": _components(groups.values(), selected),
        "groups": list(groups.values()),
        "freeSpace": shutil.disk_usage(root).free,
    }


def _components(groups, selected):
    tags = {}
    for g in groups:
        for t in g["tags"]:
            s = tags.setdefault(t, {"tag": t, "size": 0, "files": 0, "present": 0})
            s["size"] += g["presentSize"] + g["missingSize"]
            s["files"] += g["files"]
            s["present"] += g["present"]
    for s in tags.values():
        s["installed"] = (s["tag"] in selected) if selected is not None else s["present"] * 2 > s["files"]
    return sorted(tags.values(), key=lambda s: -s["size"])


def record_change(service, app_name, selected, removed, added):
    """Nach einer Komponenten-Aenderung ueber den Launcher den gespeicherten Stand direkt
    nachfuehren - wir wissen ja, was geladen bzw. geloescht wurde. Kein erneutes Pruefen.
    Gibt False zurueck, wenn kein passender Stand gespeichert war (dann neu pruefen)."""
    try:
        with open(_cache_path(app_name), encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        return False
    sel, rem = set(selected), set(removed)
    for g in cached["groups"]:
        tags = set(g["tags"])
        if rem & tags and not sel & tags:            # von prune geloescht
            g["missingSize"] += g["presentSize"]
            g["presentSize"] = g["present"] = 0
        elif added and sel & tags:                   # von Legendary vollstaendig ergaenzt
            g["presentSize"] += g["missingSize"]
            g["missingSize"], g["present"] = 0, g["files"]
    if added:
        cached["baseMissing"] = 0
    cached["components"] = _components(cached["groups"], sorted(sel))
    service.core.lgd._installed = None
    local = service.installed().get(app_name)
    old = cached.get("fingerprint") or {}
    if not local or local["path"] != old.get("path") or (old.get("source") == "legendary" and local["version"] != old.get("version")):
        return False  # Ordner/Version anders (z. B. Update nebenbei) -> lieber neu pruefen
    cached["source"] = local["source"]
    cached["fingerprint"] = _fingerprint(service, app_name, local)
    write_json(_cache_path(app_name), cached)
    return True


def summarize(analysis, selected):
    """Exakte Wirkung einer Auswahl (dieselbe Regel wie beim Loeschen, siehe oben)."""
    sel = set(selected)
    removed = {c["tag"] for c in analysis["components"] if c["installed"]} - sel
    gone = [g for g in analysis["groups"] if removed & set(g["tags"]) and not sel & set(g["tags"])]
    added = sorted(sel - {c["tag"] for c in analysis["components"] if c["installed"]})
    # geladen wird nur, wenn etwas neu gewaehlt ist - dann ergaenzt Legendary alles Fehlende der Auswahl
    download = (analysis["baseMissing"] + sum(g["missingSize"] for g in analysis["groups"] if sel & set(g["tags"]))
                if added else 0)
    return {"download": download, "freed": sum(g["presentSize"] for g in gone),
            "filesRemoved": sum(g["present"] for g in gone), "removed": sorted(removed), "added": added}

"""Bereits geladene Fab-Assets wiederverwenden statt neu herunterzuladen.

Zwei Quellen:
- Epics VaultCache (nur lesend; geloescht wird dort nur auf ausdruecklichen Wunsch, siehe delete_local):
  <Ordner>/<artifactId>/manifest + data/...
- eigene behaltene Assets (Einstellung "Assets behalten"):
  <Zwischenordner>/<artifactId>/... + .siccora-version
Genutzt wird eine Quelle nur, wenn sie vollstaendig ist (jede Datei der
Dateiliste mit richtiger Groesse) und - soweit pruefbar - die aktuelle Version hat.
"""
import configparser
import glob
import json
import os
import re
import shutil
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor

from . import settings

KEPT_MARKER = ".siccora-version"


def epic_vault_dirs():
    """Vault-Ordner aus den Einstellungen des Epic Launchers (VaultCacheDirectories)."""
    dirs = []
    for ini in glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "EpicGamesLauncher", "Saved",
                                      "Config", "Windows*", "GameUserSettings.ini")):
        try:
            with open(ini, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip().startswith("VaultCacheDirectories="):
                        path = os.path.normpath(line.split("=", 1)[1].strip())
                        if os.path.isdir(path) and path not in dirs:
                            dirs.append(path)
        except OSError:
            pass
    return dirs


def epic_cached():
    """artifactIds, die in Epics Cache eine Dateiliste haben (ohne Vollstaendigkeitspruefung)."""
    if not settings.get("useEpicVault"):
        return set()
    found = set()
    for d in epic_vault_dirs():
        try:
            for entry in os.scandir(d):
                if entry.is_dir() and os.path.isfile(os.path.join(entry.path, "manifest")):
                    found.add(entry.name)
        except OSError:
            pass
    return found


def _complete(manifest, data_dir):
    for fm in manifest.file_manifest_list.elements:
        try:
            if os.path.getsize(os.path.join(data_dir, fm.filename)) != fm.file_size:
                return False
        except OSError:
            return False
    return True


def find_source(core, artifact_id, current=None):
    """Beste Quelle ohne Download, sonst None.

    current: aktuelle Dateiliste von Epic (None, wenn Epic keine liefert -
    dann gilt Epics Cache als einzige Quelle, die Version ist nicht pruefbar).
    Rueckgabe: {"source": "epic"|"kept", "path": Ordner mit den Dateien,
                "manifest": Dateiliste, "version": ..., "verified": bool}
    """
    # 1) eigenes behaltenes Asset (nur mit pruefbarer, passender Version)
    kept = os.path.join(settings.get("vaultDir"), artifact_id)
    marker = os.path.join(kept, KEPT_MARKER)
    if current is not None and os.path.isfile(marker):
        with open(marker, encoding="utf-8") as f:
            version = f.read().strip()
        if version == current.meta.build_version and _complete(current, kept):
            return {"source": "kept", "path": kept, "manifest": current, "version": version, "verified": True}

    # 2) Epics VaultCache
    if settings.get("useEpicVault"):
        for d in epic_vault_dirs():
            entry = os.path.join(d, artifact_id)
            try:
                with open(os.path.join(entry, "manifest"), "rb") as f:
                    cached = core.load_manifest(f.read())
            except Exception:  # fehlt oder unlesbar -> naechster Ordner
                continue
            version = cached.meta.build_version
            if current is not None and version != current.meta.build_version:
                continue  # veraltet - dann lieber frisch laden
            data = os.path.join(entry, "data")
            if _complete(cached, data):
                return {"source": "epic", "path": data, "manifest": cached, "version": version,
                        "verified": current is not None}
    return None


def mark_kept(folder, version):
    with open(os.path.join(folder, KEPT_MARKER), "w", encoding="utf-8") as f:
        f.write(version)


def asset_updates(core, titles):
    """Lokal liegende Fab-Assets (Epics Vault-Cache, behaltene Assets), fuer die Epic
    inzwischen eine neuere Version hat. titles: {artifactId: Titel}. Liest nur."""
    current = {a.app_name: a.build_version for a in (core.get_assets(update_assets=False) or [])}
    try:  # frischer: vom letzten Update-Check (epic.check_updates)
        from .epic import DATA_DIR
        with open(os.path.join(DATA_DIR, "asset_versions.json"), encoding="utf-8") as f:
            current.update({k: v for k, v in json.load(f).get("versions", {}).items() if v})
    except (OSError, ValueError):
        pass
    found = []

    def check(artifact, version, where):
        cur = current.get(artifact)
        if cur and version and cur != version:
            found.append({"artifactId": artifact, "title": titles.get(artifact, artifact),
                          "local": version.split("+")[0], "current": cur.split("+")[0], "where": where})

    if settings.get("useEpicVault"):
        for d in epic_vault_dirs():
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                path = os.path.join(e.path, "manifest")
                if e.name not in current or not os.path.isfile(path):
                    continue
                try:
                    with open(path, "rb") as f:
                        check(e.name, core.load_manifest(f.read()).meta.build_version, "epic")
                except Exception:  # unlesbar -> ueberspringen
                    continue
    kept_root = settings.get("vaultDir")
    try:
        kept = list(os.scandir(kept_root)) if kept_root else []
    except OSError:
        kept = []
    for e in kept:
        marker = os.path.join(e.path, KEPT_MARKER)
        if os.path.isfile(marker):
            with open(marker, encoding="utf-8") as f:
                check(e.name, f.read().strip(), "kept")
    return found


# --- Lokal gespeicherte Assets ansehen und loeschen ---------------------------
# Geloescht wird NUR, was der Nutzer ausdruecklich waehlt, und nur ein direkter
# Unterordner eines Vault-Ordners, der wie ein Asset-Download aussieht. Nie
# Engines, DevKits oder Projekte; "FabLibrary" (Epics Plugin-Daten) bleibt.
DELETING = ".siccora-delete"


def _entries():
    """[(Schluessel, Ort, Name, Pfad, Art)] - Art: asset | incomplete. Liest nur."""
    found = []
    for d in epic_vault_dirs():
        try:
            items = [e for e in os.scandir(d) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for e in items:
            if e.is_junction() or os.path.exists(os.path.join(e.path, "Engine")):
                continue
            if os.path.exists(os.path.join(e.path, "manifest")):
                found.append((f"epic:{e.path}", "epic", e.name, e.path, "asset"))
            elif os.path.isdir(os.path.join(e.path, "data")) or os.path.isdir(os.path.join(e.path, "stage")):
                found.append((f"epic:{e.path}", "epic", e.name, e.path, "incomplete"))  # abgebrochener Epic-Download
    root = settings.get("vaultDir")
    try:
        kept = [e for e in os.scandir(root) if e.is_dir(follow_symlinks=False)] if root else []
    except OSError:
        kept = []
    for e in kept:
        if os.path.isfile(os.path.join(e.path, KEPT_MARKER)) and not e.is_junction():
            found.append((f"kept:{e.path}", "kept", e.name, e.path, "asset"))
    return found


def _size(path):
    total = files = 0
    stack = [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                        files += 1
        except OSError:
            continue
    return total, files


def _local_version(core, where, path):
    try:
        if where == "kept":
            with open(os.path.join(path, KEPT_MARKER), encoding="utf-8") as f:
                return f.read().strip()
        with open(os.path.join(path, "manifest"), "rb") as f:
            return core.load_manifest(f.read()).meta.build_version
    except Exception:  # fehlt oder unlesbar
        return None


def local_assets(core, fab_items):
    """Alles, was lokal Platz belegt - mit Groesse und Zuordnung zur Fab-Bibliothek."""
    owners = {v["artifactId"]: (it, v) for it in fab_items for v in it["versions"]}
    entries = _entries()
    with ThreadPoolExecutor(8) as pool:
        sizes = list(pool.map(lambda e: _size(e[3]), entries))
    out = []
    for (key, where, name, path, kind), (size, files) in zip(entries, sizes):
        item, version = owners.get(name, (None, None))
        build = _local_version(core, where, path) if kind == "asset" else None
        engine = re.match(r"\d+\.\d+", build or "")
        out.append({
            "key": key, "where": where, "name": name, "path": path, "incomplete": kind == "incomplete",
            "sizeMb": round(size / 1048576, 1), "files": files, "title": (item or {}).get("title") or name,
            "seller": (item or {}).get("seller") or "", "image": (item or {}).get("image"),
            "assetId": (item or {}).get("id"), "kind": (item or {}).get("kind"),
            "engines": (version or {}).get("engines") or ([f"UE_{engine.group()}"] if engine else []),
            "redownload": bool(version and version.get("downloadable")),
        })
    return sorted(out, key=lambda a: -a["sizeMb"])


def _epic_launcher_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EpicGamesLauncher.exe", "/NH"], capture_output=True,
                             text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "EpicGamesLauncher.exe" in out


def _force(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)  # schreibgeschuetzte Datei
    func(path)


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def delete_local(key, installed, in_use):
    """Einen Download aus dem Vault loeschen. key stammt aus _entries() - der Pfad kommt nie
    von der Oberflaeche. installed: Ordner installierter Software, in_use: Pfade laufender Auftraege."""
    entry = next((e for e in _entries() if e[0] == key), None)
    if not entry:
        return {"error": "Asset nicht gefunden."}
    _, where, _, path, _ = entry
    target = _norm(path)
    for other in filter(None, installed):
        o = _norm(other)
        if target == o or target.startswith(o + os.sep) or o.startswith(target + os.sep):
            return {"error": "Der Ordner gehört zu einer installierten Engine oder einem DevKit."}
    if any(p and (_norm(p) == target or _norm(p).startswith(target + os.sep)) for p in in_use):
        return {"error": "Das Asset wird gerade verwendet. Warte, bis der Auftrag fertig ist."}
    if where == "epic" and _epic_launcher_running():
        return {"error": "Der Epic Launcher läuft gerade. Bitte schließen, er könnte diesen Ordner benutzen."}
    size = _size(path)[0]
    # Erst umbenennen: klappt das nicht, sind Dateien in Benutzung - dann bleibt alles unversehrt
    trash = path + DELETING
    try:
        os.rename(path, trash)
    except OSError:
        return {"error": "Dateien sind gerade in Benutzung oder der Zugriff ist nicht erlaubt."}
    try:
        shutil.rmtree(trash, onerror=_force)
    except OSError:
        return {"error": "Der Ordner konnte nicht vollständig gelöscht werden."}
    return {"ok": True, "sizeMb": round(size / 1048576, 1)}


def used_space():
    """Platz, den Fab-Downloads im Vault und in den behaltenen Assets belegen (Bytes)."""
    with ThreadPoolExecutor(8) as pool:
        return sum(size for size, _ in pool.map(lambda e: _size(e[3]), _entries()))

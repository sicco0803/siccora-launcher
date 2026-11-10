"""Update-Vorschau: was ein Update tun WUERDE - liest nur, schreibt nichts.

Vergleicht die Dateiliste (Manifest) der installierten Version mit der
aktuellen von Epic. Bewusst ohne Legendarys Installationsablauf: der hat bei
UE 5.5 schon vor der Rueckfrage Dateien geloescht.
"""
import glob
import json
import os
import shutil
import types

from .i18n import tr

EGL_MANIFESTS = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"


def _egl_item(app_name):
    for path in glob.glob(os.path.join(EGL_MANIFESTS, "*.item")):
        try:
            with open(path, encoding="utf-8") as f:
                item = json.load(f)
        except (OSError, ValueError):
            continue
        if item.get("AppName") == app_name:
            return item
    return None


def _installed_manifest(service, app_name, local):
    """Manifest der installierten Version - vom Epic Launcher oder von Legendary."""
    core = service.core
    if local["source"] == "legendary":
        igame = core.lgd.get_installed_game(app_name)
        data = core.lgd.load_manifest(app_name, igame.version, igame.platform)
        return core.load_manifest(data) if data else None
    item = _egl_item(app_name)
    if not item:
        return None
    path = os.path.join(item["InstallLocation"], ".egstore", f"{item['InstallationGuid']}.manifest")
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return core.load_manifest(f.read())


def _present_tags(manifest, root):
    """Optionale Komponenten, von denen mehr als die Haelfte der Dateien da ist."""
    total, present = {}, {}
    for fm in manifest.file_manifest_list.elements:
        if not fm.install_tags:
            continue
        exists = os.path.exists(os.path.join(root, fm.filename))
        for tag in fm.install_tags:
            total[tag] = total.get(tag, 0) + 1
            present[tag] = present.get(tag, 0) + exists
    return sorted(t for t in total if present[t] * 2 > total[t])


def _selected(fm, tags):
    return not fm.install_tags or any(t in tags for t in fm.install_tags)


def update_preview(service, app_name):
    local = service.installed().get(app_name)
    if not local:
        return {"error": tr("Nicht installiert.")}
    item = service.find(app_name)
    if not item:
        return {"error": tr("Eintrag nicht in der Bibliothek - bitte einmal „Aktualisieren“.")}

    core = service.core
    core.login()
    old = _installed_manifest(service, app_name, local)
    if old is None:
        return {"error": tr("Dateiliste der installierten Version nicht gefunden - Vorschau nicht möglich.")}

    game = types.SimpleNamespace(namespace=item["namespace"], catalog_item_id=item["catalogItemId"], app_name=app_name)
    new_bytes, *_ = core.get_cdn_manifest(game)
    new = core.load_manifest(new_bytes)

    root = local["path"]
    tags = _present_tags(old, root)
    old_files = {fm.filename: fm for fm in old.file_manifest_list.elements if _selected(fm, tags)}
    new_files = {fm.filename: fm for fm in new.file_manifest_list.elements if _selected(fm, tags)}

    changed = [f for f, fm in new_files.items() if f in old_files and old_files[f].hash != fm.hash]
    added = [f for f in new_files if f not in old_files]
    removed = [f for f in old_files if f not in new_files]

    # Download: Bausteine (Chunks) der geaenderten/neuen Dateien, die es in der alten Version nicht gab
    old_chunks = {c.guid_num for c in old.chunk_data_list.elements}
    needed = {cp.guid_num for f in changed + added for cp in new_files[f].chunk_parts}
    sizes = {c.guid_num: c.file_size for c in new.chunk_data_list.elements}
    download = sum(sizes.get(g, 0) for g in needed - old_chunks)

    write = sum(new_files[f].file_size for f in changed + added)
    old_size = sum(fm.file_size for fm in old_files.values())
    new_size = sum(fm.file_size for fm in new_files.values())
    free = shutil.disk_usage(root).free

    up_to_date = not (changed or added or removed)
    # Gleiche Dateien und gleiche Manifest-Version, nur Epics Asset-Liste nennt eine andere Nummer:
    # nichts zu tun - merken, damit der Update-Hinweis verschwindet
    acknowledged = bool(up_to_date and old.meta.build_version == new.meta.build_version
                        and item.get("latest") and item["latest"] != local["version"])
    if acknowledged:
        service.ack_version(app_name, item["latest"])

    return {
        "appName": app_name,
        "acknowledged": acknowledged,
        "title": item["title"],
        "path": root,
        "source": local["source"],
        "oldVersion": old.meta.build_version,
        "newVersion": new.meta.build_version,
        "upToDate": up_to_date,
        "components": tags,
        "changed": len(changed),
        "added": len(added),
        "removed": len(removed),
        "removedSample": sorted(removed)[:12],
        "downloadMb": download / 1024 / 1024,
        "writeMb": write / 1024 / 1024,
        "sizeChangeMb": (new_size - old_size) / 1024 / 1024,
        "freeMb": free / 1024 / 1024,
        "enoughSpace": free > write * 1.1,
    }

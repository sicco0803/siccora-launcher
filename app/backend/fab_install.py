"""Fab-Assets in Projekte bzw. Engines bringen - wie "Zum Projekt hinzufuegen" im Epic Launcher.

Ablauf: Vorschau (liest nur Epics Dateiliste) -> Quelle bestimmen (Epics
VaultCache bzw. behaltenes Asset, sonst Download in den Zwischenordner) ->
Kopieren ins Ziel. Vorhandene Dateien werden nur ueberschrieben, wenn das
ausdruecklich gewaehlt wurde.
"""
import json
import os
import re
import shutil
import types

import requests

from . import fabdl
from .i18n import tr
from .vault import KEPT_MARKER, find_source


KINDS = {
    "ASSET_PACK": "Zum Projekt hinzufügen",
    "CODE_PLUGIN": "In Engine installieren",
    "COMPLETE_PROJECT": "Projekt erstellen",
}


def read_project(uproject):
    """Projektordner und Engine-Version aus einer .uproject-Datei."""
    with open(uproject, encoding="utf-8-sig") as f:
        data = json.load(f)
    assoc = str(data.get("EngineAssociation") or "")
    # "5.7" = Launcher-Engine; eine GUID/{...} = selbst gebaute Engine (z. B. DevKits)
    engine = f"UE_{assoc}" if re.fullmatch(r"\d+\.\d+", assoc) else None
    return {"dir": os.path.dirname(os.path.abspath(uproject)), "name": os.path.splitext(os.path.basename(uproject))[0],
            "engine": engine, "association": assoc}


def _ver(engine):
    return tuple(int(x) for x in re.findall(r"\d+", engine or ""))


def compatibility(item, artifact_id, target_ue):
    """Passt diese Asset-Version zur Ziel-Engine?
    ok | newer (Asset neuer als Ziel) | older (Asset aelter) | unknown (Zielversion unbekannt)"""
    engines = next((v["engines"] for v in item["versions"] if v["artifactId"] == artifact_id), [])
    label = ", ".join(e.replace("UE_", "") for e in engines)
    result = {"target": target_ue, "asset": label}
    if not target_ue or not engines:
        return {**result, "state": "unknown"}
    if f"UE_{target_ue}" in engines:
        return {**result, "state": "ok"}
    return {**result, "state": "newer" if min(_ver(e) for e in engines) > _ver(target_ue) else "older"}


def _manifest(service, item, artifact_id):
    """Aktuelle Dateiliste: (Manifest, nur ueber Fab?). (None, False), wenn es keine gibt."""
    asset = service.asset_ref(artifact_id)
    if asset:
        game = types.SimpleNamespace(namespace=asset.namespace, catalog_item_id=asset.catalog_item_id, app_name=artifact_id)
        data, *_ = service.core.get_cdn_manifest(game)
        return service.core.load_manifest(data), False
    if not item.get("namespace"):
        return None, False
    try:
        with service.locked():
            service.core.login()
            token = service.core.lgd.userdata["access_token"]
        data, _ = fabdl.fetch(token, artifact_id, item["id"], item["namespace"])
    except (requests.RequestException, ValueError):
        return None, False
    return service.core.load_manifest(data), True


def _safe_join(root, rel):
    """Zielpfad bilden und sicherstellen, dass er im Zielordner bleibt (kein ../)."""
    root = os.path.abspath(root)
    dest = os.path.abspath(os.path.join(root, *rel.split("/")))
    if os.path.commonpath([root, dest]) != root:
        raise ValueError(tr("Ungültiger Pfad in der Dateiliste: {rel}", rel=rel))
    return dest


def mapping(kind, files, target, project_name=None):
    """(Pfad im Download, Ziel auf der Platte) je Datei - und was ignoriert wird."""
    pairs, ignored = [], []
    for rel in files:
        if kind == "ASSET_PACK":
            if rel.startswith("Content/"):
                pairs.append((rel, _safe_join(target, rel)))  # target = Projektordner
            else:
                ignored.append(rel)
        elif kind == "CODE_PLUGIN":
            if rel.startswith("Engine/Plugins/"):
                pairs.append((rel, _safe_join(target, rel)))  # target = Engine-Hauptordner (UE_5.x)
            else:
                ignored.append(rel)
        elif kind == "COMPLETE_PROJECT":
            pairs.append((rel, _safe_join(os.path.join(target, project_name), rel)))
        else:
            raise ValueError(tr("Unbekannte Asset-Art: {kind}", kind=kind))
    return pairs, ignored


def project_folder_name(files, title):
    uprojects = [f for f in files if f.endswith(".uproject") and "/" not in f]
    if uprojects:
        return uprojects[0][:-len(".uproject")]
    return re.sub(r"[^A-Za-z0-9_]", "", title or "FabProjekt") or "FabProjekt"


def plan(service, asset_id, artifact_id, target):
    item = service.fab_item(asset_id)
    if not item:
        return {"error": tr("Asset nicht in der Fab-Bibliothek gefunden.")}
    kind = item.get("kind")
    if not target or not os.path.isdir(target):
        return {"error": tr("Zielordner existiert nicht.")}
    current, via_fab = _manifest(service, item, artifact_id)
    src = find_source(service.core, artifact_id, current)  # schon vollstaendig da? (Epic-Cache / behalten)
    if current is None and src is None:
        raise ValueError(tr("Diese Version ist derzeit nicht ladbar. Epic bietet sie nicht mehr an."))
    manifest = src["manifest"] if src else current
    files = {fm.filename: fm.file_size for fm in manifest.file_manifest_list.elements}
    name = project_folder_name(files, item["title"]) if kind == "COMPLETE_PROJECT" else None
    pairs, ignored = mapping(kind, files, target, name)
    existing = [dest for _, dest in pairs if os.path.exists(dest)]
    size = sum(files[rel] for rel, _ in pairs)
    return {
        "assetId": asset_id, "artifactId": artifact_id, "title": item["title"], "kind": kind,
        "action": tr(KINDS.get(kind, kind)), "actionKey": KINDS.get(kind, kind), "target": target, "projectName": name,
        "destination": os.path.commonpath([os.path.dirname(d) for _, d in pairs]) if pairs else target,
        "files": len(pairs), "sizeMb": size / 1024 / 1024, "ignored": len(ignored),
        "existing": len(existing), "existingSample": [os.path.relpath(e, target) for e in existing[:10]],
        "freeMb": shutil.disk_usage(target).free / 1024 / 1024,
        # Quelle: "epic" (Epics VaultCache), "kept" (behalten) oder "download"
        "source": src["source"] if src else "download",
        "sourcePath": src["path"] if src else None,
        "version": manifest.meta.build_version,
        "versionVerified": src["verified"] if src else True,
        "downloadMb": 0 if src else sum(c.file_size for c in manifest.chunk_data_list.elements) / 1024 / 1024,
        # kommt nicht ueber Epics Asset-Liste: der Download braucht diese Angaben
        "viaFab": {"asset": item["id"], "namespace": item["namespace"], "title": item["title"]} if via_fab else None,
    }


def copy_into_place(cache_dir, kind, target, project_name, overwrite, progress=None):
    """Aus dem Zwischenordner ins Ziel kopieren. Gibt (kopiert, uebersprungen) zurueck."""
    files = []
    for root, _, names in os.walk(cache_dir):
        for n in names:
            if n != KEPT_MARKER:  # eigene Markierung nicht ins Projekt kopieren
                files.append(os.path.relpath(os.path.join(root, n), cache_dir).replace(os.sep, "/"))
    pairs, _ = mapping(kind, files, target, project_name)
    copied = skipped = 0
    for i, (rel, dest) in enumerate(pairs):
        if os.path.exists(dest) and not overwrite:
            skipped += 1
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(os.path.join(cache_dir, *rel.split("/")), dest)
            copied += 1
        if progress and i % 50 == 0:
            progress(100.0 * (i + 1) / max(len(pairs), 1))
    return copied, skipped

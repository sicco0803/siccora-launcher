"""Dateiliste (Manifest) eines Fab-Assets direkt bei Fab abholen.

Manche Assets stehen nicht in Epics alter Asset-Liste, die Legendary nutzt - sie
kommen nur ueber Fab, wie im Epic Launcher und im Fab-Plugin des Editors. Die
Dateien selbst liegen auf denselben Download-Servern wie alle anderen.

Das Anmelde-Token geht nur an fab.com, die Download-Server bekommen es nie.
"""
import hashlib

import requests

ARTIFACT_URL = "https://www.fab.com/e/artifacts/{}/manifest"


def fetch(token, artifact_id, asset_id, namespace, platform="Windows"):
    """(Manifest-Daten, Basis-Adressen der Download-Server). Hash wird geprueft."""
    r = requests.post(ARTIFACT_URL.format(artifact_id),
                      json={"item_id": asset_id, "namespace": namespace, "platform": platform},
                      headers={"Authorization": f"bearer {token}"}, timeout=30)
    r.raise_for_status()
    info = next((d for d in r.json().get("downloadInfo", []) if d.get("type") == "manifest"), None)
    if not info:
        raise ValueError("Fab liefert keine Dateiliste für dieses Asset.")
    urls = [p["manifestUrl"] for p in info.get("distributionPoints", []) if p.get("manifestUrl", "").startswith("https://")]
    data = None
    for url in urls:
        try:
            got = requests.get(url, timeout=30)
        except requests.RequestException:
            continue
        if got.ok and hashlib.sha1(got.content).hexdigest() == info.get("manifestHash"):
            data = got.content
            break
    if data is None:
        raise ValueError("Die Dateiliste konnte nicht geladen werden.")
    bases = list(dict.fromkeys(u.split("?")[0].rpartition("/")[0] for u in urls))
    return data, bases

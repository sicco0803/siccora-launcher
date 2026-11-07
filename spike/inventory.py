"""Machbarkeitstest: liest nur, veraendert nichts.

1. Epic-Bibliothek (Rohliste, ohne teure Metadaten-Abfragen) nach Namespace gruppiert
2. Fab-Bibliothek ueber den Endpunkt, den auch der Epic Launcher nutzt
Ergebnis landet in spike/out/ (nicht im Git).
"""
import collections
import json
import os

import requests
from legendary.core import LegendaryCore

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

core = LegendaryCore()
core.egs.request_timeout = 120  # die Rohliste ist bei 4700+ Eintraegen gross
assert core.login(), "Nicht angemeldet - bitte login.py ausfuehren"
user = core.lgd.userdata
account_id = user["account_id"]

# --- 1. Epic-Bibliothek ---------------------------------------------------
assets = core.egs.get_game_assets(platform="Windows")
by_ns = collections.Counter(a["namespace"] for a in assets)
ue = [a for a in assets if a["namespace"] == "ue"]
print(f"Epic-Bibliothek: {len(assets)} Eintraege (Windows)")
for ns, n in by_ns.most_common(10):
    print(f"  {ns}: {n}")
print("  Beispiele aus 'ue':", ", ".join(sorted(a["appName"] for a in ue)[:15]))
for want in ("UE_5.5", "UE_5.7", "UE_5.8", "ARKDevKit", "95dc9c76e91041279de1f72f64d65f28",
             "fb67ca3f5de74da880ab96bdc668118d", "e61de4231c6b43349615781e737ad297"):
    print(f"  {want}: {'gefunden' if any(a['appName'] == want for a in assets) else 'NICHT gefunden'}")
json.dump(assets, open(os.path.join(OUT, "epic_assets.json"), "w"), indent=1)

# Manifest-Abruf fuer UE_5.8 (nur Kopf-Infos, kein Download) -> beweist Update-Faehigkeit
try:
    m = core.egs.get_game_manifest("ue", next(a["catalogItemId"] for a in ue if a["appName"] == "UE_5.8"), "UE_5.8", "Windows")
    el = m["elements"][0]
    print(f"\nManifest UE_5.8: Version {el['buildVersion']}, {len(el['manifests'])} Download-Quellen")
except Exception as e:
    print(f"\nManifest UE_5.8 fehlgeschlagen: {e!r}")

# --- 2. Fab-Bibliothek ----------------------------------------------------
s = requests.Session()
s.headers.update({
    "Authorization": f"bearer {user['access_token']}",
    "User-Agent": core.egs._user_agent if hasattr(core.egs, "_user_agent") else "EpicGamesLauncher",
})
fab_items, cursor = [], None
for _ in range(50):
    params = {"count": 100}
    if cursor:
        params["cursor"] = cursor
    r = s.get(f"https://www.fab.com/e/accounts/{account_id}/ue/library", params=params, timeout=30)
    if r.status_code != 200:
        print(f"\nFab-Bibliothek: HTTP {r.status_code} -> {r.text[:200]!r}")
        break
    data = r.json()
    fab_items += data.get("results", [])
    cursor = (data.get("cursors") or {}).get("next")
    if not cursor:
        break
if fab_items:
    print(f"\nFab-Bibliothek: {len(fab_items)} Assets")
    for it in fab_items[:10]:
        print(f"  - {it.get('title')}")
    json.dump(fab_items, open(os.path.join(OUT, "fab_library.json"), "w"), indent=1)

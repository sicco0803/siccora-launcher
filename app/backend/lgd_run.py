"""Startet Legendary mit zwei Anpassungen fuer Unreal-Arbeit.

Original-Legendary laedt vor jeder Installation die Metadaten der GESAMTEN
Bibliothek (bei 4700+ Eintraegen -> HTTP 429 von Epic) und blendet dabei alle
Unreal-Engine-Eintraege aus. Hier wird nur der eine benoetigte Eintrag
geholt, Engines eingeschlossen. Aufruf wie das normale legendary-Programm:

    python lgd_run.py -y install <appName> ...
"""
import json
import os
import sys
import time

import legendary.core as lcore
from legendary.downloader.mp import manager as dl_manager
from legendary.downloader.mp.manager import DLManager
from legendary.downloader.mp.workers import DLWorker
from legendary.models.downloading import FileTask, TaskFlags
from legendary.models.game import Game, Sidecar

try:  # im Paket als backend-Modul, in der Entwicklung als Skript
    from . import fabdl
except ImportError:
    import fabdl


def refresh_single(core, app_name, platform="Windows"):
    """Metadaten genau eines Eintrags aktualisieren (auch Engines)."""
    infos = {}
    for plat in {"Windows", platform} | core.get_installed_platforms():
        core.get_assets(update_assets=True, platform=plat)
        asset = next((a for a in core.lgd.assets.get(plat, []) if a.app_name == app_name), None)
        if asset:
            infos[plat] = asset
    if not infos:
        return None
    first = infos.get("Windows") or next(iter(infos.values()))
    meta = core.egs.get_game_info(first.namespace, first.catalog_item_id) or {"title": "Unknown"}

    sidecar = None
    if first.sidecar_rev > 0:
        manifest_info = core.egs.get_game_manifest(first.namespace, first.catalog_item_id, app_name)["elements"][0]
        if "sidecar" in manifest_info:
            sidecar = Sidecar(config=json.loads(manifest_info["sidecar"]["config"]), rev=manifest_info["sidecar"]["rvn"])

    game = Game(app_name=app_name, app_title=meta["title"], metadata=meta, asset_infos=infos, sidecar=sidecar)
    core.lgd.set_game_meta(app_name, game)
    return game


# Asset, das nur ueber Fab kommt (steht nicht in Epics Asset-Liste): {"asset": ..., "namespace": ..., "title": ...}
_FAB = json.loads(os.environ.get("SICCORA_FAB_ASSET") or "null")


def _get_game(self, app_name, update_meta=False, platform="Windows"):
    if _FAB:  # gibt es bei Legendary nicht - Eintrag nur fuer diesen einen Download
        return Game(app_name=app_name, app_title=_FAB["title"], metadata={}, asset_infos={})
    if update_meta:
        refresh_single(self, app_name, platform)
    return self.lgd.get_game_meta(app_name)


_orig_cdn_manifest = lcore.LegendaryCore.get_cdn_manifest


def _cdn_manifest(self, game, platform="Windows", disable_https=False):
    if not _FAB:
        return _orig_cdn_manifest(self, game, platform, disable_https)
    data, bases = fabdl.fetch(self.lgd.userdata["access_token"], game.app_name, _FAB["asset"], _FAB["namespace"], platform)
    return data, bases, False, {}


def _never_delete_deselected(self, installed_game):
    # Legendary loescht Dateien "abgewaehlter" Komponenten. Bei aus dem Epic
    # Launcher uebernommenen Engines kennt es die Auswahl nicht und haelt alle
    # optionalen Teile (Quellcode, Templates ...) fuer abgewaehlt -> nie loeschen.
    print(f"[Siccora] Loeschen abgewaehlter Komponenten fuer {installed_game.app_name} uebersprungen")


_SILENT_DELETE = TaskFlags.DELETE_FILE | TaskFlags.SILENT
_orig_run_analysis = DLManager.run_analysis


def _run_analysis_without_tag_deletes(self, *args, **kwargs):
    # Zweiter Loeschweg: Bei jeder Installation/jedem Update mit Komponenten-Auswahl
    # haengt Legendary still Loeschauftraege fuer alle Dateien ausserhalb der Auswahl an
    # (DELETE_FILE|SILENT). Uebersieht die Komponenten-Erkennung je eine Komponente,
    # waeren deren Dateien weg. Nur erlaubt, wenn der Launcher es ausdruecklich will
    # (Komponenten bewusst abwaehlen) - echte Loeschungen entfallener Dateien
    # (nur DELETE_FILE) bleiben unberuehrt.
    result = _orig_run_analysis(self, *args, **kwargs)
    if os.environ.get("SICCORA_ALLOW_TAG_DELETE") != "1":
        keep = [t for t in self.tasks if not (isinstance(t, FileTask) and (t.flags & _SILENT_DELETE) == _SILENT_DELETE)]
        dropped = len(self.tasks) - len(keep)
        if dropped:
            self.tasks.clear()
            self.tasks.extend(keep)
            print(f"[Siccora] {dropped} Loeschauftraege fuer nicht gewaehlte Komponenten verworfen")
    return result


_limit = {"until": 0.0, "bps": 0.0}


def _limit_bps():
    """Bytes/s je Verbindung, 0 = frei. Liest die Launcher-Einstellung hoechstens einmal je
    Sekunde - so wirkt eine Aenderung sofort, auch auf laufende Downloads."""
    now = time.monotonic()
    if now >= _limit["until"]:
        _limit["until"] = now + 1
        try:
            with open(os.environ["SICCORA_SETTINGS"], encoding="utf-8") as f:
                mb = int(json.load(f).get("speedLimit") or 0)
            _limit["bps"] = mb * 1024 * 1024 / max(int(os.environ.get("SICCORA_WORKERS") or 1), 1)
        except (KeyError, OSError, TypeError, ValueError):
            pass  # keine Einstellung lesbar: letzter Stand gilt
    return _limit["bps"]


class _LimitedWorker(DLWorker):
    """Tempolimit: Legendary kennt keins. Jede Verbindung wartet nach einem Stueck so lange,
    bis ihr Anteil am Limit eingehalten ist."""

    def run(self):
        plain_get = self.session.get

        def limited_get(url, **kwargs):
            start = time.monotonic()
            response = plain_get(url, **kwargs)
            while rate := _limit_bps():
                pause = len(response.content) / rate - (time.monotonic() - start)
                if pause <= 0:
                    break
                time.sleep(min(pause, 1))  # kurz, damit ein geaendertes Limit gleich greift
            return response

        self.session.get = limited_get
        super().run()


class _LimitedManager(DLManager):
    """Legendarys Download-Manager laeuft als eigener Prozess und startet dort die Arbeiter.
    Diese Klasse sorgt dafuer, dass der Prozess dieses Modul laedt - auch in der fertigen exe,
    sonst bekaeme er die Original-Arbeiter ohne Tempolimit."""


def _no_dlc_lookup(self, app_name, platform="Windows"):
    # Legendary sucht nach Installieren/Entfernen DLCs - dafuer laedt es die Metadaten der
    # GESAMTEN Bibliothek (4700+ Eintraege, Epic antwortet mit 429/401) und haengt minutenlang.
    # Der Launcher installiert DLCs nicht ueber Legendary (--skip-dlcs); beim Entfernen liegen
    # DLC-Dateien im Spielordner und gehen mit ihm weg.
    return []


lcore.LegendaryCore.get_game = _get_game
lcore.LegendaryCore.get_cdn_manifest = _cdn_manifest
lcore.LegendaryCore.get_dlc_for_game = _no_dlc_lookup
lcore.LegendaryCore.uninstall_tag = _never_delete_deselected
DLManager.run_analysis = _run_analysis_without_tag_deletes
lcore.DLManager = _LimitedManager
dl_manager.DLWorker = _LimitedWorker

if "download" in sys.argv[1:]:
    # Reiner Download (Fab-Assets in einen Zwischenordner) schreibt nichts in
    # Legendarys Installationsliste - darf also parallel zu einer laufenden
    # Installation arbeiten, statt stundenlang auf deren Sperre zu warten.
    from legendary.lfs.lgndry import LGDLFS
    LGDLFS.lock_installed = lambda self: True

def run(args):
    from legendary.cli import main
    sys.argv = ["legendary"] + list(args)
    main()


if __name__ == "__main__":
    run(sys.argv[1:])

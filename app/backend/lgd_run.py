"""Startet Legendary mit zwei Anpassungen fuer Unreal-Arbeit.

Original-Legendary laedt vor jeder Installation die Metadaten der GESAMTEN
Bibliothek (bei 4700+ Eintraegen -> HTTP 429 von Epic) und blendet dabei alle
Unreal-Engine-Eintraege aus. Hier wird nur der eine benoetigte Eintrag
geholt, Engines eingeschlossen. Aufruf wie das normale legendary-Programm:

    python lgd_run.py -y install <appName> ...
"""
import json
import os
import stat
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


def _grouped_order(manifest, old_manifest=None, install_tags=None, spread=2000):
    """Download-Reihenfolge, bei der deutlich weniger Zwischenspeicher noetig ist.

    Legendary arbeitet die Dateien alphabetisch ab. Ein Download-Stueck, das Dateien an weit
    entfernten Stellen gemeinsam nutzen, bleibt so lange im Speicher, bis die letzte davon fertig
    ist - bei sehr grossen DevKits braucht das 4-5 GB. Hier rueckt jede Datei, die solche Stuecke
    nutzt, direkt hinter die erste Datei mit demselben Stueck. Gemessen am ARK DevKit:
    4103 -> 1102 MiB (nur Grundpaket), 5333 -> 1688 MiB (alles), Rechenzeit 2-4 s.
    Legendarys eigene Umsortierung schaltet sich ab 100.000 Dateien ab (zu langsam)."""
    elements = manifest.file_manifest_list.elements
    tags = None if install_tags is None else ([install_tags] if isinstance(install_tags, str) else list(install_tags))
    unchanged = set()
    if old_manifest is not None:
        old = {fm.filename: fm.sha_hash for fm in old_manifest.file_manifest_list.elements}
        unchanged = {fm.filename for fm in elements if old.get(fm.filename) == fm.sha_hash}

    def wanted(fm):  # dieselbe Regel wie Legendary (leeres Tag = Grundpaket)
        if fm.filename in unchanged:
            return False
        return tags is None or any((t in fm.install_tags) or (not t and not fm.install_tags) for t in tags)

    byname = sorted(elements, key=lambda f: f.filename.lower())
    relevant = [fm for fm in byname if wanted(fm)]
    first, last = {}, {}
    for i, fm in enumerate(relevant):
        for cp in fm.chunk_parts:
            first.setdefault(cp.guid_num, i)
            last[cp.guid_num] = i
    key = {}
    for i, fm in enumerate(relevant):
        anchor = min((first[cp.guid_num] for cp in fm.chunk_parts if last[cp.guid_num] - first[cp.guid_num] > spread),
                     default=i)
        key[fm.filename] = (min(anchor, i), i)
    order = sorted(relevant, key=lambda f: key[f.filename])
    return order + [fm for fm in byname if fm.filename not in key]  # Rest ueberspringt Legendary ohnehin


def _run_analysis_without_tag_deletes(self, *args, **kwargs):
    # Zweiter Loeschweg: Bei jeder Installation/jedem Update mit Komponenten-Auswahl
    # haengt Legendary still Loeschauftraege fuer alle Dateien ausserhalb der Auswahl an
    # (DELETE_FILE|SILENT). Uebersieht die Komponenten-Erkennung je eine Komponente,
    # waeren deren Dateien weg. Nur erlaubt, wenn der Launcher es ausdruecklich will
    # (Komponenten bewusst abwaehlen) - echte Loeschungen entfallener Dateien
    # (nur DELETE_FILE) bleiben unberuehrt.
    if os.environ.get("SICCORA_GROUP_ORDER") == "1":
        # vom Launcher angefordert (nach "zu wenig Zwischenspeicher"): gruppierte Reihenfolge unterschieben -
        # Legendary sortiert die Dateiliste selbst; nur genau dieser Aufruf bekommt unsere Reihenfolge
        import builtins
        manifest = kwargs.get("manifest", args[0] if args else None)
        order = _grouped_order(manifest, kwargs.get("old_manifest"), kwargs.get("file_install_tag"))
        elements = manifest.file_manifest_list.elements
        print(f"[Siccora] Speichersparende Reihenfolge fuer {len(order)} Dateien", flush=True)

        def _sorted(iterable, *a, **kw):
            if iterable is elements:
                return list(order)
            return builtins.sorted(iterable, *a, **kw)
        dl_manager.sorted = _sorted
        try:
            result = _orig_run_analysis(self, *args, **kwargs)
        finally:
            del dl_manager.sorted
    else:
        result = _orig_run_analysis(self, *args, **kwargs)
    if os.environ.get("SICCORA_ALLOW_TAG_DELETE") != "1":
        keep = [t for t in self.tasks if not (isinstance(t, FileTask) and (t.flags & _SILENT_DELETE) == _SILENT_DELETE)]
        dropped = len(self.tasks) - len(keep)
        if dropped:
            self.tasks.clear()
            self.tasks.extend(keep)
            print(f"[Siccora] {dropped} Loeschauftraege fuer nicht gewaehlte Komponenten verworfen")
    # fuer die Abschlusszeile im Launcher: wie viele Dateien dieser Lauf schreibt
    written = sum(1 for t in self.tasks if isinstance(t, FileTask)
                  and t.flags & (TaskFlags.OPEN_FILE | TaskFlags.CREATE_EMPTY_FILE))
    print(f"SICCORA_FILES {written}", flush=True)
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


def is_cache_file(path):
    """Python-Zwischenspeicher (.pyc): legt der Unreal-Editor bei jedem Start neu an. Beim Pruefen
    zaehlen sie sonst immer als "defekt" und werden sinnlos neu geladen - das verwirrt nur."""
    return path.lower().endswith(".pyc")


def _validate_without_cache(base_path, filelist, *args, **kwargs):
    """Wie Legendarys validate_files, aber .pyc gelten ungeprueft als in Ordnung (mit Epics
    Pruefsumme - so laedt die anschliessende Reparatur sie auch nicht neu)."""
    from legendary.models.game import VerifyResult
    keep = []
    for path, sha in filelist:
        if is_cache_file(path):
            yield VerifyResult.HASH_MATCH, path, sha, 0
        else:
            keep.append((path, sha))
    yield from _validate_files(base_path, keep, *args, **kwargs)


def _writable(full):
    """Schreibschutz entfernen. Epic liefert z. B. den Engine-Quelltext (.h/.cpp/.cs) schreibgeschuetzt
    aus - Legendarys os.remove scheitert daran mit "Access is denied" (Deinstallieren liess bei
    UE 5.5 ueber 60 000 Dateien liegen)."""
    try:
        if not os.stat(full).st_mode & stat.S_IWRITE:
            os.chmod(full, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _delete_filelist(path, filenames, *args, **kwargs):
    for name in filenames:
        _writable(os.path.join(path, name))
    return _orig_delete_filelist(path, filenames, *args, **kwargs)


def _delete_folder(path, recursive=True):
    if recursive and os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for name in files:
                _writable(os.path.join(root, name))
    return _orig_delete_folder(path, recursive)


_orig_delete_filelist, _orig_delete_folder = lcore.delete_filelist, lcore.delete_folder
lcore.delete_filelist, lcore.delete_folder = _delete_filelist, _delete_folder

import legendary.cli as lcli  # noqa: E402
_validate_files = lcli.validate_files
lcli.validate_files = _validate_without_cache

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

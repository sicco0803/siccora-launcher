"""Abgleich mit dem Epic Launcher und Komponenten-Verwaltung, als eigener Prozess aufgerufen.

  egl_bridge.py import <appName>          - EGL-Installation an Legendary uebergeben (nur Verwaltungsdaten)
  egl_bridge.py export <appName>          - Legendary-Stand an den Epic Launcher zurueckmelden
  egl_bridge.py settags <appName> <a,b>   - gewaehlte Komponenten setzen (nur Verwaltungsdaten)
  egl_bridge.py prune <appName> <a,b>     - Dateien der abgewaehlten Komponenten a,b loeschen
  egl_bridge.py adopt <appName> <Ordner>  - vorhandene Installation uebernehmen (z. B. aus Heroic)
"""
import collections
import os
import sys

try:  # im Paket (entry.py) als backend-Modul, in der Entwicklung als Skript
    from . import lgd_run  # noqa: F401 - Einzelabruf statt Gesamt-Metadaten, Engines erlaubt
except ImportError:
    import lgd_run  # noqa: F401
from legendary.core import LegendaryCore


def keep_installed_components(core, app):
    """Optionale Komponenten (Engine-Quellcode, Templates ...) vom Datentraeger ablesen.

    Der Epic Launcher speichert die Auswahl nur als interne IDs, die Legendary
    nicht versteht. Ohne diese Erkennung waeren nach der Uebernahme alle
    optionalen Teile "abgewaehlt". Eine Komponente gilt als installiert, wenn
    mehr als die Haelfte ihrer Dateien vorhanden ist.
    """
    igame = core.get_installed_game(app)
    manifest = core.load_manifest(core.get_installed_manifest(app)[0])
    total, present = collections.Counter(), collections.Counter()
    for fm in manifest.file_manifest_list.elements:
        exists = None
        for tag in fm.install_tags or []:
            if exists is None:
                exists = os.path.exists(os.path.join(igame.install_path, fm.filename))
            total[tag] += 1
            present[tag] += exists
    tags = [""] + sorted(t for t in total if present[t] * 2 > total[t])
    igame.install_tags = tags
    core.lgd.set_installed_game(app, igame)
    core.lgd.config.set(app, "install_tags", ",".join(tags))
    core.lgd.save_config()
    print(f"Erkannte Komponenten: {', '.join(t for t in tags if t) or 'keine optionalen'}")


def adopt(core, app, path):
    """Vorhandenen Ordner als Installation uebernehmen - liest nur, veraendert keine Spieldateien.

    Ohne die Pruefung koennte ein falscher Ordner eingetragen und spaeter "repariert" werden.
    Optionale Komponenten zaehlen nicht mit: sie fehlen bei vielen Installationen zu Recht.
    """
    if core.is_installed(app):  # z. B. Fortsetzen nach einer Pause
        print(f"{app} ist bereits uebernommen")
        print("ADOPT_NEEDS_VERIFY" if core.get_installed_game(app).needs_verification else "ADOPT_VERIFIED")
        return 0
    game = core.get_game(app, update_meta=True)
    if not game:
        print(f"ERROR: {app} nicht in der Bibliothek")
        return 1
    manifest, igame = core.import_game(game, path)
    files = manifest.file_manifest_list.elements
    base = [f for f in files if not any(t for t in (f.install_tags or []))] or files
    found = sum(os.path.exists(os.path.join(path, f.filename)) for f in base)
    exe = (manifest.meta.launch_exe or "").lstrip("/")
    print(f"Gefunden: {found} von {len(base)} Dateien")
    if found * 2 < len(base) or (exe and not os.path.exists(os.path.join(path, exe))):
        print("ADOPT_WRONG_FOLDER")
        return 1
    if not core.lgd.lock_installed():
        print("ERROR: installed data lock")
        return 1
    core.install_game(igame)
    keep_installed_components(core, app)
    print("ADOPT_NEEDS_VERIFY" if igame.needs_verification else "ADOPT_VERIFIED")
    return 0


def set_tags(core, app, tags):
    igame = core.get_installed_game(app)
    igame.install_tags = [""] + sorted(t for t in tags if t)
    core.lgd.set_installed_game(app, igame)
    core.lgd.config.set(app, "install_tags", ",".join(igame.install_tags))
    core.lgd.save_config()
    print(f"Gewaehlte Komponenten: {', '.join(igame.install_tags[1:]) or 'keine optionalen'}")


def prune(core, app, removed):
    """Dateien loeschen, die zu einer ABGEWAEHLTEN Komponente gehoeren und zu keiner gewaehlten.

    Dieselbe Regel wie in components.summarize() - geloescht wird also genau,
    was der Nutzer in der Vorschau bestaetigt hat. Dateien von Komponenten, die
    nie gewaehlt waren, und Basisdateien bleiben immer stehen.
    """
    igame = core.get_installed_game(app)
    selected = {t for t in igame.install_tags if t}
    removed = set(removed) - selected
    if not removed:
        print("Nichts zu entfernen")
        return
    root = os.path.abspath(igame.install_path)
    manifest = core.load_manifest(core.get_installed_manifest(app)[0])
    targets = [fm for fm in manifest.file_manifest_list.elements
               if fm.install_tags and removed & set(fm.install_tags) and not selected & set(fm.install_tags)]
    done = size = 0
    dirs = set()
    for i, fm in enumerate(targets, 1):
        path = os.path.abspath(os.path.join(root, fm.filename))
        if os.path.commonpath([root, path]) != root:
            continue  # nie ausserhalb des Installationsordners
        if os.path.isfile(path):
            try:
                os.remove(path)
                done += 1
                size += fm.file_size
                dirs.add(os.path.dirname(path))
            except OSError as e:
                print(f"WARNING: {fm.filename}: {e}")
        if i % 2000 == 0:
            print(f"PRUNE {i}/{len(targets)}", flush=True)
    # leer gewordene Ordner aufraeumen (nur innerhalb, von innen nach aussen)
    for d in sorted(dirs, key=len, reverse=True):
        while d != root and os.path.commonpath([root, d]) == root:
            try:
                os.rmdir(d)  # schlaegt fehl, sobald der Ordner nicht leer ist
            except OSError:
                break
            d = os.path.dirname(d)
    print(f"PRUNED {done} {size}", flush=True)


def main():
    action, app = sys.argv[1], sys.argv[2]
    core = LegendaryCore(timeout=120)  # Epics Asset-Liste ist sehr gross
    if not core.login():
        print("ERROR: Nicht angemeldet")
        return 1
    if action == "adopt":
        code = adopt(core, app, sys.argv[3])
        if code:
            return code
    elif action == "import":
        if core.is_installed(app):
            print(f"{app} ist bereits uebernommen")
            return 0
        core.get_assets(update_assets=True)
        core.egl.read_manifests()
        core.egl_import(app)
        if not core.is_installed(app):
            print(f"ERROR: Uebernahme von {app} fehlgeschlagen")
            return 1
        keep_installed_components(core, app)
    elif action == "export":
        if not core.egl.programdata_path or not os.path.isdir(core.egl.programdata_path):
            print("Kein Epic Launcher installiert - nichts zurueckzumelden")
            return 0
        if not core.is_installed(app):
            print(f"{app} ist nicht ueber Legendary installiert - nichts zurueckzumelden")
            return 0
        core.get_game(app, update_meta=True)
        core.egl_export(app)
    elif action in ("settags", "prune"):
        if not core.is_installed(app):
            print(f"ERROR: {app} ist nicht uebernommen")
            return 1
        tags = [t for t in (sys.argv[3] if len(sys.argv) > 3 else "").split(",") if t]
        if action == "settags":
            set_tags(core, app, tags)
        else:
            prune(core, app, tags)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

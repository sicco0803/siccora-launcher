"""Siccora Launcher - schlanker Ersatz fuer den Epic Games Launcher."""
import faulthandler
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser

import requests
import webview

from backend import autostart, cleanup, components, crashes, debuglog, freefab, launch, projects, selfupdate, settings
from backend.tray import Tray
from backend.downloads import Downloads, hide_servers
from backend.epic import DATA_DIR, LOGIN_URL, EpicService
from backend.storepanel import StorePanel, guard_main
from backend.fab_install import KINDS, compatibility, read_project
from backend.fab_install import plan as fab_plan
from backend.i18n import set_lang, tr
from backend.preview import _installed_manifest, update_preview, progress as preview_progress
from backend import vault
from backend.vault import asset_updates, epic_cached, epic_vault_dirs

# im fertigen Paket liegen ui/ usw. im Entpack-Ordner von PyInstaller
HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
APP_VERSION = "1.0.8"

# Sprache fest in der Adresse: Fab ignoriert die Browsersprache und entscheidet sonst
# selbst (bei Mike kam so eine fremde Sprache heraus); Fab: ?lang=de, Epic: /de/ bzw. /en-US/
STORES = {
    "fab": "https://www.fab.com/?lang={fab}",
    "epic": "https://store.epicgames.com/{epic}/",
}
STORE_LANG = {"de": {"fab": "de", "epic": "de"}, "en": {"fab": "en", "epic": "en-US"},
              "fr": {"fab": "fr", "epic": "fr"}, "es": {"fab": "es", "epic": "es-ES"},
              "it": {"fab": "it", "epic": "it"}, "pl": {"fab": "pl", "epic": "pl"},
              "pt": {"fab": "pt", "epic": "pt-BR"}, "nl": {"fab": "en", "epic": "en-US"}}  # Fab/Epic: kein Niederlaendisch
BROWSER_LANG = {"de": "de-DE", "en": "en-US", "fr": "fr-FR", "es": "es-ES", "it": "it-IT", "pl": "pl-PL",
                "pt": "pt-PT", "nl": "nl-NL"}


def _safe(fn):
    """Fehler als Daten an die Oberflaeche geben statt die App zu stoppen."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            traceback.print_exc()
            debuglog.exception("api", f"{fn.__name__} fehlgeschlagen")
            return {"error": hide_servers(f"{type(e).__name__}: {e}")}
    wrapper.__name__ = fn.__name__
    return wrapper


class Api:
    def __init__(self):
        set_lang(settings.get("language") or "en")
        self._epic = EpicService()
        self._downloads = Downloads(on_change=self._after_job)
        self._components = {}  # appName -> (Zeitpunkt, letzte Komponenten-Analyse)
        self._store = None  # StorePanel, sobald das Fenster existiert (main)
        self._account = None  # eigenes StorePanel fuer die Kontoseite
        self._window = None  # Hauptfenster (main)
        self._login_window = None
        self._close_confirmed = False
        self._tray = None  # Symbol im Infobereich (main)

    def _after_job(self, job):
        """Nach einer Aenderung am Element den Komponenten-Stand im Hintergrund neu pruefen,
        damit "Optionen" beim naechsten Oeffnen sofort da ist."""
        app = job["appName"]
        fab = job.get("fab") or {}
        if job["action"] == "fab" and job["status"] == "done" and fab.get("kind") == "COMPLETE_PROJECT":
            projects.register_created(fab["target"], fab.get("projectName"))
            return
        self._components.pop(app, None)
        if job["action"] == "uninstall":
            components.forget(app)
            return
        if job["status"] != "done" or job["action"] not in ("install", "update", "repair", "modify"):
            return
        if job["action"] in ("install", "update"):
            threading.Thread(target=self._follow_dlcs, args=(job,), daemon=True).start()
            threading.Thread(target=lambda: components.refresh_options(self._epic), daemon=True).start()
        comp = job.get("components") or {}
        if job["action"] == "modify" and components.record_change(
                self._epic, app, comp.get("selected", []), comp.get("removed", []), comp.get("adding", False)):
            return  # Stand direkt nachgefuehrt - sofort aktuell
        threading.Thread(target=lambda: components.analyse(self._epic, app, refresh=True), daemon=True).start()

    def _follow_dlcs(self, job):
        """Wie der Epic Launcher: nach der Installation eines Spiels seine DLCs mitinstallieren,
        nach einem Update die DLCs mit neuer Version nachziehen."""
        try:
            data = self._epic.library()
            dlcs = [i for i in data["items"] if i["kind"] == "dlc" and i.get("parent") == job["appName"]]
            for d in dlcs:
                if job["action"] == "install" and not d["installed"]:
                    self.install(d["appName"])
                elif d["installed"] and d.get("updateAvailable"):
                    self._queue_existing("update", d["appName"])
            if dlcs:
                debuglog.log("dlc", "Folgeauftraege", game=job["appName"], action=job["action"], dlcs=len(dlcs))
        except Exception:
            debuglog.exception("dlc", "DLC-Folgeauftraege fehlgeschlagen")

    @_safe
    def dlcs(self, app_name):
        return {"items": self._dlcs_of(app_name)}

    # --- Einstellungen -------------------------------------------------------
    @_safe
    def settings(self):
        return {**settings.load(), "workerChoices": settings.WORKER_CHOICES, "speedChoices": settings.SPEED_CHOICES,
                "epicVaultDirs": epic_vault_dirs(), "autostart": autostart.get()}

    @_safe
    def save_settings(self, changes):
        changes = dict(changes or {})
        if "autostart" in changes:  # steht in Windows, nicht in settings.json
            if changes["autostart"] not in autostart.MODES:
                return {"error": tr("Ungültige Autostart-Einstellung.")}
            autostart.set_mode(changes.pop("autostart"))
        result = settings.save(changes)
        if "error" not in result and "language" in changes:
            set_lang(result["language"])
            if self._tray:
                self._tray.set_texts(_tray_texts())
        return {**result, "autostart": autostart.get()} if "error" not in result else result

    @_safe
    def set_language(self, lang):
        return self.save_settings({"language": lang})

    @_safe
    def account(self):
        return self._epic.account()

    @_safe
    def open_login_page(self):
        webbrowser.open(LOGIN_URL)
        return {"ok": True}

    @_safe
    def start_login(self):
        """Epics Anmeldefenster im Launcher - wie bei Heroic, ohne Code kopieren.

        Nach dem Login leitet Epic auf /id/api/redirect weiter; die Seite enthaelt
        den einmaligen authorizationCode. Den lesen wir dort aus, melden an und
        schliessen das Fenster. Das Passwort geht nur an Epic.
        """
        if self._login_window is not None:
            return {"ok": True}
        win = webview.create_window(tr("Mit Epic anmelden"), self._epic.core.egs.get_auth_url(),
                                    width=520, height=780, background_color="#15110E")
        self._login_window = win

        def on_loaded():
            try:
                url = win.get_current_url() or ""
            except Exception:
                return
            # Pfad UND Server pruefen: die Anmeldeseite traegt die Weiterleitung als Parameter in ihrer
            # Adresse, und eine fremde Seite mit gleichem Pfad duerfte keinen Code unterschieben
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != "www.epicgames.com" \
                    or not parsed.path.startswith("/id/api/redirect"):
                return
            result = self._epic.login_with_text(win.evaluate_js("document.body.innerText") or "")
            self._login_window = None
            win.destroy()
            self._window.evaluate_js(f"onEpicLogin({json.dumps(result)})")

        def on_closed():
            self._login_window = None

        win.events.loaded += on_loaded
        win.events.closed += on_closed
        return {"ok": True}

    @_safe
    def login(self, text):
        return self._epic.login_with_text(text)

    @_safe
    def logout(self):
        # auch im eingebauten Browser abmelden (Epic, Fab) - sonst meldet die naechste
        # Anmeldung ohne Rueckfrage wieder dasselbe Konto an
        if self._window is not None:
            self._window.clear_cookies()
        return self._epic.logout()

    @_safe
    def library(self, refresh=False):
        return self._epic.library(refresh)

    @_safe
    def check_updates(self, force=False):
        t = time.time()
        res = self._epic.check_updates(min_age=0 if force else 1800)
        if res:
            debuglog.log("library", "Abgleich", force=force, s=round(time.time() - t, 1),
                         updates=[i["appName"] for i in res["items"] if i.get("updateAvailable")], neu=res.get("newItems"))
        return res

    @_safe
    def update_preview_progress(self):
        return dict(preview_progress)

    @_safe
    def update_preview(self, app_name):
        t = time.time()
        res = update_preview(self._epic, app_name)
        debuglog.log("preview", app_name, s=round(time.time() - t, 1),
                     **{k: res.get(k) for k in ("oldVersion", "newVersion", "upToDate", "acknowledged", "changed", "added",
                                                "removed", "downloadMb", "error") if k in res})
        return res

    # --- Komponenten (Optionen) ------------------------------------------------
    @_safe
    def components(self, app_name, refresh=False):
        result = components.analyse(self._epic, app_name, refresh)
        if "error" not in result:
            self._components[app_name] = (time.time(), result)
        return result

    @_safe
    def components_summary(self, app_name, selected):
        cached = self._components.get(app_name)
        if not cached:
            return {"error": tr("Bitte Optionen neu öffnen.")}
        return components.summarize(cached[1], selected)

    @_safe
    def modify_components(self, app_name, selected):
        # Grundlage ist genau die Analyse, deren Zahlen der Nutzer gesehen hat (max. 30 Min. alt)
        cached = self._components.get(app_name)
        if not cached or time.time() - cached[0] > 1800:
            return {"error": tr("Bitte Optionen neu öffnen.")}
        analysis = cached[1]
        plan = components.summarize(analysis, selected)
        if not plan["added"] and not plan["removed"]:
            return {"error": tr("Keine Änderung ausgewählt.")}
        if plan["download"] > analysis["freeSpace"] + plan["freed"]:
            return {"error": tr("Nicht genug Speicherplatz.")}
        item = self._epic.find(app_name)
        del self._components[app_name]
        return self._downloads.add("modify", app_name, item["title"] if item else app_name,
                                   from_egl=analysis["source"] == "egl", components={
                                       "selected": sorted(selected), "removed": plan["removed"],
                                       # nur bei neu gewaehlten Komponenten laden - ein reines Abwaehlen
                                       # soll nie nebenbei ein ausstehendes Update starten
                                       "adding": bool(plan["added"])})

    # --- Unreal-Projekte ---------------------------------------------------
    def _engines(self):
        """Installierte Engines und DevKits (fuer Zuordnung und Projektsuche)."""
        lib = self._epic.library()["items"]
        return [{"appName": i["appName"], "title": i["title"], "path": i["path"], "kind": i["kind"]}
                for i in lib if i["kind"] in ("engine", "tool") and i["installed"] and i.get("path")]

    def _protected(self):
        """Ordner, die beim Projekt-Loeschen nie betroffen sein duerfen: alles Installierte
        (Spiele, Engines, DevKits) und die Asset-Zwischenordner."""
        lib = self._epic.library()["items"]
        paths = [i["path"] for i in lib if i.get("installed") and i.get("path")]
        return paths + list(epic_vault_dirs()) + [settings.get("vaultDir")]

    @_safe
    def projects(self, refresh=False):
        items = projects.cached()
        if refresh or not items:
            items = projects.scan(self._engines(), self._protected())
        for p in items:
            p["deleteBlockText"] = tr(p["deleteBlock"]) if p.get("deleteBlock") else None
        return {"items": items, "updated": time.time()}

    @staticmethod
    def _tr_result(res):
        if res.get("error"):
            res["error"] = tr(res["error"])
        if res.get("blocked"):
            res["blockedText"] = tr(res["blocked"])
        return res

    @_safe
    def delete_project_info(self, uproject):
        return self._tr_result(projects.delete_info(uproject, self._protected()))

    @_safe
    def delete_project(self, uproject, confirm_name):
        info = projects.find(uproject)
        if not info or confirm_name != info["name"]:
            return {"error": tr("Bestätigung passt nicht zum Projektnamen.")}
        return self._tr_result(projects.delete(uproject, self._protected()))

    @_safe
    def project_thumb(self, uproject):
        return {"url": projects.thumbnail(uproject)}

    @_safe
    def open_project(self, uproject):
        proj = projects.open_project(uproject)
        if not proj:
            return {"error": tr("Projekt nicht gefunden.")}
        # fuer "Zuletzt gestartet": die Engine bzw. das DevKit dahinter merken
        eng = next((e for e in self._engines() if proj.get("enginePath")
                    and os.path.normcase(e["path"]) == os.path.normcase(proj["enginePath"])), None)
        if eng:
            launch.record(eng["appName"], eng["title"], eng["kind"])
        return {"ok": True}

    @_safe
    def rename_project(self, uproject, name):
        if not projects.rename(uproject, name):
            return {"error": tr("Projekt nicht gefunden.")}
        return self.projects()

    @_safe
    def add_project(self):
        picked = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, file_types=(tr("Unreal-Projekt") + " (*.uproject)",))
        if not picked:
            return {"cancelled": True}
        projects.add_project(picked[0])
        return self.projects(refresh=True)

    @_safe
    def add_project_folder(self):
        picked = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if not picked:
            return {"cancelled": True}
        projects.add_folder(picked[0])
        return self.projects(refresh=True)

    @_safe
    def hide_project(self, uproject):
        projects.hide(uproject)
        return self.projects(refresh=True)

    # --- Fab-Assets in Projekte/Engines -----------------------------------
    @_safe
    def local_assets(self):
        return {"items": vault.local_assets(self._epic.core, self._epic.fab_cached()["items"])}

    @_safe
    def delete_local_asset(self, key):
        lib = self._epic.library()["items"]
        installed = [i["path"] for i in lib if i.get("installed") and i.get("path")]
        res = vault.delete_local(key, installed, self._downloads.paths_in_use())
        if res.get("error"):
            res["error"] = tr(res["error"])
        return res

    @_safe
    def fab_options(self, asset_id):
        item = self._epic.fab_item(asset_id)
        if not item:
            return {"error": tr("Asset nicht gefunden.")}
        if not projects.cached():
            projects.scan(self._engines(), self._protected())
        # Engines und DevKits mit ihrer UE-Version (Software ohne UE-Version scheidet aus)
        engines = [{**e, "ue": ue} for e in self._engines() if (ue := projects.engine_version(e["path"]))]
        return {"item": item, "action": tr(KINDS.get(item.get("kind"), "")), "engines": engines,
                "projects": projects.targets()}

    @_safe
    def choose_project(self):
        picked = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, file_types=(tr("Unreal-Projekt") + " (*.uproject)",))
        if not picked:
            return {"cancelled": True}
        return projects.describe(picked[0], self._engines()) or read_project(picked[0])

    @_safe
    def choose_folder(self):
        picked = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return {"path": picked[0]} if picked else {"cancelled": True}

    @_safe
    def fab_plan(self, asset_id, artifact_id, target):
        p = fab_plan(self._epic, asset_id, artifact_id, target)
        if "error" not in p:
            p["compat"] = self._fab_compat(p["kind"], asset_id, artifact_id, target)
        return p

    def _fab_compat(self, kind, asset_id, artifact_id, target):
        """Versionspruefung im Backend - die Oberflaeche kann sie nicht umgehen."""
        if kind == "COMPLETE_PROJECT":
            return {"state": "ok"}  # das Projekt entsteht neu, die Version waehlt der Nutzer
        ue = projects.engine_version(target)
        if kind == "ASSET_PACK":
            found = glob.glob(os.path.join(glob.escape(target), "*.uproject"))
            info = projects.describe(found[0], self._engines()) if found else None
            ue = info.get("ueVersion") if info else None
        return compatibility(self._epic.fab_item(asset_id), artifact_id, ue)

    @_safe
    def fab_install(self, asset_id, artifact_id, target, overwrite=False, override=False):
        p = fab_plan(self._epic, asset_id, artifact_id, target)
        if "error" in p:
            return p
        if self._fab_compat(p["kind"], asset_id, artifact_id, target)["state"] != "ok" and not override:
            return {"error": tr("Die Asset-Version passt nicht zur Engine des Ziels.")}
        return self._downloads.add("fab", artifact_id, p["title"], label=p["actionKey"], fab={
            "kind": p["kind"], "target": target, "projectName": p["projectName"], "overwrite": bool(overwrite),
            "source": p["source"], "sourcePath": p["sourcePath"], "version": p["version"], "viaFab": p.get("viaFab"),
            "keep": settings.get("keepAssets")})

    @_safe
    def fab(self, refresh=False):
        # welche Versionen schon in Epics Vault-Cache liegen -> auch ohne Download installierbar
        return {**self._epic.fab(refresh), "epicCached": sorted(epic_cached())}

    @_safe
    def open_store(self, which):
        url = STORES.get(which)
        if url:
            lang = STORE_LANG.get(settings.get("language") or "en", STORE_LANG["en"])
            webview.create_window(tr("Store - {name}", name=which.capitalize()),
                                  url.format(**lang), width=1280, height=860)
        return {"ok": bool(url)}

    # --- Store rechts im Hauptfenster -----------------------------------------
    @_safe
    def store_home(self, which):
        url = STORES.get(which)
        lang = STORE_LANG.get(settings.get("language") or "en", STORE_LANG["en"])
        return {"url": url.format(**lang) if url else None}

    @_safe
    def account_url(self):
        """Epics Kontoseite in der Launcher-Sprache."""
        lang = STORE_LANG.get(settings.get("language") or "en", STORE_LANG["en"])["fab"]
        return {"url": f"https://www.epicgames.com/account/personal?lang={lang}"}

    def _panel(self, which):
        """Store und Konto haben je ein eigenes Browser-Element, damit sich ihre Verlaeufe nicht mischen."""
        return self._account if which == "account" else self._store

    @_safe
    def store_show(self, url, rect, which="store"):
        panel = self._panel(which)
        return panel.show(url, rect) if panel else {"error": "no window"}

    @_safe
    def store_resize(self, rect, which="store"):
        panel = self._panel(which)
        return panel.resize(rect) if panel else {"ok": False}

    @_safe
    def store_hide(self, which="store"):
        panel = self._panel(which)
        return panel.hide() if panel else {"ok": False}

    @_safe
    def store_go(self, action, which="store"):
        panel = self._panel(which)
        return panel.go(action) if panel else {"ok": False}

    @_safe
    def store_current(self, which="store"):
        panel = self._panel(which)
        return panel.current() if panel else {"url": None}

    # --- Launcher-Updates (GitHub-Releases) ------------------------------------
    @_safe
    def self_update(self, force=False):
        res = selfupdate.check(APP_VERSION, force)
        # nur die installierte exe kann sich selbst ersetzen - aus dem Quellcode (Start.bat) nur Hinweis
        res["canInstall"] = bool(getattr(sys, "frozen", False) and res["setup"])
        return res

    @_safe
    def debug_event(self, kind, text):
        """Fehler aus der Oberflaeche (nur mit debug.flag protokolliert)."""
        debuglog.log("ui", str(kind)[:40], text=str(text)[:2000])
        return {"ok": True}

    def self_update_progress(self):
        return dict(selfupdate.progress)

    @_safe
    def install_self_update(self):
        info = selfupdate.check(APP_VERSION)
        debuglog.log("selfupdate", "Update angefordert", current=APP_VERSION, latest=info.get("latest"))
        if not (getattr(sys, "frozen", False) and info["setup"]):
            return {"error": tr("Kein Update zum Installieren.")}
        try:
            path = selfupdate.download(info)
        except (ValueError, requests.RequestException) as e:
            debuglog.exception("selfupdate", "Download fehlgeschlagen")
            return {"error": tr(str(e)) if isinstance(e, ValueError) else tr("Update konnte nicht geladen werden.")}
        selfupdate.progress["phase"] = "install"
        debuglog.log("selfupdate", "Setup gestartet, Launcher wird beendet", path=path)
        selfupdate.install(path)
        # Launcher schliessen, damit das Setup die Dateien ersetzen kann (Downloads werden pausiert)
        self._close_confirmed = True
        threading.Thread(target=self._window.destroy, daemon=True).start()
        return {"ok": True}

    @_safe
    def open_url(self, url):
        if url and url.startswith("https://"):
            webbrowser.open(url)
        return {"ok": True}

    # --- Downloads -----------------------------------------------------------
    @_safe
    def choose_install_dir(self):
        picked = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if not picked:
            return {"cancelled": True}
        return settings.save({"installDir": picked[0]})

    @_safe
    def install(self, app_name, base_dir=None, remember=False):
        """base_dir: Ordner nur fuer diese Installation (sonst der Standard aus den Einstellungen);
        remember: diesen Ordner ausserdem als neuen Standard speichern."""
        item = self._epic.find(app_name)
        if not item:
            return {"error": tr("Eintrag nicht in der Bibliothek gefunden.")}
        if item["kind"] == "dlc":  # landet im Ordner des Spiels
            parent = self._epic.installed().get(item["parent"])
            if not parent:
                return {"error": tr("Bitte zuerst das Spiel installieren.")}
            return self._downloads.add("install", app_name, item["title"], parent_from_egl=parent["source"] == "egl",
                                       parent=item["parent"])
        if base_dir:
            if remember:  # prueft den Ordner gleich mit (lokal, vorhanden)
                saved = settings.save({"installDir": base_dir})
                if "error" in saved:
                    return saved
            elif not settings.local_dir(base_dir):
                return {"error": tr("Ordner existiert nicht oder ist ein Netzwerkpfad.")}
            base = os.path.abspath(base_dir)
        else:
            base = settings.get("installDir")
        if not base:
            return {"needsInstallDir": True}
        return self._downloads.add("install", app_name, item["title"], base_path=base)

    @_safe
    def disk_free(self, path):
        """Freier Platz auf dem Laufwerk eines Ordners (fuer das Installieren-Fenster)."""
        if not settings.local_dir(path):
            return {"freeGb": None}
        return {"freeGb": round(shutil.disk_usage(path).free / 1024 ** 3)}

    def _all_projects(self):
        """Eigene Projekte plus die Projekte in Engines und DevKits (z. B. Projects/ShooterGame)."""
        projs = list(self.projects()["items"])
        for e in self._engines():
            projs += [{**p, "displayName": f"{e['title']} · {p['name']}"} for p in cleanup.kit_projects(e["path"])]
        return projs

    @_safe
    def crash_reports(self):
        return crashes.scan(self._all_projects())

    def _private_names(self):
        """Namen, die nicht an eine KI gehen: Windows-Konto, Rechnername, Epic-Anzeigename."""
        names = [os.environ.get("USERNAME"), os.environ.get("COMPUTERNAME")]
        try:
            names.append(self._epic.account().get("name"))
        except Exception:
            pass
        return [n for n in names if n]

    @_safe
    def ai_prompt(self, text):
        return {"text": crashes.scrub(str(text or ""), self._private_names())}

    @_safe
    def ask_ai(self, provider, text):
        """Oeffnet den gewaehlten KI-Dienst im Browser mit der Frage - nur feste Adressen, Text erneut bereinigt."""
        url = crashes.ai_url(provider, crashes.scrub(str(text or ""), self._private_names()))
        if not url:
            return {"error": tr("Unbekannter Anbieter.")}
        webbrowser.open(url)
        return {"ok": True}

    # --- Speicher aufraeumen ---------------------------------------------------
    @_safe
    def cleanup_scan(self):
        projs = self._all_projects()
        installed = self._epic.installed()
        installs = {app: v["path"] for app, v in installed.items()}

        def load(app):
            try:
                return _installed_manifest(self._epic, app, installed[app])
            except Exception:  # ohne Dateiliste wird das Projekt nicht angeboten
                traceback.print_exc()
                return None
        kits = [{"dir": e["path"], "name": e["title"], "displayName": e["title"]} for e in self._engines()]
        return cleanup.scan(projs, installs, load, kits)

    def cleanup_progress(self):
        return dict(cleanup.progress)

    @_safe
    def cleanup_run(self, ids):
        res = cleanup.clean(list(ids or []))
        return {"error": tr("Bitte zuerst den Unreal Editor schließen.")} if res.get("blocked") else res

    @_safe
    def adopt_options(self):
        return {"heroic": self._epic.heroic_installed()}

    @_safe
    def adopt_install(self, app_name, path):
        """Vorhandenen Ordner (z. B. aus Heroic oder einem anderen PC) als Installation uebernehmen."""
        item = self._epic.find(app_name)
        if not item or item["kind"] not in ("engine", "tool", "game"):
            return {"error": tr("Eintrag nicht in der Bibliothek gefunden.")}
        installed = self._epic.installed()
        if app_name in installed:
            return {"error": tr("Diese Installation ist schon im Launcher.")}
        folder = os.path.abspath(path or "")
        if not path or path.startswith(("\\\\", "//")) or not os.path.isdir(folder):
            return {"error": tr("Ordner existiert nicht oder ist ein Netzwerkpfad.")}
        if os.path.dirname(folder) == folder:
            return {"error": tr("Bitte den Hauptordner der Installation wählen, nicht das ganze Laufwerk.")}
        key = os.path.normcase(folder)
        users = [app for app, local in installed.items() if os.path.normcase(os.path.abspath(local["path"])) == key]
        if users:  # Plugins teilen sich den Ordner der Engine - den lesbaren Namen nennen
            names = [i["title"] for i in map(self._epic.find, users) if i]
            return {"error": tr("Dieser Ordner gehört schon zu {title}.", title=names[0] if names else users[0])}
        return self._downloads.add("adopt", app_name, item["title"], base_path=folder)

    @_safe
    def update(self, app_name):
        return self._queue_existing("update", app_name)

    @_safe
    def repair(self, app_name):
        return self._queue_existing("repair", app_name)

    @_safe
    def uninstall(self, app_name):
        # erst die DLCs des Spiels sauber austragen (sie liegen in seinem Ordner)
        installed = self._epic.installed()
        for d in self._dlcs_of(app_name):
            if d["appName"] in installed and installed[d["appName"]]["source"] == "legendary":
                self._downloads.add("uninstall", d["appName"], d["title"])
        return self._queue_existing("uninstall", app_name)

    def _dlcs_of(self, app_name):
        data = self._epic.library()
        return [i for i in data["items"] if i["kind"] == "dlc" and i.get("parent") == app_name]

    def _queue_existing(self, action, app_name):
        local = self._epic.installed().get(app_name)
        if not local:
            return {"error": tr("Nicht installiert.")}
        item = self._epic.find(app_name)
        title = item["title"] if item else app_name
        return self._downloads.add(action, app_name, title, from_egl=local["source"] == "egl")

    @_safe
    def downloads_list(self):
        return {"jobs": self._downloads.list()}

    @_safe
    def close_app(self):
        """Schliessen bestaetigt (Rueckfrage laufende Downloads)."""
        self._close_confirmed = True
        threading.Thread(target=self._window.destroy, daemon=True).start()
        return {"ok": True}

    @_safe
    def download_log(self, job_id):
        return self._downloads.log(job_id)

    @_safe
    def cancel_download(self, job_id):
        return self._downloads.cancel(job_id)

    @_safe
    def pause_download(self, job_id):
        return self._downloads.pause(job_id)

    @_safe
    def resume_download(self, job_id):
        return self._downloads.resume(job_id)

    @_safe
    def clear_downloads(self):
        return self._downloads.clear_finished()

    @_safe
    def launch_app(self, app_name):
        item = next((i for i in self._epic.library()["items"] if i["appName"] == app_name), None)
        if not item or not item["installed"]:
            return {"error": tr("Nicht installiert.")}
        if item["kind"] == "game":
            problem = launch.start_game(app_name, item["title"], item.get("source"))
            return {"error": tr("Spiel konnte nicht gestartet werden: {msg}", msg=problem)} if problem else {"ok": True}
        if not launch.start(app_name, item["title"], item["kind"], item["path"]):
            return {"error": tr("Startprogramm nicht gefunden.")}
        return {"ok": True}

    # --- Startseite -----------------------------------------------------------
    @_safe
    def home(self):
        lib = self._epic.library()["items"]
        by_app = {i["appName"]: i for i in lib}
        startable = [i for i in lib if i["installed"] and i["kind"] in ("engine", "tool")]

        # Zuletzt gestartet: ueber den Launcher gestartet ODER ein Projekt damit geoeffnet
        # (der Editor merkt sich geoeffnete Projekte - so zaehlen auch Starts ausserhalb)
        last = {}
        for h in launch.history():
            if h["appName"] in by_app:
                last[h["appName"]] = max(last.get(h["appName"], 0), h["time"])
        projs = projects.cached() or projects.scan(self._engines(), self._protected())
        use = projects.engine_use(self._engines())
        for i in startable:
            ts = use.get(os.path.normcase(os.path.abspath(i["path"])))
            if ts:
                last[i["appName"]] = max(last.get(i["appName"], 0), ts)
        recent = [{"appName": a, "title": by_app[a]["title"], "kind": by_app[a]["kind"], "time": t,
                   "image": by_app[a].get("image"), "installed": by_app[a]["installed"], "path": by_app[a]["path"]}
                  for a, t in sorted(last.items(), key=lambda x: -x[1]) if by_app[a]["installed"]
                  and (by_app[a]["kind"] != "game" or settings.get("showGames"))][:3]

        # zuletzt benutzt: geoeffnet oder neu angelegt - was spaeter war
        newest = sorted(projs, key=lambda p: -max(p.get("lastOpened") or 0, p.get("created") or 0))[:3]

        updates = [{"appName": i["appName"], "title": i["title"], "kind": i["kind"], "image": i.get("image"),
                    "version": i.get("version"), "latest": i.get("latest")}
                   for i in lib if i["installed"] and i.get("updateAvailable")
                   and (i["kind"] not in ("game", "dlc") or settings.get("showGames"))]
        try:
            fab = self._epic.fab_cached()  # nie laden: die Startseite soll sofort da sein
            titles = {v["artifactId"]: it["title"] for it in fab["items"] for v in it["versions"]}
            assets = asset_updates(self._epic.core, titles)
            counts = {"fab": len(fab["items"])}
        except Exception:  # Fab nicht erreichbar -> Startseite trotzdem zeigen
            assets, counts = [], {"fab": None}
        counts.update(engines=sum(1 for i in startable if i["kind"] == "engine"),
                      tools=sum(1 for i in startable if i["kind"] == "tool"), projects=len(projs))
        return {"recent": recent, "projects": newest, "updates": updates, "assetUpdates": assets,
                "counts": counts, "libraryUpdated": (lambda d: d.get("checked") or d.get("updated"))(self._epic.library())}

    @_safe
    def home_storage(self):
        """Laufwerke, auf denen Installiertes liegt, und Platz der Fab-Downloads."""
        lib = self._epic.library()["items"]
        roots = {os.path.splitdrive(p)[0].upper() + os.sep for p in
                 [i["path"] for i in lib if i.get("installed") and i.get("path")] + list(epic_vault_dirs())
                 + [settings.get("installDir")] if p and os.path.splitdrive(p)[0]}
        drives = []
        for root in sorted(roots):
            try:
                use = shutil.disk_usage(root)
            except OSError:  # Laufwerk gerade nicht da
                continue
            drives.append({"drive": root.rstrip(os.sep), "totalGb": round(use.total / 1024 ** 3), "freeGb": round(use.free / 1024 ** 3),
                           "usedPct": round(100 * (use.total - use.free) / use.total) if use.total else 0})
        return {"drives": drives, "vaultMb": round(vault.used_space() / 1048576)}

    @_safe
    def free_assets(self, refresh=False):
        return freefab.current([i.get("url") for i in self._epic.fab_cached()["items"]], refresh)

    @_safe
    def open_folder(self, path):
        # nur lokale, vollstaendige Ordnerpfade, keine Netzwerkpfade (\\server\...) - und immer nur der
        # Explorer: ein Ordner wird angezeigt, nie etwas ausgefuehrt
        path = os.path.normpath(str(path or ""))
        if os.path.isabs(path) and not path.startswith(("\\\\", "//")) and os.path.isdir(path):
            explorer = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe")  # voller Pfad
            subprocess.Popen([explorer, path], close_fds=True)
        return {"ok": True}


def _quiet(fn, *args):
    """Hintergrundarbeit, deren Fehler nur ins Protokoll gehen."""
    try:
        fn(*args)
    except Exception:
        traceback.print_exc()
        debuglog.exception("background", f"{getattr(fn, '__name__', fn)} fehlgeschlagen")


class _Redacted:
    """Schreibt ins Protokoll, aber ohne Server-Adressen (koennen Zugangs-Token enthalten) -
    das Protokoll wird bei Problemen evtl. weitergegeben."""

    def __init__(self, f):
        self._f = f

    def write(self, text):
        return self._f.write(hide_servers(text))

    def flush(self):
        self._f.flush()

    def fileno(self):  # faulthandler schreibt direkt in die Datei (nur Python-Stapel, keine Adressen)
        return self._f.fileno()

    def __getattr__(self, name):
        return getattr(self._f, name)


def _crash_log():
    """Abstuerze und Fehler in launcher.log festhalten - im Fensterbetrieb gibt es keine Konsole."""
    path = os.path.join(DATA_DIR, "launcher.log")
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        if os.path.getsize(path) > 1024 * 1024:
            os.replace(path, path + ".old")
    except OSError:
        pass
    log = _Redacted(open(path, "a", encoding="utf-8", buffering=1))
    print(f"=== Start {time.strftime('%Y-%m-%d %H:%M:%S')} Version {APP_VERSION} ===", file=log)
    sys.stderr = log
    if sys.stdout is None:
        sys.stdout = log
    faulthandler.enable(log)  # auch harte Abstuerze (Python-Stack der Threads)
    sys.excepthook = lambda *e: traceback.print_exception(*e, file=log)
    threading.excepthook = lambda a: traceback.print_exception(a.exc_type, a.exc_value, a.exc_traceback, file=log)


_instance = {}  # Windows-Handles der laufenden Instanz (duerfen nicht freigegeben werden)


def _first_instance(on_wake):
    """Nur ein Launcher je Benutzer und Datenordner. Laeuft schon einer (z. B. still im
    Infobereich nach dem Windows-Start), wird der nach vorn geholt und False geliefert."""
    import ctypes
    import hashlib
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = k32.CreateEventW.restype = k32.OpenEventW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    k32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
    k32.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
    k32.SetEvent.argtypes = [ctypes.c_void_p]
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    tag = hashlib.sha1(os.path.normcase(os.path.abspath(DATA_DIR)).encode()).hexdigest()[:16]
    mutex = k32.CreateMutexW(None, False, f"Local\\SiccoraLauncher-{tag}")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        event = k32.OpenEventW(0x0002, False, f"Local\\SiccoraLauncher-{tag}-show")  # EVENT_MODIFY_STATE
        if event:
            k32.SetEvent(event)
        return False
    event = k32.CreateEventW(None, False, False, f"Local\\SiccoraLauncher-{tag}-show")
    _instance.update(mutex=mutex, event=event)

    def wait():
        while k32.WaitForSingleObject(event, 0xFFFFFFFF) == 0:
            on_wake()
    threading.Thread(target=wait, daemon=True).start()
    return True


def _bring_to_front(window):
    """Fenster zeigen, wiederherstellen und nach vorn holen (aus dem Infobereich oder minimiert)."""
    from System import Action
    window.show()
    window.restore()
    form = window.native
    form.Invoke(Action(lambda: (form.Activate(), form.BringToFront())))


def _tray_texts():
    return {"open": tr("Siccora Launcher öffnen"), "quit": tr("Beenden")}


def main(selftest=None):
    started = time.time()
    _crash_log()
    debuglog.prune()
    debuglog.log("start", "Launcher startet", version=APP_VERSION, frozen=getattr(sys, "frozen", False),
                 args=sys.argv[1:], exe=sys.executable)
    holder = {}
    if not selftest and not _first_instance(lambda: holder.get("show") and holder["show"]()):
        return  # laeuft schon - wurde nach vorn geholt
    start_hidden = autostart.TRAY_ARG in sys.argv[1:]
    # Ohne GPU-Prozess spart die Anzeige ~125 MB (gemessen 242 -> 117 MB);
    # fuer eine Oberflaeche aus Karten und Listen reicht Software-Zeichnen.
    # --lang: Sprache, die die Fenster an Webseiten melden (sonst nur Windows-Anzeigesprache)
    lang = BROWSER_LANG.get(settings.get("language") or "", "en-US")
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", f"--disable-gpu --lang={lang}")
    api = Api()
    # gross genug fuer 3 Boxen in voller Breite, aber nie groesser als der Bildschirm
    try:
        screen = webview.screens[0]
        start_w, start_h = min(1640, screen.width - 40), min(920, screen.height - 80)
    except (IndexError, AttributeError):
        start_w, start_h = 1320, 860
    window = webview.create_window("Siccora Launcher", os.path.join(HERE, "ui", "index.html"), js_api=api,
                                   width=start_w, height=start_h, min_size=(960, 600), background_color="#15110E",
                                   hidden=start_hidden)
    api._store = StorePanel(window)
    api._account = StorePanel(window)
    api._window = window
    holder["show"] = lambda: _bring_to_front(window)

    def ask_close():
        try:
            window.evaluate_js("void askClose()")  # Rueckfrage im Launcher-Design
        except Exception:  # Oberflaeche antwortet nicht -> Schliessen nie blockieren
            api.close_app()

    def quit_from_tray():
        if api._downloads.active():
            _bring_to_front(window)  # Rueckfrage zu laufenden Downloads im Fenster
            ask_close()
        else:
            api.close_app()

    def on_closing():
        # X bei "im Infobereich weiterlaufen": nur verstecken, Downloads laufen weiter
        if not api._close_confirmed and api._tray and settings.get("closeToTray"):
            threading.Thread(target=window.hide, daemon=True).start()
            if not holder.get("hinted"):
                holder["hinted"] = True
                api._tray.notify(tr("Der Launcher läuft im Infobereich weiter."))
            return False
        # laufende Downloads nicht still abwuergen
        if api._downloads.active() and not api._close_confirmed:
            threading.Thread(target=ask_close, daemon=True).start()  # hier nicht warten: das ist der Fenster-Thread
            return False
        debuglog.log("start", "Launcher wird beendet", laufzeit_min=round((time.time() - started) / 60, 1))
        api._downloads.shutdown()
        if api._tray:
            api._tray.close()  # jetzt, solange die Nachrichtenschleifen noch laufen
        return True

    def on_started():
        # erst jetzt: die Windows-Bausteine (.NET) laedt pywebview beim Start
        try:
            # Herunterfahren/Abmelden/Installer-Update: nie aufhalten (kein Verstecken, keine Rueckfrage) -
            # laufende Downloads werden pausiert und lassen sich spaeter fortsetzen
            from Microsoft.Win32 import SystemEvents
            SystemEvents.SessionEnding += lambda s, e: setattr(api, "_close_confirmed", True)
        except Exception:
            traceback.print_exc()
        try:
            api._tray = Tray(os.path.join(HERE, "ui", "siccora.ico"), holder["show"], quit_from_tray, _tray_texts())
        except Exception:
            traceback.print_exc()  # ohne Symbol weiter - das X beendet dann normal
        # einmal nach dem Start: wo gibt es ueberhaupt "Optionen"? (nur fuer neue/aktualisierte Versionen)
        threading.Thread(target=lambda: _quiet(components.refresh_options, api._epic), daemon=True).start()
        if selftest:
            _selftest(window, selftest)()

    window.events.closing += on_closing

    def on_first_load():
        window.events.loaded -= on_first_load
        debuglog.log("start", "Oberflaeche geladen", s=round(time.time() - started, 1))
        try:
            guard_main(window)
        except Exception:
            traceback.print_exc()  # Sperre fehlgeschlagen - im Protokoll sichtbar
    window.events.loaded += on_first_load
    # Kein privater Modus: Anmeldungen bei Fab/Epic im Store-Bereich bleiben erhalten.
    # Eigener Profilordner, getrennt von Edge; liegt in %LOCALAPPDATA%\SiccoraLauncher\webview.
    # Ohne privaten Modus nimmt pywebview sonst immer Port 42001 fuer die Oberflaeche -
    # eine zweite Instanz (oder ein Test) wuerde dann die Oberflaeche der ersten laden.
    # Popups im selben Fenster oeffnen: Epics Anmeldung ueber Steam & Co. nutzt ein Popup. Im
    # System-Browser landete der Anmeldecode sonst dort, und der Launcher bekam ihn nie.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    try:
        webview.start(on_started, gui="edgechromium", debug=bool(os.environ.get("SICCORA_DEBUG")),
                      private_mode=False, storage_path=os.path.join(DATA_DIR, "webview"), http_port=free_port())
    finally:
        if api._tray:
            api._tray.close()


def _selftest(window, out_file):
    """Fuer Paket-Tests ohne Bildschirm: Oberflaeche laden lassen, Zustand notieren, beenden."""
    def run():
        time.sleep(12)
        state = window.evaluate_js("""JSON.stringify({
            title: document.querySelector('#view-title').textContent,
            meta: document.querySelector('#meta').textContent,
            loginShown: !document.querySelector('#login').hidden,
            nav: [...document.querySelectorAll('.nav')].filter(b => !b.hidden).map(b => b.dataset.view)})""")
        window.evaluate_js("show('projects')")
        time.sleep(4)
        proj = window.evaluate_js("""JSON.stringify({
            meta: document.querySelector('#meta').textContent,
            cards: document.querySelectorAll('.card.project').length,
            thumbs: document.querySelectorAll('.card.project img').length})""")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
                                "ui": json.loads(state), "projects": json.loads(proj)}))
        window.destroy()
    return run


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    main()

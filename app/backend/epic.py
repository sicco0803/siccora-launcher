"""Zugriff auf Epic (Bibliothek, Engines, DevKits) und Fab.

Alles, was teuer abzurufen ist, wird in %LOCALAPPDATA%\\SiccoraLauncher
zwischengespeichert. Epic reagiert auf viele Anfragen mit HTTP 429, darum
werden Kataloginfos nur einmal je Eintrag geholt und dann dauerhaft gemerkt.
"""
import json
import os
import re
import tempfile
import threading
import time
import traceback

import requests
from legendary.core import LegendaryCore

from . import debuglog
from .i18n import tr

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SiccoraLauncher")
EGL_INSTALLED = r"C:\ProgramData\Epic\UnrealEngineLauncher\LauncherInstalled.dat"
LOGIN_URL = "https://legendary.gl/epiclogin"

UE_NS = "ue"
MEGASCANS_NS = "89efe5924d3d467c839449ab6ab52e7f"
TOOL_WORDS = ("devkit", "modkit", "mod kit", "editor", "sdk")
REQUEST_PAUSE = 0.3  # Sekunden zwischen Katalog-Anfragen
LIB_SCHEMA = 2  # hochzaehlen, wenn library.json neue Eintragsarten bekommt (2: DLCs) -> einmal neu aufbauen
FAB_SCHEMA = 3  # hochzaehlen, wenn fab.json neue Felder bekommt -> Cache wird neu geladen


def read_json(path, default):
    """JSON lesen; fehlt die Datei oder ist sie kaputt -> default. Wird sie gerade ausgetauscht
    (write_json), sperrt Windows sie fuer einen Augenblick - dann kurz warten statt default zu liefern,
    sonst wuerde z. B. settings.save die Standardwerte zurueckschreiben."""
    for attempt in range(20):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except PermissionError:
            time.sleep(0.02)
        except (OSError, ValueError):
            return default
    return default


def _load(name, default):
    return read_json(os.path.join(DATA_DIR, name), default)


def write_json(path, data, **dump_args):
    """JSON sicher schreiben: erst in eine eigene Zwischendatei, dann austauschen. Jeder Aufruf hat
    seine eigene Zwischendatei - zwei Hintergrundaufgaben koennen sich so nicht in die Quere kommen."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_args)
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows: liest gerade jemand die Datei, kurz warten
                if attempt == 9:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _save(name, data):
    write_json(os.path.join(DATA_DIR, name), data)


def _image(key_images, *types):
    for t in types:
        for img in key_images or []:
            if img.get("type") == t:
                return img.get("url")
    return (key_images or [{}])[0].get("url") if key_images else None


def legendary_dir():
    """Legendarys Datenordner - dieselbe Reihenfolge wie Legendary selbst (lfs/lgndry.py)."""
    return os.environ.get("LEGENDARY_CONFIG_PATH") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")), "legendary")


def _prune_legendary_cache():
    """Legendary laedt beim Start ALLE gespeicherten Metadaten in den Speicher.

    Wir brauchen sie nur fuer installierte Eintraege (lgd_run holt sie bei
    Bedarf einzeln nach) - der Rest kostet nur RAM und Startzeit.
    """
    base = legendary_dir()
    try:
        with open(os.path.join(base, "installed.json"), encoding="utf-8") as f:
            keep = tuple(json.load(f))
    except (OSError, ValueError):
        return  # im Zweifel nichts loeschen
    for folder in ("metadata", "manifests"):
        path = os.path.join(base, folder)
        if not os.path.isdir(path):
            continue
        # Dateinamen beginnen mit dem appName (metadata/<app>.json, manifests/<app>_<...>.manifest)
        for name in os.listdir(path):
            if name.endswith((".json", ".manifest")) and not name.startswith(keep):
                try:
                    os.remove(os.path.join(path, name))
                except OSError:
                    pass


class EpicService:
    def __init__(self):
        _prune_legendary_cache()
        self.core = LegendaryCore()
        self.core.egs.request_timeout = 120  # die Rohliste ist sehr gross
        self._lock = threading.Lock()

    # --- Anmeldung -----------------------------------------------------------
    def account(self):
        with self._lock:
            try:
                if self.core.lgd.userdata and self.core.login():
                    return {"loggedIn": True, "name": self.core.lgd.userdata.get("displayName")}
            except Exception:
                pass
            return {"loggedIn": False, "name": None}

    def login_with_text(self, text):
        match = re.search(r'"authorizationCode"\s*:\s*"([0-9a-f]{32})"', text or "") \
            or re.search(r"\b([0-9a-f]{32})\b", text or "")
        if not match:
            return {"ok": False, "error": tr("Kein Code im Text gefunden.")}
        with self._lock:
            ok = self.core.auth_code(match.group(1))
        if not ok:
            return {"ok": False, "error": tr("Epic hat den Code abgelehnt - vermutlich abgelaufen. Bitte neu holen.")}
        return {"ok": True, **self.account()}

    def logout(self):
        with self._lock:
            # auch bei Epic beenden - sonst bliebe die Anmeldung dort noch eine Weile gueltig
            # (Legendarys eigenes invalidate_session nutzt ein nie gesetztes Feld - darum hier selbst)
            try:
                if self.core.lgd.userdata:
                    self.core.login()  # abgelaufenes Token erst erneuern, sonst lehnt Epic das Beenden ab
                token = (self.core.lgd.userdata or {}).get("access_token")
                if token:
                    egs = self.core.egs
                    egs.session.delete(f"https://{egs._oauth_host}/account/api/oauth/sessions/kill/{token}",
                                       headers={"Authorization": f"bearer {token}"}, timeout=10)
            except Exception:  # offline o. ae.: lokal trotzdem abmelden
                pass
            self.core.lgd.invalidate_userdata()
        for name in ("library.json", "fab.json"):
            try:
                os.remove(os.path.join(DATA_DIR, name))
            except OSError:
                pass
        return {"loggedIn": False}

    # --- Lokal installiert ---------------------------------------------------
    def installed(self):
        """Installiert von Epic Launcher oder von uns (appName -> Ort/Version/Quelle).

        Legendary-Eintraege gewinnen: nach Uebernahme/Update sind sie aktueller.
        Epic-Launcher-Eintraege zaehlen nur, solange der Ordner noch existiert.
        """
        try:
            with open(EGL_INSTALLED, encoding="utf-8") as f:
                entries = json.load(f).get("InstallationList", [])
        except (OSError, ValueError):
            entries = []
        result = {e["AppName"]: {"path": e["InstallLocation"], "version": e["AppVersion"], "source": "egl"}
                  for e in entries if os.path.isdir(e["InstallLocation"])}
        # direkt lesen: die Download-Prozesse schreiben die Datei, unser Core-Objekt merkt das nicht
        try:
            with open(os.path.join(self.core.lgd.path, "installed.json"), encoding="utf-8") as f:
                own = json.load(f)
        except (OSError, ValueError):
            own = {}
        for app, ig in own.items():
            result[app] = {"path": ig["install_path"], "version": ig["version"], "source": "legendary"}
        return result

    def heroic_installed(self):
        """Was Heroic installiert hat (appName -> Ordner): Vorschlaege fuer "Vorhandene hinzufuegen"."""
        path = os.path.join(os.environ.get("APPDATA", ""), "heroic", "legendaryConfig", "legendary", "installed.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return {app: ig["install_path"] for app, ig in data.items()
                if isinstance(ig, dict) and os.path.isdir(ig.get("install_path") or "")}

    # --- Bibliothek: Spiele, Engines, Tools ----------------------------------
    def _catalog(self, wanted):
        """Katalog-Infos je catalogItemId, dauerhaft gecacht. wanted: {ns: [ids]}."""
        cache = _load("catalog.json", {})
        session = self.core.egs.session
        host = self.core.egs._catalog_host
        for ns, ids in wanted.items():
            missing = [i for i in ids if i not in cache or (cache[i].get("dlc") and "mainApp" not in cache[i])]
            for start in range(0, len(missing), 50):
                chunk = missing[start:start + 50]
                r = session.get(f"https://{host}/catalog/api/shared/namespace/{ns}/bulk/items",
                                params=[("id", i) for i in chunk] + [("includeMainGameDetails", "true"),
                                                                      ("country", "DE"), ("locale", "de")],
                                timeout=60)
                if r.status_code == 429:
                    time.sleep(5)
                    continue  # beim naechsten Aktualisieren erneut versuchen
                r.raise_for_status()
                for cid, item in r.json().items():
                    main = item.get("mainGameItem") or {}
                    cache[cid] = {
                        "title": item.get("title"),
                        "dlc": bool(main),
                        # appName des Hauptspiels - so haengt Legendary DLCs an ihr Spiel
                        "mainApp": next((x.get("appId") for x in main.get("releaseInfo") or [] if x.get("appId")), None),
                        "categories": [c.get("path") for c in item.get("categories", [])],
                        "image": _image(item.get("keyImages"), "DieselGameBoxTall", "DieselGameBox", "Thumbnail"),
                        "wide": _image(item.get("keyImages"), "DieselGameBox", "Featured", "DieselGameBoxTall"),
                        "developer": item.get("developer"),
                    }
                time.sleep(REQUEST_PAUSE)
            _save("catalog.json", cache)
        return cache

    def library(self, refresh=False):
        cached = _load("library.json", None)
        if cached and not refresh and cached.get("schema") == LIB_SCHEMA:
            return self._with_install_state(cached)
        return self._with_install_state(self._fetch_library())

    def check_updates(self, min_age=1800):
        """Aktuelle Versionsnummern holen (eine Anfrage). Taucht bei Epic etwas Neues auf (neue
        Engine, Preview, DevKit, Spiel), wird die Bibliothek einmal komplett neu geladen."""
        data = _load("library.json", None)
        if not data:
            return None
        if data.get("schema") != LIB_SCHEMA:  # aeltere Launcher-Version: Bibliothek einmal neu aufbauen
            try:
                data = self._fetch_library()
            except Exception:
                traceback.print_exc()
        announce = []
        if time.time() - data.get("checked", data.get("updated", 0)) >= min_age:
            with self._lock:
                self.core.login()
                assets = self.core.egs.get_game_assets(platform="Windows")
            latest = {a["appName"]: a.get("buildVersion") for a in assets}
            known = {i["appName"] for i in data["items"]}
            others = _other_apps(assets)
            seen = data.get("seenApps")
            current = {a["appName"] for a in assets if _is_engine(a)}
            # neu hinzugekommen ODER bei Epic weggefallen (z. B. zurueckgezogen) -> Liste neu aufbauen
            is_new = bool(current - known) or any(i["kind"] == "engine" and i["appName"] not in current for i in data["items"]) \
                or (seen is not None and (bool(others - set(seen)) or bool(set(seen) - others)))
            refreshed = None
            if is_new:
                try:
                    refreshed = self._fetch_library()
                except Exception:  # Epic gerade nicht erreichbar - beim naechsten Mal erneut
                    traceback.print_exc()
            if refreshed:
                data = refreshed
                announce = [i["title"] for i in data["items"] if i["appName"] not in known and i["kind"] in ("engine", "tool")]
            else:
                ids = {a["appName"]: a["catalogItemId"] for a in assets}
                for item in data["items"]:
                    item["latest"] = latest.get(item["appName"], item.get("latest"))
                    item["catalogItemId"] = ids.get(item["appName"], item.get("catalogItemId"))
                if seen is None:
                    data["seenApps"] = sorted(others)
                with self._lock:
                    self._mark_previews(data["items"])  # auch der Wechsel von Preview zur fertigen Version
            data["checked"] = time.time()
            # aktuelle Versionen auch der Fab-Assets merken (Startseite: Asset-Updates)
            _save("asset_versions.json", {"checked": data["checked"], "versions": latest})
            _save("library.json", data)
        return {**self._with_install_state(data), "newItems": announce}

    def _mark_previews(self, items):
        """Preview-Versionen der Engine erkennen: Epic fuehrt sie unter engines/preview. Immer frisch
        fragen (nicht aus catalog.json), geprueft werden nur die neuesten und bisherige Previews."""
        engines = sorted((i for i in items if i["kind"] == "engine"), key=_engine_sort)
        ids = list({i["catalogItemId"] for i in engines[:3]} | {i["catalogItemId"] for i in engines if i.get("preview")})
        if not ids:
            return
        try:
            r = self.core.egs.session.get(f"https://{self.core.egs._catalog_host}/catalog/api/shared/namespace/{UE_NS}/bulk/items",
                                          params=[("id", i) for i in ids] + [("country", "DE"), ("locale", "de")], timeout=60)
            r.raise_for_status()
            info = r.json()
        except (requests.RequestException, ValueError):
            return  # bisheriger Stand bleibt
        for item in engines:
            found = info.get(item["catalogItemId"])
            if found is not None:
                item["preview"] = any(c.get("path") == "engines/preview" for c in found.get("categories", []))
                item["title"] = "Unreal Engine " + item["appName"][3:] + (" Preview" if item["preview"] else "")

    def find(self, app_name):
        data = _load("library.json", {"items": []})
        return next((i for i in data["items"] if i["appName"] == app_name), None)

    def _fetch_library(self):

        with self._lock:
            self.core.login()
            assets = self.core.egs.get_game_assets(platform="Windows")

        # Katalog-Infos direkt zu jedem Download holen (die Asset-Liste ist genau das, was das Konto
        # besitzt) - nicht ueber die separate Bibliotheksliste, deren Eintraege nicht immer passen
        wanted = {}
        for a in assets:
            if a["namespace"] not in (UE_NS, MEGASCANS_NS):
                wanted.setdefault(a["namespace"], set()).add(a["catalogItemId"])
        catalog = self._catalog({ns: sorted(ids) for ns, ids in wanted.items()})

        items, pending = [], set()
        for a in assets:
            ns, name = a["namespace"], a["appName"]
            if ns == UE_NS:
                if not _is_engine(a):
                    continue  # Vault-Assets und Plugins kommen ueber Fab
                items.append({"appName": name, "kind": "engine", "title": "Unreal Engine " + name[3:],
                              "namespace": ns, "catalogItemId": a["catalogItemId"],
                              "latest": a.get("buildVersion"), "image": None})
                continue
            if ns == MEGASCANS_NS:
                continue
            info = catalog.get(a["catalogItemId"])
            if not info:
                pending.add(name)  # Epic gerade nicht erreichbar/zu viele Anfragen: beim naechsten Abgleich erneut
                continue
            cats = set(info["categories"])
            title = info["title"] or name
            launchable = "addons/launchable" in cats
            if info["dlc"] and not launchable:
                if info.get("mainApp"):  # wird unten nur behalten, wenn das Hauptspiel in der Bibliothek ist
                    items.append({"appName": name, "kind": "dlc", "parent": info["mainApp"], "title": title, "namespace": ns,
                                  "catalogItemId": a["catalogItemId"], "latest": a.get("buildVersion"),
                                  "image": info["image"], "wide": info["wide"], "developer": info["developer"]})
                continue
            if cats == {"addons"} and not launchable:
                continue  # reine Zusatzinhalte ohne eigenen Download-Sinn
            # Epic fuehrt DevKits/ModKits/Editoren unter "engines" oder "software"
            if cats & {"engines", "software"} or launchable or any(w in title.lower() for w in TOOL_WORDS):
                kind = "tool"
            else:
                kind = "game"
            items.append({"appName": name, "kind": kind, "title": title, "namespace": ns,
                          "catalogItemId": a["catalogItemId"], "latest": a.get("buildVersion"),
                          "image": info["image"], "wide": info["wide"], "developer": info["developer"]})

        # DLCs nur zu Spielen, die das Konto besitzt (ohne Hauptspiel nicht installierbar)
        games = {i["appName"] for i in items if i["kind"] == "game"}
        items = [i for i in items if i["kind"] != "dlc" or i["parent"] in games]
        items.sort(key=lambda i: (i["kind"], _engine_sort(i) if i["kind"] == "engine" else i["title"].lower()))
        with self._lock:
            self._mark_previews(items)
        now = time.time()
        # noch nicht eingeordnete Eintraege gelten nicht als gesehen - so holt der naechste Abgleich sie nach
        data = {"updated": now, "checked": now, "items": items, "seenApps": sorted(_other_apps(assets) - pending),
                "schema": LIB_SCHEMA}
        debuglog.log("library", "Bibliothek neu aufgebaut", assets=len(assets), eintraege=len(items),
                     nicht_eingeordnet=sorted(pending)[:20])
        _save("library.json", data)
        return data

    def ack_version(self, app_name, latest):
        """Epics Asset-Liste nennt fuer manche Eintraege eine andere Nummer als das Manifest
        (z. B. Conan Exiles Enhanced Dev Kit). Hat die Vorschau bestaetigt, dass die installierte
        Version schon dem aktuellen Manifest entspricht, gilt diese Nummer als erledigt - bis
        Epic eine neue meldet."""
        acks = _load("version_ack.json", {})
        debuglog.log("library", "Abweichende Epic-Versionsnummer als aktuell markiert", app=app_name, latest=latest)
        acks[app_name] = latest
        _save("version_ack.json", acks)

    def _with_install_state(self, data):
        inst = self.installed()
        acks = _load("version_ack.json", {})
        options = _load("options.json", {})  # von components.refresh_options im Hintergrund ermittelt
        for item in data["items"]:
            local = inst.get(item["appName"])
            item["installed"] = bool(local)
            item["source"] = local["source"] if local else None
            item["path"] = local["path"] if local else None
            item["version"] = local["version"] if local else None
            item["updateAvailable"] = bool(local and item.get("latest") and local["version"] != item["latest"]
                                           and acks.get(item["appName"]) != item["latest"])
            known = options.get(item["appName"]) or {}
            # None = noch unbekannt (Button bleibt sichtbar); nur fuer die installierte Version gueltig
            item["hasOptions"] = known.get("has") if local and known.get("version") == local["version"] else None
            if item["kind"] == "engine" and local:
                item["plugins"] = sorted(n.split("_")[0] for n, v in inst.items()
                                         if v["path"] == local["path"] and n != item["appName"])
        return data

    # --- Fab-Bibliothek -------------------------------------------------------
    def fab(self, refresh=False):
        cached = _load("fab.json", None)
        if cached and not refresh and cached.get("schema") == FAB_SCHEMA:
            return cached

        with self._lock:
            self.core.login()
            user = self.core.lgd.userdata
            assets = {a["appName"] for a in self.core.egs.get_game_assets(platform="Windows")}

        s = requests.Session()
        s.headers["Authorization"] = f"bearer {user['access_token']}"
        raw, cursor = [], None
        for _ in range(200):
            params = {"count": 100, **({"cursor": cursor} if cursor else {})}
            r = s.get(f"https://www.fab.com/e/accounts/{user['account_id']}/ue/library", params=params, timeout=60)
            r.raise_for_status()
            page = r.json()
            raw += page.get("results", [])
            cursor = (page.get("cursors") or {}).get("next")
            if not cursor:
                break
            time.sleep(REQUEST_PAUSE)

        items = []
        for it in raw:
            # Fehlt eine Version in Epics Asset-Liste, kommt sie ueber Fab - ladbar sind alle
            versions = [{"artifactId": v["artifactId"], "engines": v.get("engineVersions", []),
                         "downloadable": True, "direct": v["artifactId"] in assets}
                        for v in it.get("projectVersions", [])]
            images = it.get("images") or []
            items.append({
                "id": it.get("assetId"),
                "namespace": it.get("assetNamespace"),
                "title": it.get("title"),
                "seller": it.get("seller"),
                "type": it.get("listingType"),
                "kind": it.get("distributionMethod"),  # ASSET_PACK / CODE_PLUGIN / COMPLETE_PROJECT
                "categories": [c.get("name") for c in it.get("categories", [])],
                "image": images[0]["url"] if images else None,
                "url": it.get("url"),
                "versions": versions,
                "engines": sorted({e for v in versions for e in v["engines"]}, key=_version_key),
                "downloadable": any(v["downloadable"] for v in versions),
            })
        items.sort(key=lambda i: (i["title"] or "").lower())
        data = {"updated": time.time(), "schema": FAB_SCHEMA, "items": items}
        _save("fab.json", data)
        return data

    def locked(self):
        """Sperre fuer Zugriffe auf Legendarys Anmeldung (Token-Erneuerung)."""
        return self._lock

    def fab_cached(self):
        """Fab-Bibliothek nur aus dem Zwischenspeicher - laedt nie von Epic (fuer die Startseite)."""
        return _load("fab.json", None) or {"items": []}

    def fab_item(self, asset_id):
        return next((i for i in self.fab()["items"] if i["id"] == asset_id), None)

    def asset_ref(self, artifact_id):
        """namespace/catalogItemId zu einer Fab-Version (aus Epics Asset-Liste)."""
        with self._lock:
            self.core.login()
            for a in self.core.get_assets(update_assets=False) or self.core.get_assets(update_assets=True):
                if a.app_name == artifact_id:
                    return a
        return None


def _version_key(engine):
    nums = re.findall(r"\d+", engine or "")
    return tuple(int(n) for n in nums) or (0,)


def _is_engine(asset):
    return asset["namespace"] == UE_NS and bool(re.match(r"^UE_\d", asset["appName"]))


def _other_apps(assets):
    """Alles ausser Engines und Vault-Inhalten - daran erkennt der Launcher neue DevKits und Spiele."""
    return {a["appName"] for a in assets if a["namespace"] not in (UE_NS, MEGASCANS_NS)}


def _engine_sort(item):
    return tuple(-n for n in _version_key(item["appName"]))

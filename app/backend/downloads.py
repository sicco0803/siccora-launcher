"""Download-Warteschlange: Installieren, Updaten, Deinstallieren.

Jeder Auftrag laeuft als eigener Legendary-Prozess. Stuerzt der ab, bleibt die
App heil. "Pausieren" beendet den Prozess, Legendarys .resume-Datei bleibt -
"Fortsetzen" macht dort weiter (auch nach einem Neustart, die Liste wird
gespeichert). "Abbrechen" beendet und raeumt halbfertige Dateien weg.
Was der Epic Launcher installiert hat, wird vorher an Legendary uebergeben
(egl_import) und danach zurueckgemeldet (egl_export), damit beide Launcher
denselben Stand kennen.
"""
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from . import debuglog
from .epic import DATA_DIR, legendary_dir, write_json
from . import settings
from .fab_install import copy_into_place
from .i18n import tr
from .vault import mark_kept

if getattr(sys, "frozen", False):
    # Fertiges Paket: kein python.exe - die SiccoraLauncher.exe uebernimmt die Hintergrundarbeit selbst
    LEGENDARY = [sys.executable, "--lgd", "-A", "120"]
    BRIDGE = [sys.executable, "--bridge"]
else:
    PY = os.path.join(os.path.dirname(sys.executable), "python.exe")
    LEGENDARY = [PY, os.path.join(os.path.dirname(__file__), "lgd_run.py"), "-A", "120"]  # -A: API-Timeout
    BRIDGE = [PY, os.path.join(os.path.dirname(__file__), "egl_bridge.py")]
JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")
OPEN = ("queued", "running", "paused")  # noch nicht erledigt
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

RE_PROGRESS = re.compile(r"= Progress: ([\d.]+)%.*ETA: (\d+:\d+:\d+)")
RE_SPEED = re.compile(r"\+ Download\s+- ([\d.]+) MiB/s \(raw\)")
RE_DONE_MB = re.compile(r"Downloaded: ([\d.]+) MiB")
RE_DL_SIZE = re.compile(r"Download size: ([\d.]+) MiB")
RE_INSTALL_SIZE = re.compile(r"Install size: ([\d.]+) MiB")
RE_MOVE = re.compile(r"^MOVE_PROGRESS (\d+) (\d+)")
RE_SHM = re.compile(r"shared memory cache is smaller than required: [\d.]+ MiB < ([\d.]+) MiB")
RE_PROBLEM = re.compile(r"(ERROR|CRITICAL|FATAL|Failure):?\s*(.*)")
RE_UP_TO_DATE = re.compile(r"Download size is 0")
RE_INSTALL_PATH = re.compile(r"Install path: (.+)$")
RE_RESUMED = re.compile(r"Skipping (\d+) files based on resume data")
RE_PRUNE = re.compile(r"^PRUNE (\d+)/(\d+)")
# Pruefen ("Verify"): Legendary schreibt den Fortschritt mit \r in dieselbe Zeile
RE_VERIFY = re.compile(r"Verification progress: (\d+)/(\d+) \(([\d.]+)%\) \[([\d.]+) MiB/s\]")
RE_VERIFY_BAD = re.compile(r"File does not match hash|File is missing|treating file as missing")
RE_WRITTEN = re.compile(r"Written: ([\d.]+) MiB")
RE_DISK = re.compile(r"\+ Disk\s+- ([\d.]+) MiB/s \(write\) / ([\d.]+) MiB/s \(read\)")
RE_CACHE = re.compile(r"Cache usage: ([\d.]+) MiB, active tasks: (\d+)")
RE_PRUNED = re.compile(r"^PRUNED (\d+) (\d+)")
# Adressen der Download-Server gehoeren nicht in die Anzeige (koennen Zugangs-Token enthalten)
RE_SERVER = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+|\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|cloud|gg)\b(?:[/:]\S*)?", re.I)

ACTION_LABEL = {"install": "Installieren", "update": "Update", "uninstall": "Deinstallieren", "repair": "Reparieren",
                "fab": "Fab-Asset", "modify": "Komponenten ändern", "adopt": "Übernehmen", "move": "Verschieben"}


class Downloads:
    def __init__(self, on_change=None):
        self._jobs = _load_jobs()
        self._ids = itertools.count(max((j["id"] for j in self._jobs), default=0) + 1)
        self._lock = threading.Lock()
        self._procs = {}  # Auftrags-ID -> laufender Prozess
        self._on_change = on_change  # z. B. Bibliotheks-Cache auffrischen
        # Zwei Spuren: Spiele/Engines/DevKits nacheinander, Fab-Assets daneben -
        # sonst wartet ein 12-MB-Asset stundenlang hinter einem 300-GB-DevKit.
        self._wake = {lane: threading.Event() for lane in ("main", "fab")}
        for lane in self._wake:
            threading.Thread(target=self._worker, args=(lane,), daemon=True).start()

    # --- oeffentliche Methoden ---------------------------------------------
    def add(self, action, app_name, title, base_path=None, from_egl=False, fab=None, label=None, components=None,
            parent=None, parent_from_egl=False, tags=None, move=None):
        with self._lock:
            if any(j["appName"] == app_name and j["status"] in OPEN for j in self._jobs):
                return {"error": tr("{title} ist bereits in der Liste (ggf. pausiert – dort fortsetzen).", title=title)}
            job = {"id": next(self._ids), "action": action, "label": label or ACTION_LABEL[action], "fab": fab,
                   "components": components,  # {"selected": [...], "removed": [...], "adding": bool}
                   "appName": app_name, "title": title, "basePath": base_path, "fromEgl": from_egl,
                   "parent": parent, "parentFromEgl": parent_from_egl,  # DLC: Spiel, in dessen Ordner es landet
                   "tags": tags,  # Installation: gewaehlte optionale Komponenten (None = alles wie bisher)
                   "move": move,  # Verschieben: {"from": alter Ordner, "to": neuer Ordner}
                   "status": "queued", "progress": 0.0, "speed": 0.0, "eta": "", "downloadedMb": 0.0,
                   "downloadMb": None, "installMb": None, "message": "", "log": [], "added": time.time()}
            if action == "fab":
                _vault(job)  # Zwischenordner jetzt festhalten
            self._jobs.append(job)
            self._save()
        self._wake[_lane(job)].set()
        return {"ok": True, "id": job["id"]}

    def list(self):
        """Meldungen werden erst hier uebersetzt - ein Sprachwechsel wirkt sofort, auch auf Pausiertes."""
        with self._lock:
            out = []
            for j in self._jobs:
                row = {k: v for k, v in j.items() if k != "log"}
                row["message"] = tr(j["message"], **(j.get("msgVars") or {}))
                row["label"] = tr(j["label"])
                out.append(row)
            return out

    def log(self, job_id, lines=60):
        """Letzte Zeilen der Ausgabe eines Auftrags - fuer die Aktivitaetsanzeige."""
        with self._lock:
            job = self._get(job_id)
            return {"lines": list((job or {}).get("log") or [])[-lines:]}

    def paths_in_use(self):
        """Ordner, die offene Auftraege gerade als Quelle oder Ziel nutzen (Vault-Loeschsperre)."""
        with self._lock:
            out = []
            for j in self._jobs:
                if j["status"] in OPEN and j["action"] == "fab":
                    out += [(j.get("fab") or {}).get("sourcePath"), os.path.join(_vault(j), j["appName"])]
            return out

    def active(self):
        with self._lock:
            return any(j["status"] in ("queued", "running") for j in self._jobs)

    def pause(self, job_id):
        """Anhalten - Legendarys .resume-Datei bleibt, Fortsetzen macht dort weiter."""
        with self._lock:
            job = self._get(job_id)
            if not job or job["status"] not in ("queued", "running"):
                return {"error": tr("Nichts zu pausieren.")}
            if job["action"] == "uninstall":
                return {"error": tr("Entfernen lässt sich nicht pausieren.")}
            was_running = job["status"] == "running"
            job["status"], job["speed"], job["eta"] = "paused", 0.0, ""
            job["message"] = "Pausiert – mit „Fortsetzen“ geht es an derselben Stelle weiter."
            if was_running and (proc := self._procs.get(job_id)):
                _kill_tree(proc)
            self._save()
        return {"ok": True}

    def resume(self, job_id):
        with self._lock:
            job = self._get(job_id)
            if not job or job["status"] not in ("paused", "failed"):
                return {"error": tr("Nichts fortzusetzen.")}
            # Legendary zaehlt nach dem Fortsetzen nur den Rest (wieder ab 0 %) -
            # die Anzeige soll beim bisherigen Stand weiterlaufen.
            job["resumeBase"] = job["progress"] if job["status"] == "paused" and job["action"] != "repair" else 0.0
            job["status"], job["message"] = "queued", "Wartet …"
            self._save()
        self._wake[_lane(job)].set()
        return {"ok": True}

    def cancel(self, job_id):
        """Abbrechen - beenden und halbfertige Dateien wegraeumen."""
        with self._lock:
            job = self._get(job_id)
            if not job or job["status"] not in OPEN:
                return {"error": tr("Nichts abzubrechen.")}
            if job["status"] == "running" and job["action"] == "uninstall":
                return {"error": tr("Entfernen läuft bereits und lässt sich nicht mehr abbrechen.")}
            was_running = job["status"] == "running"
            job["status"] = "cancelled"
            if was_running and (proc := self._procs.get(job_id)):
                _kill_tree(proc)  # aufgeraeumt wird in _run, sobald der Prozess weg ist
            self._save()
        if not was_running:
            self._cleanup(job)
        return {"ok": True}

    def clear_finished(self):
        with self._lock:
            self._jobs = [j for j in self._jobs if j["status"] in OPEN]
            self._save()
        return {"ok": True}

    def shutdown(self):
        """Beim Schliessen: Laufendes pausieren, damit es nach dem Neustart fortsetzbar ist."""
        with self._lock:
            for job in self._jobs:
                if job["status"] in ("running", "queued") and job["action"] != "uninstall":
                    job["status"] = "paused"
                    job["message"] = "Beim Schließen angehalten – mit „Fortsetzen“ geht es weiter."
            for proc in self._procs.values():
                _kill_tree(proc)
            self._save()

    def _get(self, job_id):
        return next((j for j in self._jobs if j["id"] == job_id), None)

    def _save(self):
        """Offene Auftraege sichern (ohne Protokoll) - Aufruf nur mit gehaltenem Lock."""
        keep = [{k: v for k, v in j.items() if k != "log"} for j in self._jobs if j["status"] in OPEN]
        try:
            write_json(JOBS_FILE, keep)
        except OSError:
            pass

    def _cleanup(self, job):
        """Reste eines abgebrochenen Auftrags entfernen."""
        app = job["appName"]
        try:
            os.remove(os.path.join(legendary_dir(), "tmp", f"{app}.resume"))
        except OSError:
            pass
        if job["action"] == "move":
            # Abgebrochen: halbe Kopie am Ziel weg - aber NUR, solange Legendary noch auf das Original zeigt
            mv = job.get("move") or {}
            try:
                with open(os.path.join(legendary_dir(), "installed.json"), encoding="utf-8") as f:
                    current = (json.load(f).get(app) or {}).get("install_path") or ""
            except (OSError, ValueError):
                current = ""
            same = lambda a, b: os.path.normcase(os.path.abspath(a or "")) == os.path.normcase(os.path.abspath(b or ""))
            if mv.get("to") and same(current, mv.get("from")) and not same(mv["to"], mv["from"]) \
                    and os.path.isdir(mv["to"]) and os.path.isdir(mv["from"]):
                shutil.rmtree("\\\\?\\" + os.path.abspath(mv["to"]), ignore_errors=True)
                job["message"] = "Abgebrochen – das Original ist unverändert, die halbe Kopie wurde gelöscht."
            else:
                job["message"] = "Abgebrochen."
            return
        if job["action"] == "fab":
            # nur einen gerade begonnenen Download wegraeumen - nie ein behaltenes Asset oder Epics Cache
            if (job.get("fab") or {}).get("source", "download") == "download":
                shutil.rmtree(os.path.join(_vault(job), app), ignore_errors=True)
                job["message"] = "Abgebrochen – Zwischendateien gelöscht."
            else:
                job["message"] = "Abgebrochen."
        elif job["action"] == "install" and _is_partial_install(job):
            shutil.rmtree(job["installPath"], ignore_errors=True)
            job["message"] = "Abgebrochen – halbfertige Installation gelöscht."
        elif job["action"] in ("update", "repair", "modify"):
            job["message"] = ("Abgebrochen – die Installation ist evtl. unvollständig. "
                              "Bitte später „Update“ oder „Prüfen“ ausführen.")
        else:
            job["message"] = "Abgebrochen."

    # --- Arbeiter ------------------------------------------------------------
    def _worker(self, lane):
        while True:
            self._wake[lane].wait()
            with self._lock:
                job = next((j for j in self._jobs if j["status"] == "queued" and _lane(j) == lane), None)
                if not job:
                    self._wake[lane].clear()
                    continue
                job["status"] = "running"
                job["message"] = ""
                self._save()
            debuglog.job_start(job)
            began = time.time()
            try:
                self._run(job)
            except Exception as e:  # nie den Arbeiter sterben lassen
                debuglog.exception("job", f"Auftrag {job['id']} abgestuerzt")
                if job["status"] == "running":
                    job["status"], job["message"] = "failed", hide_servers(f"{type(e).__name__}: {e}")
            debuglog.job_end(job, time.time() - began)
            with self._lock:
                self._save()
            if self._on_change:
                try:
                    self._on_change(job)
                except Exception:
                    pass

    def _run(self, job):
        if job["action"] == "fab":
            return self._run_fab(job)
        if job["action"] == "modify":
            return self._run_modify(job)
        if job["action"] == "adopt":
            return self._run_adopt(job)
        if job["action"] == "move":
            return self._run_move(job)
        app = job["appName"]
        if job["fromEgl"]:
            job["message"] = "Übernehme Installation aus dem Epic Launcher …"
            if not self._exec(job, BRIDGE + ["import", app]):
                if self._stopped(job):
                    return
                return self._fail(job, "Übernahme aus dem Epic Launcher fehlgeschlagen.")

        if job.get("parentFromEgl") and job.get("parent"):
            # DLC zu einem Spiel aus dem Epic Launcher: Legendary muss das Spiel erst kennen
            job["message"] = "Übernehme Installation aus dem Epic Launcher …"
            if not self._exec(job, BRIDGE + ["import", job["parent"]]):
                if self._stopped(job):
                    return
                return self._fail(job, "Übernahme aus dem Epic Launcher fehlgeschlagen.")
            job["parentFromEgl"] = False

        if job["action"] == "uninstall":
            job["message"] = "Entferne Dateien …"
            ok = self._exec(job, LEGENDARY + ["-y", "uninstall", app])
        else:
            args = ["-y", "install", app, "--skip-sdl", "--skip-dlcs"]
            if job["action"] == "install" and job["basePath"]:
                args += ["--base-path", job["basePath"]]
            if job["action"] == "install" and job.get("tags") is not None:
                # gewaehlte Komponenten ("" = Grundpaket) - sonst laedt Legendary ALLES
                # (bei Engines z. B. 38 GB Debug-Symbole und alle Zielplattformen)
                for tag in [""] + [t for t in job["tags"] if t]:
                    args += ["--install-tag", tag]
            if job["action"] == "update":
                args.append("--update-only")
            if job["action"] == "repair":
                args.append("--repair")
                if not job.get("verified"):
                    # Legendary wuerde sonst ein altes Pruefergebnis (z. B. von einem
                    # abgebrochenen Pruefen) wiederverwenden, statt neu zu pruefen
                    try:
                        os.remove(os.path.join(legendary_dir(), "tmp", f"{app}.repair"))
                    except OSError:
                        pass
                    job.update(phase="verify", verifyBad=0, verifyNum=0, verifyTotal=0, readSpeed=0.0)
            if job["action"] == "update" and "oldVersion" not in job:
                # fuer die Nachkontrolle: nur pruefen, was das Update geschrieben hat (bleibt bei Pause erhalten)
                job["oldVersion"] = _installed_version(app)
            job["message"] = "Bereite Prüfung vor …" if job["action"] == "repair" else "Bereite Download vor …"
            ok = self._exec(job, LEGENDARY + args + _workers())
            if not ok and job["status"] == "running" and job.get("shmNeeded"):
                # Sehr grosse Pakete (z. B. ARK DevKit) brauchen in Legendarys Reihenfolge mehr Zwischenspeicher
                # fuer gemeinsam genutzte Download-Stuecke als dessen Standard (2 GB). Neuer Versuch mit
                # gruppierter Reihenfolge (lgd_run._grouped_order, braucht meist unter 2 GB) und - wenn der
                # PC genug RAM hat - zusaetzlich mehr Zwischenspeicher.
                for attempt in (1, 2):
                    needed = job.pop("shmNeeded", None)
                    if not needed or not ok and job["status"] != "running":
                        break
                    extra = _shm_args(needed, last=attempt == 2)
                    if extra is None:  # auch mit gruppierter Reihenfolge zu wenig RAM
                        job["log"].append("[Siccora] Zu wenig Arbeitsspeicher fuer dieses Paket")
                        job["shmTooBig"] = True
                        break
                    job["message"] = "Großes Paket – bereite Download speichersparend vor …"
                    note = f"[Siccora] Neuer Versuch {attempt}: gruppierte Reihenfolge {' '.join(extra)}".strip()
                    debuglog.job_line(job, note)
                    job["log"].append(note)
                    ok = self._exec(job, LEGENDARY + args + extra + _workers(), extra_env={"SICCORA_GROUP_ORDER": "1"})
                    if ok:
                        break
                if not ok and (job.get("shmTooBig") or job.get("shmNeeded")) and job["status"] == "running":
                    return self._fail(job, "Zu wenig Arbeitsspeicher für dieses Paket. Bitte andere Programme schließen "
                                           "oder weniger optionale Komponenten wählen.")
            if ok and job["status"] == "running" and job["action"] in ("install", "update") and settings.get("verifyAfter"):
                ok = self._verify_after(job, app)
            if ok and job["status"] == "running":
                self._export_to_egl(job, app)

        if self._stopped(job):
            return
        if ok:
            job["status"], job["progress"] = "done", 100.0
            if job.get("afterCheck") is not None and (job["afterCheck"] or job.get("verifyTotal")):
                bad = job["afterCheck"]
                job["message"] = ("Fertig – Nachkontrolle: {bad} von {n} Dateien waren fehlerhaft und wurden neu geladen."
                                  if bad else "Fertig – Nachkontrolle: alle {n} geänderten Dateien sind in Ordnung.")
                job["msgVars"] = {"bad": bad, "n": job.get("verifyTotal") or 0}
            elif job["action"] == "repair" and job.get("verifyTotal"):
                bad = job.get("verifyBad") or 0
                job["message"] = ("Fertig – {bad} von {n} Dateien waren defekt oder fehlten und wurden neu geladen."
                                  if bad else "Fertig – alle {n} Dateien sind in Ordnung.")
                job["msgVars"] = {"bad": bad, "n": job["verifyTotal"]}
            elif not job["message"].startswith(("Bereits", "Fertig – Versionsstand")):
                job["message"] = "Fertig."
        else:
            problems = [line for line in job["log"] if RE_PROBLEM.search(line)]
            self._fail(job, problems[-1] if problems else "Unbekannter Fehler – siehe Protokoll.")

    def _run_fab(self, job):
        """Fab-Asset: in Zwischenordner laden, ins Ziel kopieren, Zwischenordner loeschen."""
        fab, artifact = job["fab"], job["appName"]
        vault = _vault(job)
        cache = os.path.join(vault, artifact)
        source = fab.get("source", "download")

        if source in ("epic", "kept") and os.path.isdir(fab.get("sourcePath") or ""):
            files_from = fab["sourcePath"]  # liegt schon vollstaendig vor - kein Download
        else:
            os.makedirs(vault, exist_ok=True)
            job["message"] = "Bereite Download vor …"
            ok = self._exec(job, LEGENDARY + ["-y", "download", artifact, "--skip-sdl",
                                              "--base-path", vault, "--game-folder", artifact] + _workers(),
                            {"SICCORA_FAB_ASSET": json.dumps(fab["viaFab"])} if fab.get("viaFab") else None)
            if self._stopped(job):
                return
            if not ok or not os.path.isdir(cache):
                problems = [line for line in job["log"] if RE_PROBLEM.search(line)]
                return self._fail(job, problems[-1] if problems else "Download fehlgeschlagen.")
            source, files_from = "download", cache

        job["message"], job["progress"] = "Kopiere ins Ziel …", 0.0

        def progress(p):
            job["progress"] = p

        copied, skipped = copy_into_place(files_from, fab["kind"], fab["target"], fab.get("projectName"),
                                          fab.get("overwrite", False), progress)
        # Epics VaultCache wird nie angefasst; eigenes nur loeschen, wenn nicht "behalten"
        if source in ("download", "kept"):
            if fab.get("keep"):
                mark_kept(cache, fab.get("version") or "")
            else:
                shutil.rmtree(cache, ignore_errors=True)
        job["status"], job["progress"] = "done", 100.0
        job["message"] = {
            ("epic", True): "Fertig: {copied} Dateien aus Epics Vault-Cache kopiert, {skipped} vorhandene übersprungen.",
            ("epic", False): "Fertig: {copied} Dateien aus Epics Vault-Cache kopiert.",
            ("kept", True): "Fertig: {copied} Dateien aus behaltenem Asset kopiert, {skipped} vorhandene übersprungen.",
            ("kept", False): "Fertig: {copied} Dateien aus behaltenem Asset kopiert.",
            ("download", True): "Fertig: {copied} Dateien kopiert, {skipped} vorhandene übersprungen.",
            ("download", False): "Fertig: {copied} Dateien kopiert.",
        }[(source, bool(skipped))]
        job["msgVars"] = {"copied": copied, "skipped": skipped}

    def _run_move(self, job):
        """Installation verschieben (egl_bridge.move): gleiches Laufwerk sofort, sonst kopieren mit
        Fortschritt; Original erst nach vollstaendiger Kopie loeschen. Danach neuen Ort an den Epic
        Launcher melden."""
        app, mv = job["appName"], job["move"]
        if job["fromEgl"]:
            job["message"] = "Übernehme Installation aus dem Epic Launcher …"
            if not self._exec(job, BRIDGE + ["import", app]):
                if self._stopped(job):
                    return
                return self._fail(job, "Übernahme aus dem Epic Launcher fehlgeschlagen.")
            job["fromEgl"] = False
        job["message"], job["msgVars"] = "Verschiebe nach {path} …", {"path": mv["to"]}
        ok = self._exec(job, BRIDGE + ["move", app, mv["from"], mv["to"]])
        if self._stopped(job):
            return
        if not ok:
            problems = [line for line in job["log"] if RE_PROBLEM.search(line)]
            return self._fail(job, problems[-1] if problems else "Verschieben fehlgeschlagen.")
        self._export_to_egl(job, app)
        if self._stopped(job):
            return
        job["status"], job["progress"] = "done", 100.0
        job["message"], job["msgVars"] = "Fertig – verschoben nach {path}.", {"path": mv["to"]}

    def _run_adopt(self, job):
        """Vorhandene Installation uebernehmen. Ohne Epics Verwaltungsdaten (z. B. aus Heroic)
        ist der Stand unbekannt: dann alle Dateien pruefen, Fehlendes und Veraltetes nachladen."""
        job.pop("adoptResult", None)
        job["message"] = "Ordner wird geprüft …"
        ok = self._exec(job, BRIDGE + ["adopt", job["appName"], job["basePath"]])
        if self._stopped(job):
            return
        if not ok:
            if job.get("adoptResult") == "wrong":
                job["msgVars"] = {"title": job["title"]}
                return self._fail(job, "Dieser Ordner passt nicht zu {title}. Bitte den Hauptordner der Installation wählen.")
            problems = [line for line in job["log"] if RE_PROBLEM.search(line)]
            return self._fail(job, problems[-1] if problems else "Übernahme fehlgeschlagen.")
        if job.get("adoptResult") == "verify":
            job["action"] = "repair"
            return self._run(job)
        job["status"], job["progress"], job["message"] = "done", 100.0, "Fertig – Installation übernommen."

    def _run_modify(self, job):
        """Komponenten aendern: Auswahl setzen, Neues laden, Abgewaehltes gezielt loeschen.

        Jeder Schritt ist wiederholbar - nach Pause/Fortsetzen laeuft der Auftrag
        einfach noch einmal durch (Uebernahme und Auswahl sind dann schon erledigt).
        """
        app, comp = job["appName"], job["components"]
        if job["fromEgl"]:
            job["message"] = "Übernehme Installation aus dem Epic Launcher …"
            if not self._exec(job, BRIDGE + ["import", app]):
                return None if self._stopped(job) else self._fail(job, "Übernahme aus dem Epic Launcher fehlgeschlagen.")

        if not self._exec(job, BRIDGE + ["settags", app, ",".join(comp["selected"])]):
            return None if self._stopped(job) else self._fail(job, "Komponenten-Auswahl konnte nicht gespeichert werden.")

        if comp.get("adding"):
            job["message"] = "Bereite Download vor …"
            ok = self._exec(job, LEGENDARY + ["-y", "install", app, "--skip-sdl", "--skip-dlcs"] + _workers())
            if self._stopped(job):
                return
            if not ok:
                problems = [line for line in job["log"] if RE_PROBLEM.search(line)]
                return self._fail(job, problems[-1] if problems else "Download fehlgeschlagen.")

        if comp.get("removed"):
            job["message"], job["progress"] = "Entferne abgewählte Komponenten …", 0.0
            if not self._exec(job, BRIDGE + ["prune", app, ",".join(comp["removed"])]):
                return None if self._stopped(job) else self._fail(job, "Entfernen der Komponenten fehlgeschlagen.")

        self._export_to_egl(job, app)
        if self._stopped(job):
            return
        job["status"], job["progress"] = "done", 100.0
        pruned = job.get("pruned")
        if pruned:
            job["message"] = "Fertig – {n} Dateien abgewählter Komponenten entfernt ({size} GB frei)."
            job["msgVars"] = {"n": pruned[0], "size": f"{pruned[1] / 1024 ** 3:.1f}"}
        else:
            job["message"] = "Fertig."

    def _stopped(self, job):
        """Pausiert oder abgebrochen? Abgebrochenes wird hier aufgeraeumt."""
        if job["status"] == "cancelled":
            self._cleanup(job)
            return True
        return job["status"] == "paused"

    def _fail(self, job, msg):
        if "installed data lock" in msg:
            msg = ("Ein anderes Programm installiert gerade mit Legendary (z. B. eine zweite Launcher-Instanz "
                   "oder Heroic). Bitte warten, bis es fertig ist, und dann erneut versuchen.")
        debuglog.log("job", "Fehlgeschlagen", id=job["id"], app=job.get("appName"), msg=msg)
        if job["status"] == "running":
            job["status"], job["message"] = "failed", msg

    def _verify_after(self, job, app):
        """Nachkontrolle wie beim Epic Launcher; Fehlerhaftes wird gezielt neu geladen.
        Gibt False nur bei Pause/Abbruch oder wenn die Reparatur scheitert."""
        job.update(phase="verify", verifyBad=0, verifyNum=0, verifyTotal=0, readSpeed=0.0, progress=0.0, eta="")
        job["message"], job["msgVars"] = "Nachkontrolle: prüfe die geschriebenen Dateien …", {}
        cmd = BRIDGE + ["verify", app] + ([job["oldVersion"]] if job.get("oldVersion") else [])
        if not self._exec(job, cmd):
            if self._stopped(job):
                return False
            job.pop("afterCheck", None)  # Nachkontrolle ging nicht - das Update selbst ist trotzdem fertig
            debuglog.log("job", "Nachkontrolle nicht moeglich", app=app)
            return True
        if job.get("afterResult") == "skipped":
            return True
        bad = job.get("verifyBad") or 0
        job["afterCheck"] = bad
        if not bad:
            return True
        job.update(phase=None, progress=0.0)
        job["message"], job["msgVars"] = "Lade {n} fehlerhafte Dateien neu …", {"n": bad}
        ok = self._exec(job, LEGENDARY + ["-y", "install", app, "--repair", "--skip-sdl", "--skip-dlcs"] + _workers())
        if not ok and not self._stopped(job):
            self._fail(job, "Fehlerhafte Dateien konnten nicht neu geladen werden – bitte „Prüfen“ ausführen.")
        return ok

    def _export_to_egl(self, job, app):
        """Neuen Stand an den Epic Launcher melden (nicht kritisch). Laeuft er gerade, wird die
        Meldung vorgemerkt und nachgeholt, sobald er geschlossen ist (egl_pending)."""
        job["message"] = "Melde Stand an den Epic Launcher …"
        job.pop("eglBusy", None)
        self._exec(job, BRIDGE + ["export", app])
        if job.get("eglBusy"):
            egl_pending_add(app)

    def _exec(self, job, cmd, extra_env=None):
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", SICCORA_SETTINGS=settings.PATH,
                   SICCORA_WORKERS=str(_connections()), **(extra_env or {}))
        with self._lock:
            if job["status"] != "running":
                return False
            proc = self._procs[job["id"]] = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace")
        began = time.time()
        debuglog.job_line(job, f">>> {' '.join(os.path.basename(c) if os.path.isabs(c) else c for c in cmd)}")
        quiet = 0.0
        for line in proc.stdout:
            # Fortschrittszeilen nur alle 2 s ins Protokoll (bei DevKits sonst ueber 100 MB)
            if line.startswith("Verification progress") or "[DLManager] INFO:" in line and "Progress:" not in line:
                if time.time() - quiet >= 2:
                    quiet = time.time()
                    debuglog.job_line(job, line.rstrip())
            else:
                debuglog.job_line(job, line.rstrip())
            self._parse(job, line.rstrip())
        code = proc.wait()
        debuglog.job_line(job, f"<<< beendet mit {code} nach {time.time() - began:.1f}s, Status {job['status']}")
        with self._lock:
            self._procs.pop(job["id"], None)
        return code == 0 and job["status"] == "running"

    @staticmethod
    def _parse(job, line):
        if not line.strip():
            return
        if line.startswith("EGL_BUSY"):
            job["eglBusy"] = True
        if m := RE_MOVE.search(line):
            done, total = int(m.group(1)), int(m.group(2))
            job["progress"] = 100.0 * done / max(total, 1)
            job["downloadedMb"], job["downloadMb"] = done / 1048576, total / 1048576
        if line.startswith("MOVE_RECORDED"):
            job["moveRecorded"] = True
        if m := RE_SHM.search(line):
            job["shmNeeded"] = float(m.group(1))
        log = job["log"]
        shown = hide_servers(line)  # nur die Anzeige - ausgewertet wird weiter die Originalzeile
        if m := RE_VERIFY.search(line):
            # tausende Fortschrittszeilen -> im Protokoll nur die jeweils letzte behalten
            if log and log[-1].startswith("Verification progress"):
                log[-1] = shown.strip()
            else:
                log.append(shown.strip())
            num, total = int(m.group(1)), int(m.group(2))
            job.update(phase="verify", verifyNum=num, verifyTotal=total, readSpeed=float(m.group(4)),
                       progress=float(m.group(3)), eta="")
            job["message"], job["msgVars"] = "Prüfe Dateien …", {}
            if num >= total:
                job["verified"] = True
            return
        job["log"] = (log + [shown])[-200:]
        if line.startswith(("VERIFY_OK", "VERIFY_BAD", "VERIFY_SKIPPED")):
            job["afterResult"] = line.split()[0][7:].lower()
            if line.startswith("VERIFY_OK"):
                job["verifyTotal"] = job.get("verifyTotal") or int(line.split()[1])
        elif line.startswith("ADOPT_"):
            job["adoptResult"] = {"ADOPT_WRONG_FOLDER": "wrong", "ADOPT_NEEDS_VERIFY": "verify"}.get(line.strip(), "ok")
        elif RE_VERIFY_BAD.search(line):
            job["verifyBad"] = (job.get("verifyBad") or 0) + 1
        elif "Verification finished successfully" in line:
            job["verified"] = True
            job["message"] = "Prüfung fertig – alles in Ordnung."
        elif "Verification failed" in line:
            job["verified"] = True
            job["message"] = "Prüfung fertig – lade defekte und fehlende Dateien neu …"
        elif m := RE_WRITTEN.search(line):
            job["writtenMb"] = float(m.group(1))
            if dm := RE_DONE_MB.search(line):
                job["downloadedMb"] = float(dm.group(1))
        elif m := RE_DISK.search(line):
            job["writeSpeed"], job["readSpeed"] = float(m.group(1)), float(m.group(2))
        elif m := RE_CACHE.search(line):
            job["cacheMb"], job["tasks"] = float(m.group(1)), int(m.group(2))
        if m := RE_PROGRESS.search(line):
            job["phase"] = "download"
            base = job.get("resumeBase") or 0.0
            job["progress"], job["eta"] = base + (100.0 - base) * float(m.group(1)) / 100.0, m.group(2)
            job["message"] = "Lädt defekte und fehlende Dateien neu …" if job["action"] == "repair" else "Lädt herunter …"
        elif m := RE_RESUMED.search(line):
            job["message"], job["msgVars"] = "Setze fort – {n} Dateien waren schon fertig …", {"n": m.group(1)}
        elif m := RE_SPEED.search(line):
            job["speed"] = float(m.group(1))
        elif m := RE_DONE_MB.search(line):
            job["downloadedMb"] = float(m.group(1))
        elif m := RE_DL_SIZE.search(line):
            job["downloadMb"] = float(m.group(1))
        elif m := RE_INSTALL_SIZE.search(line):
            job["installMb"] = float(m.group(1))
        elif m := RE_PRUNE.search(line):
            job["progress"] = 100.0 * int(m.group(1)) / max(int(m.group(2)), 1)
        elif m := RE_PRUNED.search(line):
            job["pruned"] = (int(m.group(1)), int(m.group(2)))
        elif m := RE_INSTALL_PATH.search(line):
            path = m.group(1).strip()
            if "installPath" not in job:
                # Lag dort schon vorher etwas (z. B. ein kopiertes Spiel)? Dann loescht ein Abbruch den Ordner nie.
                # Nur beim ersten Lauf pruefen - nach "Fortsetzen" liegen dort ja unsere eigenen Teildateien.
                try:
                    job["folderExisted"] = os.path.isdir(path) and any(os.scandir(path))
                except OSError:
                    job["folderExisted"] = True  # im Zweifel nichts loeschen
            job["installPath"] = path
        elif RE_UP_TO_DATE.search(line):
            job["message"] = ("Fertig – Versionsstand aktualisiert, es musste nichts geladen werden."
                              if job["action"] == "update" else "Bereits aktuell – nichts zu tun.")
        elif "Waiting for installation to finish" in line:
            job["message"] = "Schließe Installation ab …"


def _load_jobs():
    """Offene Auftraege vom letzten Mal - laufen nicht von selbst weiter, sondern warten pausiert."""
    try:
        with open(JOBS_FILE, encoding="utf-8") as f:
            jobs = json.load(f)
    except (OSError, ValueError):
        return []
    for job in jobs:
        job["log"] = []
        if job["status"] in ("queued", "running"):
            job["status"] = "paused"
            job["message"] = "Beim letzten Beenden angehalten – mit „Fortsetzen“ geht es weiter."
    return [j for j in jobs if j["status"] == "paused"]


def _is_partial_install(job):
    """Nur loeschen, was dieser Auftrag gerade neu angelegt hat - nie etwas Fertiges.

    Bedingungen: Legendary hat den Zielordner genannt, er liegt UNTER dem
    gewaehlten Installationsordner (nicht gleich), und der Eintrag steht weder
    in Legendarys noch in der Epic-Launcher-Installationsliste.
    """
    path, base = job.get("installPath"), job.get("basePath")
    if not path or not base or not os.path.isdir(path) or job.get("folderExisted", True):
        return False  # Ordner gab es schon vor dem Auftrag (oder unbekannt) -> nie loeschen
    path, base = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(base))
    if path == base or os.path.commonpath([path, base]) != base:
        return False
    try:
        with open(os.path.join(legendary_dir(), "installed.json"), encoding="utf-8") as f:
            if job["appName"] in json.load(f):
                return False
    except (OSError, ValueError):
        return False  # im Zweifel nichts loeschen
    try:
        with open(os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Epic", "UnrealEngineLauncher",
                               "LauncherInstalled.dat"), encoding="utf-8") as f:
            listed = {os.path.normcase(os.path.abspath(e["InstallLocation"]))
                      for e in json.load(f).get("InstallationList", [])}
        if path in listed:
            return False
    except (OSError, ValueError):
        pass
    return True


# --- Meldungen an den Epic Launcher, die warten muessen, bis er geschlossen ist ---------------
EGL_PENDING = "egl_pending.json"


def egl_pending_add(app):
    from .epic import _load, _save
    pending = _load(EGL_PENDING, [])
    if app not in pending:
        _save(EGL_PENDING, pending + [app])


def _total_ram_mib():
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(st)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return 0
    return st.ullTotalPhys // 1048576


def _shm_args(needed_mib, last=False):
    """Zusatz-Argumente fuer den Neuversuch (immer mit gruppierter Reihenfolge).
    1. Versuch: mehr Zwischenspeicher nur, wenn er in ein Drittel des RAM passt - sonst reicht meist
       schon die gruppierte Reihenfolge mit Legendarys 2 GB.
    2. Versuch (gruppiert hat nicht gereicht): bis zur Haelfte des RAM, sonst None = aufgeben."""
    # 1. Versuch bewusst OHNE mehr Zwischenspeicher: die gruppierte Reihenfolge braucht selbst beim ARK
    # DevKit unter 2 GB, und jeder zusaetzliche GB Zwischenspeicher belastet Windows' Speicher sofort
    # (Test-VM mit 16 GB: "Auslagerungsdatei zu klein" bei 4,2 GB Zwischenspeicher + 64 Verbindungen).
    if not last:
        return []
    wanted = int(needed_mib) + 64
    return ["--max-shared-memory", str(wanted)] if wanted <= _total_ram_mib() // 3 else None


def egl_startup_check():
    """Einmal beim Start: Installationen, die der Epic Launcher mit falschem Stand fuehrt (z. B. von
    einer aelteren Launcher-Version), zur Meldung vormerken - egl_pending_flush erledigt den Rest."""
    from .egl_sync import needs_sync
    try:
        with open(os.path.join(legendary_dir(), "installed.json"), encoding="utf-8") as f:
            own = json.load(f)
    except (OSError, ValueError):
        return []
    found = [app for app, ig in own.items()
             if needs_sync(app, ig.get("version") or "", ig.get("install_path") or "", ig.get("install_tags") or [], legendary_dir())]
    for app in found:
        egl_pending_add(app)
    if found:
        debuglog.log("egl", "Abgleich beim Start vorgemerkt", apps=found)
    return found


def egl_pending_flush():
    """Vorgemerkte Meldungen nachholen (Aufruf im Hintergrund). Liefert die erledigten Apps."""
    from .epic import _load, _save
    from .egl_sync import egl_running
    pending = _load(EGL_PENDING, [])
    if not pending or egl_running():
        return []
    done = []
    for app in pending:
        out = subprocess.run(BRIDGE + ["export", app], capture_output=True, text=True, errors="replace",
                             env=dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8"),
                             creationflags=NO_WINDOW, timeout=600)
        debuglog.log("egl", "Nachgeholte Meldung", app=app, code=out.returncode, text=out.stdout[-500:])
        if out.returncode == 0 and "EGL_BUSY" not in out.stdout:
            done.append(app)
    _save(EGL_PENDING, [a for a in _load(EGL_PENDING, []) if a not in done])
    return done


def _vault(job):
    """Zwischenordner fuer Fab-Assets - beim Anlegen des Auftrags festgehalten, damit ein
    pausierter Download nach einer Aenderung der Einstellung am alten Ort weitermacht."""
    fab = job.get("fab") or {}
    if not fab.get("vault"):
        fab["vault"] = settings.get("vaultDir")
    return fab["vault"]


def hide_servers(text):
    return RE_SERVER.sub("[Server]", text)


def _installed_version(app):
    try:
        with open(os.path.join(legendary_dir(), "installed.json"), encoding="utf-8") as f:
            return (json.load(f).get(app) or {}).get("version")
    except (OSError, ValueError):
        return None


def _connections():
    """Parallele Verbindungen. Beim Tempolimit weniger (Epic liefert etwa 0,5 MB/s je
    Verbindung) - das Tempo wird so gleichmaessiger."""
    # Die Wahl des Nutzers gilt - mehr Verbindungen als GB Arbeitsspeicher zeigt nur eine Warnung
    # in den Einstellungen (jede Verbindung ist ein eigener Prozess, ~45 MB)
    workers, limit = settings.get("maxWorkers"), settings.get("speedLimit")
    return min(workers, max(2, limit * 2)) if limit else workers


def _workers():
    return ["--max-workers", str(_connections())]


def _lane(job):
    return "fab" if job["action"] == "fab" else "main"


def _kill_tree(proc):
    """Legendary startet eigene Download-Prozesse - alle mitbeenden."""
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)

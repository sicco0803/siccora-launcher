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

from .epic import DATA_DIR, legendary_dir
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
                "fab": "Fab-Asset", "modify": "Komponenten ändern"}


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
    def add(self, action, app_name, title, base_path=None, from_egl=False, fab=None, label=None, components=None):
        with self._lock:
            if any(j["appName"] == app_name and j["status"] in OPEN for j in self._jobs):
                return {"error": tr("{title} ist bereits in der Liste (ggf. pausiert – dort fortsetzen).", title=title)}
            job = {"id": next(self._ids), "action": action, "label": label or ACTION_LABEL[action], "fab": fab,
                   "components": components,  # {"selected": [...], "removed": [...], "adding": bool}
                   "appName": app_name, "title": title, "basePath": base_path, "fromEgl": from_egl,
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
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(JOBS_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(keep, f)
            os.replace(JOBS_FILE + ".tmp", JOBS_FILE)
        except OSError:
            pass

    def _cleanup(self, job):
        """Reste eines abgebrochenen Auftrags entfernen."""
        app = job["appName"]
        try:
            os.remove(os.path.join(legendary_dir(), "tmp", f"{app}.resume"))
        except OSError:
            pass
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
            try:
                self._run(job)
            except Exception as e:  # nie den Arbeiter sterben lassen
                if job["status"] == "running":
                    job["status"], job["message"] = "failed", hide_servers(f"{type(e).__name__}: {e}")
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
        app = job["appName"]
        if job["fromEgl"]:
            job["message"] = "Übernehme Installation aus dem Epic Launcher …"
            if not self._exec(job, BRIDGE + ["import", app]):
                if self._stopped(job):
                    return
                return self._fail(job, "Übernahme aus dem Epic Launcher fehlgeschlagen.")

        if job["action"] == "uninstall":
            job["message"] = "Entferne Dateien …"
            ok = self._exec(job, LEGENDARY + ["-y", "uninstall", app])
        else:
            args = ["-y", "install", app, "--skip-sdl", "--skip-dlcs"]
            if job["action"] == "install" and job["basePath"]:
                args += ["--base-path", job["basePath"]]
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
            job["message"] = "Bereite Prüfung vor …" if job["action"] == "repair" else "Bereite Download vor …"
            ok = self._exec(job, LEGENDARY + args + _workers())
            if ok and job["status"] == "running":
                job["message"] = "Melde Stand an den Epic Launcher …"
                self._exec(job, BRIDGE + ["export", app])  # nicht kritisch

        if self._stopped(job):
            return
        if ok:
            job["status"], job["progress"] = "done", 100.0
            if job["action"] == "repair" and job.get("verifyTotal"):
                bad = job.get("verifyBad") or 0
                job["message"] = ("Fertig – {bad} von {n} Dateien waren defekt oder fehlten und wurden neu geladen."
                                  if bad else "Fertig – alle {n} Dateien sind in Ordnung.")
                job["msgVars"] = {"bad": bad, "n": job["verifyTotal"]}
            elif not job["message"].startswith("Bereits"):
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

        job["message"] = "Melde Stand an den Epic Launcher …"
        self._exec(job, BRIDGE + ["export", app])  # nicht kritisch
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
        if job["status"] == "running":
            job["status"], job["message"] = "failed", msg

    def _exec(self, job, cmd, extra_env=None):
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", SICCORA_SETTINGS=settings.PATH,
                   SICCORA_WORKERS=str(_connections()), **(extra_env or {}))
        with self._lock:
            if job["status"] != "running":
                return False
            proc = self._procs[job["id"]] = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            self._parse(job, line.rstrip())
        code = proc.wait()
        with self._lock:
            self._procs.pop(job["id"], None)
        return code == 0 and job["status"] == "running"

    @staticmethod
    def _parse(job, line):
        if not line.strip():
            return
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
        if RE_VERIFY_BAD.search(line):
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
            job["installPath"] = m.group(1).strip()
        elif RE_UP_TO_DATE.search(line):
            job["message"] = "Bereits aktuell – nichts zu tun."
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
    if not path or not base or not os.path.isdir(path):
        return False
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
        with open(r"C:\ProgramData\Epic\UnrealEngineLauncher\LauncherInstalled.dat", encoding="utf-8") as f:
            listed = {os.path.normcase(os.path.abspath(e["InstallLocation"]))
                      for e in json.load(f).get("InstallationList", [])}
        if path in listed:
            return False
    except (OSError, ValueError):
        pass
    return True


def _vault(job):
    """Zwischenordner fuer Fab-Assets - beim Anlegen des Auftrags festgehalten, damit ein
    pausierter Download nach einer Aenderung der Einstellung am alten Ort weitermacht."""
    fab = job.get("fab") or {}
    if not fab.get("vault"):
        fab["vault"] = settings.get("vaultDir")
    return fab["vault"]


def hide_servers(text):
    return RE_SERVER.sub("[Server]", text)


def _connections():
    """Parallele Verbindungen. Beim Tempolimit weniger (Epic liefert etwa 0,5 MB/s je
    Verbindung) - das Tempo wird so gleichmaessiger."""
    workers, limit = settings.get("maxWorkers"), settings.get("speedLimit")
    return min(workers, max(2, limit * 2)) if limit else workers


def _workers():
    return ["--max-workers", str(_connections())]


def _lane(job):
    return "fab" if job["action"] == "fab" else "main"


def _kill_tree(proc):
    """Legendary startet eigene Download-Prozesse - alle mitbeenden."""
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)

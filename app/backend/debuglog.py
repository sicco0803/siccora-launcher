"""Ausfuehrliches Protokoll zur Fehlersuche.

Nur aktiv, wenn die Datei %USERPROFILE%\\.siccora-debug\\enabled existiert -
ohne sie passiert hier nichts. Protokolle liegen im selben Ordner unter logs\\. Alles bleibt auf dem PC, nichts wird gesendet.
Keine Anmeldedaten; Server-Adressen und alles, was nach Token/Passwort aussieht, wird ausgeblendet.

    logs/debug-JJJJ-MM-TT.log            Ablauf: Start, Updates, Abgleich, Fehler, Zeiten
    logs/jobs/JJJJMMTT-HHMMSS_<app>_<aktion>.log   komplette Ausgabe eines Download-Auftrags
"""
import json
import os
import re
import threading
import time
import traceback

# Bewusst im Benutzerordner und nicht in AppData: Programme aus App-Paketen (MSIX) sehen bei
# AppData eine eigene, umgeleitete Kopie - Schalter und Protokolle waeren dann nicht gemeinsam sichtbar.
DEBUG_HOME = os.path.join(os.path.expanduser("~"), ".siccora-debug")
FLAG = os.path.join(DEBUG_HOME, "enabled")
LOG_DIR = os.path.join(DEBUG_HOME, "logs")
JOB_DIR = os.path.join(LOG_DIR, "jobs")
KEEP_DAYS = 14

ENABLED = os.path.isfile(FLAG)
_lock = threading.Lock()
_job_files = {}  # job-id -> Pfad
# wie downloads.hide_servers (hier eigene Kopie, sonst gegenseitiger Import)
RE_SERVER = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+|\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|cloud|gg)\b(?:[/:]\S*)?", re.I)
# auch in verschachteltem JSON (\"access_token\": \"...\") und "Bearer <token>"
RE_SECRET = re.compile(r"(?i)\b(access_token|refresh_token|token|authorization|password|passwort|secret|exchange_?code|code)"
                       r"([\\\"']*\s*[:=]\s*[\\\"']*)(?:bearer\s+)?[^\s\\\"',}]+")
RE_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
RE_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+){0,2}")


def _clean(text):
    text = RE_SECRET.sub(r"\1\2[hidden]", str(text))
    text = RE_JWT.sub("[hidden]", RE_BEARER.sub("Bearer [hidden]", text))
    return RE_SERVER.sub("[Server]", text)


def _write(path, text):
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def log(area, msg, /, **data):  # "/": Zusatzangaben duerfen auch "msg" oder "area" heissen
    """Eine Zeile ins Tagesprotokoll, z. B. log("update", "Download fertig", mb=16.7, s=8.1)."""
    if not ENABLED:
        return
    try:
        extra = " " + json.dumps(data, ensure_ascii=False, default=str) if data else ""
        line = f"{time.strftime('%H:%M:%S')} [{area}] {msg}{extra}\n"
        _write(os.path.join(LOG_DIR, f"debug-{time.strftime('%Y-%m-%d')}.log"), _clean(line))
    except Exception:
        pass  # Protokoll darf den Launcher nie stoeren


def exception(area, msg, /):
    """Aufruf aus einem except-Block: Meldung samt Stapel."""
    if ENABLED:
        log(area, msg + "\n" + traceback.format_exc().rstrip())


def job_start(job):
    if not ENABLED:
        return
    safe = re.sub(r"[^\w.-]+", "_", f"{job.get('appName') or job.get('title')}_{job.get('action')}")[:80]
    _job_files[job["id"]] = os.path.join(JOB_DIR, f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.log")
    log("job", "Start", id=job["id"], app=job.get("appName"), title=job.get("title"), action=job.get("action"),
        file=os.path.basename(_job_files[job["id"]]))


def job_line(job, line):
    path = _job_files.get(job.get("id"))
    if ENABLED and path:
        try:
            _write(path, _clean(f"{time.strftime('%H:%M:%S')} {line}\n"))
        except Exception:
            pass


def job_end(job, seconds):
    if ENABLED:
        log("job", "Ende", id=job["id"], app=job.get("appName"), action=job.get("action"), status=job.get("status"),
            message=job.get("message"), s=round(seconds, 1))
        _job_files.pop(job["id"], None)


def prune():
    """Alte Protokolle wegraeumen (beim Start)."""
    if not ENABLED:
        return
    limit = time.time() - KEEP_DAYS * 86400
    for folder in (LOG_DIR, JOB_DIR):
        try:
            for e in os.scandir(folder):
                if e.is_file() and e.stat().st_mtime < limit:
                    os.remove(e.path)
        except OSError:
            pass

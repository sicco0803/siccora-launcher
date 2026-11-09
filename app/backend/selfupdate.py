"""Neue Launcher-Versionen aus dem oeffentlichen GitHub-Repo.

Ablauf: GitHub nach dem neuesten Release fragen (hoechstens alle 6 Stunden, ohne
Anmeldung, es gehen keine Daten mit), das Setup laden, gegen die Pruefsumme pruefen,
die GitHub selbst zum Release angibt, und still ueber die alte Version installieren.

Sicherheit: Geladen wird nur von github.com aus genau diesem Repo, nur eine Datei mit
dem erwarteten Namen, und nur, wenn die Pruefsumme stimmt. Ist die laufende exe
signiert, muss das Setup vom selben Herausgeber signiert sein.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import requests

from .epic import DATA_DIR

REPO = "sicco0803/siccora-launcher"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
ASSET = re.compile(r"^SiccoraLauncher-(\d+(?:\.\d+){1,3})-Setup\.exe$")
CACHE = os.path.join(DATA_DIR, "self_update.json")
UPDATE_DIR = os.path.join(DATA_DIR, "update")
MAX_AGE = 6 * 3600
RE_NOTES_BLOCK = re.compile(r"<!--\s*notes:([a-z]{2})\s*\n(.*?)-->", re.S)
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "SiccoraLauncher"}


def _version(text):
    try:
        return tuple(int(p) for p in str(text).lstrip("vV").split("."))
    except ValueError:
        return ()


def parse_notes(body):
    """Patch Notes aus dem Release-Text: {"en": [Stichpunkte], "de": [...], ...}.

    Englisch steht sichtbar unter "## What's new", die anderen Sprachen in unsichtbaren
    Bloecken <!-- notes:de ... -->. Nur Stichpunkte, ohne Formatierung; angezeigt als reiner Text.
    """
    body = (body or "").replace("\r\n", "\n")
    notes = {}
    for code, block in RE_NOTES_BLOCK.findall(body):
        notes[code] = _bullets(block)
    visible = RE_NOTES_BLOCK.sub("", body)
    section = re.search(r"^##\s*What's new\s*$(.*?)(?=^##\s|\Z)", visible, re.M | re.S | re.I)
    notes["en"] = _bullets(section.group(1) if section else visible)
    return {k: v for k, v in notes.items() if v}


def _bullets(text):
    out = []
    for m in re.finditer(r"^\s*[-*•]\s+(.+?)\s*$", text, re.M):
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", m.group(1))  # Links -> nur der Text
        line = re.sub(r"[*_`]{1,3}", "", line).strip()
        if line:
            out.append(line[:240])
    return out[:25]


def _fetch():
    """Neuestes Release bei GitHub abfragen."""
    r = requests.get(API, headers=HEADERS, timeout=20)
    if r.status_code == 404:  # noch kein Release veroeffentlicht
        return {"tag": None, "checked": time.time()}
    r.raise_for_status()
    data = r.json()
    setup = None
    for a in data.get("assets", []):
        m = ASSET.match(a.get("name", ""))
        url = a.get("browser_download_url", "")
        digest = a.get("digest") or ""
        if m and url.startswith(DOWNLOAD_PREFIX) and digest.startswith("sha256:"):
            setup = {"name": a["name"], "url": url, "sha256": digest[7:].lower(), "size": a.get("size", 0)}
    return {"tag": data.get("tag_name"), "page": data.get("html_url"), "draft": data.get("draft"),
            "prerelease": data.get("prerelease"), "setup": setup, "notes": parse_notes(data.get("body")),
            "checked": time.time()}


def check(current, force=False):
    """{"current", "latest", "available", "page", "setup": {...} | None, "checked"}"""
    try:
        with open(CACHE, encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        cached = None
    if cached and not force and time.time() - cached.get("checked", 0) < MAX_AGE:
        release = cached
    else:
        try:
            release = _fetch()
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump(release, f)
        except (requests.RequestException, ValueError):  # offline, GitHub-Limit: letzter bekannter Stand
            release = cached or {"tag": None, "checked": 0}
    latest = (release.get("tag") or "").lstrip("vV") or None
    available = bool(latest) and not release.get("draft") and not release.get("prerelease") \
        and _version(latest) > _version(current)
    page = release.get("page") if str(release.get("page") or "").startswith(f"https://github.com/{REPO}/") else None
    return {"current": current, "latest": latest, "available": available, "page": page,
            "setup": release.get("setup") if available else None, "notes": release.get("notes") or {},
            "checked": release.get("checked")}


def _signer(path):
    """Herausgeber einer gueltig signierten Datei als "Name|Aussteller-Organisation", sonst None.
    Bewusst nicht der Fingerabdruck: das Zertifikat wird jaehrlich erneuert, der Fingerabdruck
    wechselt dabei. Die Organisation stellt sicher, dass es dieselbe Zertifizierungsstelle ist."""
    cmd = ("$s = Get-AuthenticodeSignature -LiteralPath $env:SICCORA_SIGCHECK; "
           "if ($s.Status -eq 'Valid') { $c = $s.SignerCertificate; "
           "$c.GetNameInfo('SimpleName', $false) + '|' + [regex]::Match($c.Issuer, 'O=([^,]+)').Groups[1].Value }")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                         env=dict(os.environ, SICCORA_SIGCHECK=path), capture_output=True, text=True,
                         timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out.stdout.strip() or None


def download(info):
    """Setup laden und pruefen. Gibt den Pfad zurueck oder wirft ValueError."""
    setup = info.get("setup") or {}
    if not ASSET.match(setup.get("name", "")) or not setup.get("url", "").startswith(DOWNLOAD_PREFIX):
        raise ValueError("Kein passendes Setup im Release gefunden.")
    os.makedirs(UPDATE_DIR, exist_ok=True)
    for old in os.listdir(UPDATE_DIR):  # alte Setups wegraeumen
        try:
            os.remove(os.path.join(UPDATE_DIR, old))
        except OSError:
            pass
    path = os.path.join(UPDATE_DIR, setup["name"])
    sha = hashlib.sha256()
    with requests.get(setup["url"], headers={"User-Agent": "SiccoraLauncher"}, stream=True, timeout=60) as r:
        r.raise_for_status()
        if not r.url.startswith(("https://github.com/", "https://objects.githubusercontent.com/",
                                 "https://release-assets.githubusercontent.com/")):
            raise ValueError("Unerwartete Download-Adresse.")
        with open(path + ".part", "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                sha.update(chunk)
                f.write(chunk)
    if sha.hexdigest() != setup["sha256"]:
        os.remove(path + ".part")
        raise ValueError("Prüfsumme des Updates stimmt nicht – Download verworfen.")
    os.replace(path + ".part", path)
    if getattr(sys, "frozen", False):
        mine = _signer(sys.executable)
        if mine and _signer(path) != mine:
            os.remove(path)
            raise ValueError("Das Update ist nicht vom selben Herausgeber signiert – verworfen.")
    return path


def install(path):
    """Setup still starten (Fortschrittsfenster, keine Fragen). Es schliesst den Launcher
    und startet ihn danach neu (installer.iss: [Run] mit WizardSilent)."""
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     close_fds=True, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))

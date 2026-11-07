"""App-Einstellungen in %LOCALAPPDATA%\\SiccoraLauncher\\settings.json.

Fehlende Werte kommen aus DEFAULTS; save() prueft jeden Wert, bevor er
gespeichert wird - Unsinniges (z. B. ein nicht vorhandener Ordner) wird abgelehnt.
"""
import configparser
import json
import os

from .epic import DATA_DIR, legendary_dir
from .i18n import LANGUAGES, tr

PATH = os.path.join(DATA_DIR, "settings.json")
WORKER_CHOICES = (8, 16, 24, 32, 48, 64)
SPEED_CHOICES = (0, 1, 2, 5, 10, 20, 50, 100)  # MB/s, 0 = keine Begrenzung


def _legendary_workers():
    """Bisheriger Wert aus Legendarys config.ini (dort hatten wir 32 eingetragen)."""
    cfg = configparser.ConfigParser()
    try:
        cfg.read(os.path.join(legendary_dir(), "config.ini"), encoding="utf-8")
        return cfg.getint("Legendary", "max_workers", fallback=16)
    except (configparser.Error, ValueError):
        return 16


DEFAULTS = {
    "language": None,          # None = beim ersten Start die Windows-Sprache
    "showGames": True,
    "installDir": None,
    "vaultDir": os.path.join(DATA_DIR, "vault"),
    "maxWorkers": None,        # None = aus Legendarys config.ini bzw. 16
    "speedLimit": 0,           # MB/s fuer Downloads, 0 = keine Begrenzung
    "useEpicVault": True,      # Fab-Assets aus Epics VaultCache kopieren statt neu laden (nur lesend)
    "keepAssets": False,       # geladene Fab-Assets im Zwischenordner behalten (wie Epics Vault)
    "closeToTray": False,      # X versteckt nur das Fenster, der Launcher laeuft im Infobereich weiter
}


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    data = {**DEFAULTS, **saved}
    if data["maxWorkers"] is None:
        data["maxWorkers"] = _legendary_workers()
    return data


def get(key):
    return load()[key]


def _write(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    stored = {k: v for k, v in data.items() if k in DEFAULTS}
    with open(PATH + ".tmp", "w", encoding="utf-8") as f:
        json.dump(stored, f, indent=1)
    os.replace(PATH + ".tmp", PATH)


def _local_dir(path):
    return bool(path) and not path.startswith(("\\\\", "//")) and os.path.isdir(path)


def _is_epic_vault(path):
    """Epic-Launcher-VaultCache erkennen: Unterordner mit 'manifest'-Datei + 'data'-Ordner.

    Unser Zwischenordner wird nach dem Kopieren geleert - dort wuerden wir
    Epics Cache-Eintraege desselben Assets mitloeschen.
    """
    try:
        for entry in os.scandir(path):
            if entry.is_dir() and os.path.isfile(os.path.join(entry.path, "manifest")) \
                    and os.path.isdir(os.path.join(entry.path, "data")):
                return True
    except OSError:
        pass
    return False


def save(changes):
    """Teilweise Aenderungen pruefen und uebernehmen. Gibt die neuen Einstellungen zurueck."""
    data = load()
    for key, value in (changes or {}).items():
        if key == "language":
            if value not in LANGUAGES:
                return {"error": tr("Unbekannte Sprache.")}
        elif key in ("showGames", "useEpicVault", "keepAssets", "closeToTray"):
            value = bool(value)
        elif key in ("installDir", "vaultDir"):
            if value is None:  # zuruecksetzen auf Standard
                value = DEFAULTS[key]
            elif not _local_dir(value):
                return {"error": tr("Ordner existiert nicht oder ist ein Netzwerkpfad.")}
            elif key == "vaultDir" and _is_epic_vault(value):
                return {"error": tr("Das ist der Vault-Cache des Epic Launchers – bitte einen eigenen Ordner wählen.")}
        elif key == "maxWorkers":
            if int(value) not in WORKER_CHOICES:
                return {"error": tr("Ungültige Anzahl Verbindungen.")}
            value = int(value)
        elif key == "speedLimit":
            if int(value) not in SPEED_CHOICES:
                return {"error": tr("Ungültiges Tempolimit.")}
            value = int(value)
        else:
            continue  # unbekannte Schluessel ignorieren
        data[key] = value
    _write(data)
    return data

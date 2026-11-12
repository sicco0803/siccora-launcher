"""Uebersetzungen der Meldungen aus dem Hintergrund (Gegenstueck zu ui/i18n.js).

Der deutsche Text ist der Schluessel; fehlt eine Uebersetzung, gilt Englisch.
Je Sprache eine Datei lang_xx.py. Platzhalter: tr("{n} Dateien", n=3).
"""
from . import lang_es, lang_fr, lang_it, lang_nl, lang_pl, lang_pt

_lang = "de"

EN = {
    # Auftragsarten
    "Installieren": "Install",
    "Update": "Update",
    "Deinstallieren": "Uninstall",
    "Reparieren": "Verify",
    "Fab-Asset": "Fab asset",
    "Zum Projekt hinzufügen": "Add to project",
    "In Engine installieren": "Install to engine",
    "Projekt erstellen": "Create project",
    "Komponenten ändern": "Change components",

    "Projekt nicht gefunden.": "Project not found.",

    "Bestätigung passt nicht zum Projektnamen.": "Confirmation does not match the project name.",
    "Nur reine Unreal-Engine-Projekte können gelöscht werden – keine DevKit- oder ModKit-Projekte.":
        "Only plain Unreal Engine projects can be deleted – no DevKit or ModKit projects.",
    "Das Projekt liegt direkt auf einem Laufwerk.": "The project is located directly on a drive.",
    "Das Projekt liegt in oder um eine installierte Engine, ein DevKit oder ein Spiel.":
        "The project is located inside or around an installed engine, DevKit or game.",
    "Der Projektordner ist ein geschützter Windows-Ordner.": "The project folder is a protected Windows folder.",
    "Der Projektordner enthält eine Engine.": "The project folder contains an engine.",
    "Der Ordner sieht nicht wie ein Unreal-Projekt aus (kein Content- oder Config-Ordner).":
        "The folder does not look like an Unreal project (no Content or Config folder).",
    "Im Projektordner liegen weitere Projekte – zum Schutz wird nicht gelöscht.":
        "The project folder contains other projects – not deleted for safety.",
    "Das Projekt ist gerade geöffnet oder Dateien sind gesperrt – bitte den Editor schließen.":
        "The project is open or files are locked – please close the editor.",
    "Löschen abgebrochen oder fehlgeschlagen.": "Deletion was cancelled or failed.",

    "Bereite Prüfung vor …": "Preparing verification …",
    "Prüfe Dateien …": "Verifying files …",
    "Prüfung fertig – alles in Ordnung.": "Verification done – everything is fine.",
    "Prüfung fertig – lade defekte und fehlende Dateien neu …": "Verification done – re-downloading damaged and missing files …",
    "Lädt defekte und fehlende Dateien neu …": "Re-downloading damaged and missing files …",
    "Fertig – alle {n} Dateien sind in Ordnung.": "Done – all {n} files are fine.",
    "Fertig – {bad} von {n} Dateien waren defekt oder fehlten und wurden neu geladen.":
        "Done – {bad} of {n} files were damaged or missing and have been re-downloaded.",

    "Startprogramm nicht gefunden.": "Launch executable not found.",

    "Die Asset-Version passt nicht zur Engine des Ziels.": "The asset version does not match the target engine.",

    "Asset nicht gefunden.": "Asset not found.",
    "Der Ordner gehört zu einer installierten Engine oder einem DevKit.": "The folder belongs to an installed engine or DevKit.",
    "Das Asset wird gerade verwendet. Warte, bis der Auftrag fertig ist.": "The asset is in use. Wait until the job has finished.",
    "Der Epic Launcher läuft gerade. Bitte schließen, er könnte diesen Ordner benutzen.":
        "The Epic Games Launcher is running. Please close it, it might be using this folder.",
    "Dateien sind gerade in Benutzung oder der Zugriff ist nicht erlaubt.": "Files are in use or access is not allowed.",
    "Der Ordner konnte nicht vollständig gelöscht werden.": "The folder could not be deleted completely.",

    "Diese Version ist derzeit nicht ladbar. Epic bietet sie nicht mehr an.": "This version cannot be downloaded right now. Epic no longer offers it.",

    "Spiel konnte nicht gestartet werden: {msg}": "The game could not be started: {msg}",

    "Ungültiges Tempolimit.": "Invalid speed limit.",

    # Komponenten
    "Bitte Optionen neu öffnen.": "Please reopen the options.",
    "Keine Änderung ausgewählt.": "No change selected.",
    "Nicht genug Speicherplatz.": "Not enough disk space.",
    "Komponenten-Auswahl konnte nicht gespeichert werden.": "Component selection could not be saved.",
    "Entferne abgewählte Komponenten …": "Removing deselected components …",
    "Entfernen der Komponenten fehlgeschlagen.": "Removing the components failed.",
    "Fertig – {n} Dateien abgewählter Komponenten entfernt ({size} GB frei).":
        "Done – {n} files of deselected components removed ({size} GB freed).",

    # Fortschritt
    "Wartet …": "Queued …",
    "Bereite Download vor …": "Preparing download …",
    "Lädt herunter …": "Downloading …",
    "Setze fort – {n} Dateien waren schon fertig …": "Resuming – {n} files were already done …",
    "Schließe Installation ab …": "Finishing installation …",
    "Übernehme Installation aus dem Epic Launcher …": "Taking over installation from the Epic Launcher …",
    "Melde Stand an den Epic Launcher …": "Reporting new state to the Epic Launcher …",
    "Entferne Dateien …": "Removing files …",
    "Kopiere ins Ziel …": "Copying to target …",
    "Fertig.": "Done.",
    "Fertig: {copied} Dateien kopiert.": "Done: {copied} files copied.",
    "Fertig: {copied} Dateien kopiert, {skipped} vorhandene übersprungen.": "Done: {copied} files copied, {skipped} existing skipped.",
    "Bereits aktuell – nichts zu tun.": "Already up to date – nothing to do.",
    "Fertig: {copied} Dateien aus Epics Vault-Cache kopiert.": "Done: {copied} files copied from Epic’s vault cache.",
    "Fertig: {copied} Dateien aus Epics Vault-Cache kopiert, {skipped} vorhandene übersprungen.":
        "Done: {copied} files copied from Epic’s vault cache, {skipped} existing skipped.",
    "Fertig: {copied} Dateien aus behaltenem Asset kopiert.": "Done: {copied} files copied from kept asset.",
    "Fertig: {copied} Dateien aus behaltenem Asset kopiert, {skipped} vorhandene übersprungen.":
        "Done: {copied} files copied from kept asset, {skipped} existing skipped.",

    # Pause / Abbrechen
    "Pausiert – mit „Fortsetzen“ geht es an derselben Stelle weiter.": "Paused – “Resume” continues where it left off.",
    "Beim Schließen angehalten – mit „Fortsetzen“ geht es weiter.": "Stopped when closing – “Resume” continues.",
    "Beim letzten Beenden angehalten – mit „Fortsetzen“ geht es weiter.": "Stopped at last exit – “Resume” continues.",
    "Abgebrochen.": "Cancelled.",
    "Abgebrochen – Zwischendateien gelöscht.": "Cancelled – temporary files deleted.",
    "Abgebrochen – halbfertige Installation gelöscht.": "Cancelled – partial installation deleted.",
    "Abgebrochen – die Installation ist evtl. unvollständig. Bitte später „Update“ oder „Prüfen“ ausführen.":
        "Cancelled – the installation may be incomplete. Please run “Update” or “Verify” later.",
    "Nichts zu pausieren.": "Nothing to pause.",
    "Nichts fortzusetzen.": "Nothing to resume.",
    "Nichts abzubrechen.": "Nothing to cancel.",
    "Entfernen lässt sich nicht pausieren.": "Removing cannot be paused.",
    "Entfernen läuft bereits und lässt sich nicht mehr abbrechen.": "Removal is already running and can no longer be cancelled.",
    "{title} ist bereits in der Liste (ggf. pausiert – dort fortsetzen).": "{title} is already in the list (possibly paused – resume it there).",

    # Fehler
    "Übernahme aus dem Epic Launcher fehlgeschlagen.": "Taking over from the Epic Launcher failed.",
    "Unbekannter Fehler – siehe Protokoll.": "Unknown error – see log.",
    "Download fehlgeschlagen.": "Download failed.",
    "Ein anderes Programm installiert gerade mit Legendary (z. B. eine zweite Launcher-Instanz oder Heroic). "
    "Bitte warten, bis es fertig ist, und dann erneut versuchen.":
        "Another program is currently installing with Legendary (e.g. a second launcher instance or Heroic). "
        "Please wait until it has finished, then try again.",
    "Kein Code im Text gefunden.": "No code found in the text.",
    "Epic hat den Code abgelehnt - vermutlich abgelaufen. Bitte neu holen.": "Epic rejected the code – probably expired. Please get a new one.",
    "Eintrag nicht in der Bibliothek gefunden.": "Entry not found in the library.",
    "Eintrag nicht in der Bibliothek - bitte einmal „Aktualisieren“.": "Entry not in the library – please “Refresh” once.",
    "Nicht installiert.": "Not installed.",
    "UnrealEditor.exe nicht gefunden.": "UnrealEditor.exe not found.",
    "Asset nicht gefunden.": "Asset not found.",
    "Asset nicht in der Fab-Bibliothek gefunden.": "Asset not found in the Fab library.",
    "Zielordner existiert nicht.": "Target folder does not exist.",
    "Diese Version ist nicht direkt ladbar – bitte über das Fab-Plugin im Editor holen.":
        "This version cannot be downloaded directly – please get it via the Fab plugin in the editor.",
    "Ungültiger Pfad in der Dateiliste: {rel}": "Invalid path in file list: {rel}",
    "Unbekannte Asset-Art: {kind}": "Unknown asset type: {kind}",
    "Dateiliste der installierten Version nicht gefunden - Vorschau nicht möglich.":
        "File list of the installed version not found – preview not possible.",

    # Fenster
    "Downloads laufen noch": "Downloads still running",
    "Beim Schließen wird der Download pausiert. Nach dem nächsten Start kannst du ihn unter „Downloads“ an derselben Stelle fortsetzen.\n\nTrotzdem schließen?":
        "Closing will pause the download. After the next start you can resume it under “Downloads” where it left off.\n\nClose anyway?",
    "Store - {name}": "Store - {name}",
    "Mit Epic anmelden": "Sign in with Epic",
    "Unreal-Projekt": "Unreal project",

    # Einstellungen
    "Unbekannte Sprache.": "Unknown language.",
    "Ordner existiert nicht oder ist ein Netzwerkpfad.": "Folder does not exist or is a network path.",
    "Ungültige Anzahl Verbindungen.": "Invalid number of connections.",
    "Das ist der Vault-Cache des Epic Launchers – bitte einen eigenen Ordner wählen.":
        "This is the Epic Launcher's vault cache – please choose a separate folder.",
    "Siccora Launcher öffnen": "Open Siccora Launcher",
    "Beenden": "Quit",
    "Der Launcher läuft im Infobereich weiter.": "The launcher keeps running in the notification area.",
    "Ungültige Autostart-Einstellung.": "Invalid autostart setting.",
    "Kein Update zum Installieren.": "No update to install.",
    "Update konnte nicht geladen werden.": "The update could not be downloaded.",
    "Kein passendes Setup im Release gefunden.": "No matching setup found in the release.",
    "Unerwartete Download-Adresse.": "Unexpected download address.",
    "Prüfsumme des Updates stimmt nicht – Download verworfen.": "The update’s checksum does not match – download discarded.",
    "Das Update ist nicht vom selben Herausgeber signiert – verworfen.": "The update is not signed by the same publisher – discarded.",
    "Übernehmen": "Add existing",
    "Ordner wird geprüft …": "Checking folder …",
    "Fertig – Installation übernommen.": "Done – installation added.",
    "Übernahme fehlgeschlagen.": "Adding the installation failed.",
    "Dieser Ordner passt nicht zu {title}. Bitte den Hauptordner der Installation wählen.": "This folder does not match {title}. Please choose the main folder of the installation.",
    "Diese Installation ist schon im Launcher.": "This installation is already in the launcher.",
    "Bitte den Hauptordner der Installation wählen, nicht das ganze Laufwerk.": "Please choose the main folder of the installation, not the whole drive.",
    "Dieser Ordner gehört schon zu {title}.": "This folder already belongs to {title}.",
    "Fertig – Versionsstand aktualisiert, es musste nichts geladen werden.": "Done – version updated, nothing had to be downloaded.",
    "Bitte zuerst den Unreal Editor schließen.": "Please close the Unreal Editor first.",
    "Nachkontrolle: prüfe die geschriebenen Dateien …": "Checking the written files …",
    "Lade {n} fehlerhafte Dateien neu …": "Downloading {n} faulty files again …",
    "Fertig – Nachkontrolle: {bad} von {n} Dateien waren fehlerhaft und wurden neu geladen.": "Done – check: {bad} of {n} files were faulty and have been downloaded again.",
    "Fertig – Nachkontrolle: alle {n} geänderten Dateien sind in Ordnung.": "Done – check: all {n} changed files are fine.",
    "Fehlerhafte Dateien konnten nicht neu geladen werden – bitte „Prüfen“ ausführen.": "Faulty files could not be downloaded again – please run \"Verify\".",
    "Bitte zuerst das Spiel installieren.": "Please install the game first.",
}

LANGUAGES = ("de", "en", "fr", "es", "it", "pl", "pt", "nl")
_LANGS = {"fr": lang_fr.TEXTS, "es": lang_es.TEXTS, "it": lang_it.TEXTS, "pl": lang_pl.TEXTS, "pt": lang_pt.TEXTS,
          "nl": lang_nl.TEXTS}


def set_lang(lang):
    global _lang
    _lang = lang if lang in LANGUAGES else "en"


def _text(key):
    if _lang == "de":
        return key
    return _LANGS.get(_lang, {}).get(key) or EN.get(key) or key  # Fehlendes: Englisch


def tr(key, **kw):
    text = _text(key)
    if not kw:
        return text
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):  # z. B. Legendary-Logzeile mit {…}
        return text

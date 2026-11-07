'use strict';
// Uebersetzungen. Der deutsche Text ist der Schluessel - fehlt eine
// Uebersetzung, erscheint Englisch. Neue Sprache: Datei in ui/lang/ + backend/lang_xx.py.
// Platzhalter in geschweiften Klammern: t('{n} Dateien', { n: 3 }).

const LANGUAGES = { de: 'Deutsch', en: 'English', fr: 'Français', es: 'Español', it: 'Italiano', pl: 'Polski', pt: 'Português', nl: 'Nederlands' };

const I18N = {
  en: {
    // Navigation & Rahmen
    'Spiele': 'Games',
    'Unreal Engine': 'Unreal Engine',
    'Fab-Bibliothek': 'Fab library',
    'Store': 'Store',
    'Downloads': 'Downloads',
    'Nicht angemeldet': 'Not signed in',
    'Abmelden': 'Sign out',
    'Suchen …': 'Search …',
    'Alle UE-Versionen': 'All UE versions',
    'Alle': 'All',
    'Installiert': 'Installed',
    'Update verfügbar': 'Update available',
    'Aktualisieren': 'Refresh',
    'Neu von Epic laden': 'Reload from Epic',
    'Sprache': 'Language',

    // Anmeldung
    'Mit Epic anmelden': 'Sign in with Epic',
    'Epic-Anmeldeseite öffnen': 'Open Epic sign-in page',
    'Dort anmelden. Danach zeigt der Browser einen Text mit <code>authorizationCode</code>.':
      'Sign in there. Afterwards the browser shows a text containing <code>authorizationCode</code>.',
    'Den ganzen Text kopieren und hier einfügen:': 'Copy the whole text and paste it here:',
    'Anmelden': 'Sign in',
    'Dein Passwort sieht diese App nie. Der Code gilt nur wenige Minuten.':
      'This app never sees your password. The code is only valid for a few minutes.',
    'Melde dich mit deinem Epic-Games-Konto an, um Bibliothek, Engines und Fab-Assets zu sehen.':
      'Sign in with your Epic Games account to see your library, engines and Fab assets.',
    'Es öffnet sich Epics Anmeldefenster. Dein Passwort geht nur an Epic – diese App sieht es nie.':
      'Epic’s sign-in window opens. Your password only goes to Epic – this app never sees it.',
    'Anmeldung klappt nicht? Code manuell einfügen': 'Sign-in not working? Paste the code manually',
    'Anmeldefenster ist offen – bitte dort anmelden …': 'Sign-in window is open – please sign in there …',
    'Anmeldung fehlgeschlagen – bitte erneut versuchen.': 'Sign-in failed – please try again.',

    // Zeit
    'gerade eben': 'just now',
    'vor {n} Min.': '{n} min ago',
    'vor {n} Std.': '{n} h ago',
    'vor {n} Tagen': '{n} days ago',

    // Zustaende
    'Wartet': 'Queued',
    'Läuft': 'Running',
    'Pausiert': 'Paused',
    'Fertig': 'Done',
    'Fehler': 'Error',
    'Abgebrochen': 'Cancelled',
    'Update': 'Update',
    'Nicht installiert': 'Not installed',

    // Knoepfe
    'Installieren': 'Install',
    'Ordner': 'Folder',
    'Prüfen': 'Verify',
    'Dateien prüfen und defekte neu laden': 'Check files and re-download broken ones',
    'Entfernen': 'Remove',
    'Starten': 'Launch',
    'Pause': 'Pause',
    'Fortsetzen': 'Resume',
    'Erneut versuchen': 'Retry',
    'Abbrechen': 'Cancel',
    'Ändern': 'Change',
    'Erledigte ausblenden': 'Hide finished',
    'Auf Fab': 'On Fab',
    'Zum Projekt': 'To project',
    'In Engine': 'To engine',
    'Als Projekt': 'As project',
    'Nur im Editor': 'Editor only',
    'Update starten': 'Start update',

    // Listen & Meldungen
    'Plugins': 'Plugins',
    '{n} von {total} Spielen · {inst} installiert · Stand {ago}': '{n} of {total} games · {inst} installed · updated {ago}',
    '{n} von {total} Assets · Stand {ago}': '{n} of {total} assets · updated {ago}',
    '{e} Engines und {t} Tools installiert · Stand {ago}': '{e} engines and {t} tools installed · updated {ago}',
    'Engine-Versionen': 'Engine versions',
    'DevKits & Tools': 'DevKits & tools',
    'Nichts gefunden.': 'Nothing found.',
    'Keine Downloads.': 'No downloads.',
    '{n} aktiv': '{n} active',
    'Neue Installationen landen in': 'New installations go to',
    'noch nicht festgelegt': 'not set yet',
    '{a} von {b}': '{a} of {b}',
    'noch {eta}': '{eta} left',
    '{title}: fertig': '{title}: done',
    '{title}: Fehler': '{title}: error',
    'Lade von Epic … das kann beim ersten Mal eine Minute dauern.': 'Loading from Epic … the first time this can take a minute.',
    'Lade Bibliothek …': 'Loading library …',
    'Fehler beim Laden: {msg}': 'Loading failed: {msg}',
    'Lade …': 'Loading …',
    'Prüfe …': 'Checking …',

    // Store
    'Zurück': 'Back',
    'Vor': 'Forward',
    'Neu laden': 'Reload',
    'Im eigenen Fenster': 'In own window',
    'Der Store öffnet sich in einem eigenen Fenster.': 'The store opens in its own window.',
    'Assets, Plugins und Megascans für Unreal Engine.': 'Assets, plugins and Megascans for Unreal Engine.',
    'Fab öffnen': 'Open Fab',
    'Spiele und Angebote.': 'Games and deals.',
    'Store öffnen': 'Open store',

    // Update-Vorschau
    'Update-Vorschau': 'Update preview',
    'Vergleiche installierte Version mit der neuen … bei großen DevKits bis zu 2 Minuten.':
      'Comparing the installed version with the new one … up to 2 minutes for large DevKits.',
    'keine optionalen': 'no optional ones',
    'Was': 'What',
    'Neu': 'New',
    'Komponenten': 'Components',
    '{c} – bleiben erhalten': '{c} – will be kept',
    'Download': 'Download',
    'Dateien': 'Files',
    '{c} geändert · {a} neu · {r} entfällt': '{c} changed · {a} new · {r} removed',
    'Platz frei': 'Free space',
    ' – zu wenig!': ' – not enough!',
    '{n} Dateien': '{n} files',
    'gibt es in der neuen Version nicht mehr und werden entfernt.': 'no longer exist in the new version and will be removed.',
    'Deine eigenen Dateien (z. B. Mod-Projekte) sind nicht betroffen – entfernt wird nur, was Epic selbst installiert hat.':
      'Your own files (e.g. mod projects) are not affected – only what Epic itself installed is removed.',
    'Bereits aktuell – nichts zu tun.': 'Already up to date – nothing to do.',
    'Wurde mit dem Epic Launcher installiert. Er bekommt den neuen Stand danach automatisch mitgeteilt.':
      'Installed with the Epic Launcher. It will be told about the new version automatically.',
    'Update in der Warteschlange.': 'Update queued.',

    // Fab-Dialog
    'Fab-Asset': 'Fab asset',
    'Projekt': 'Project',
    'noch keins gewählt': 'none chosen yet',
    'noch keiner gewählt': 'none chosen yet',
    'Projekt wählen …': 'Choose project …',
    'Ordner wählen …': 'Choose folder …',
    'Das Projekt nutzt eine eigene Engine (z. B. ein DevKit). Wähle unten die Version, die am besten passt – ob das Asset dort funktioniert, hängt von der Engine-Version ab.':
      'This project uses its own engine (e.g. a DevKit). Pick the best matching version below – whether the asset works there depends on the engine version.',
    'Engine': 'Engine',
    '– wählen –': '– choose –',
    'Keine installierte Engine passt zu diesem Plugin.': 'No installed engine matches this plugin.',
    'Zielordner (dort entsteht ein neuer Projektordner)': 'Target folder (a new project folder is created there)',
    'Version für': 'Version for',
    'Ziel': 'Target',
    '{n} Dateien gibt es dort schon.': '{n} files already exist there.',
    'Standardmäßig bleiben sie unverändert.': 'By default they stay unchanged.',
    'Vorhandene Dateien überschreiben': 'Overwrite existing files',
    '{n} Dateien gehören nicht in dieses Ziel und werden ausgelassen.': '{n} files do not belong in this target and are skipped.',
    'Zur Warteschlange hinzugefügt – Fortschritt unter „Downloads“.': 'Added to the queue – progress under “Downloads”.',
    'Zur Warteschlange hinzugefügt.': 'Added to the queue.',
    'Wähle zuerst den Ordner, in den installiert werden soll.': 'First choose the folder to install into.',

    // Aktionen & Rueckfragen
    'Unreal Editor wird gestartet …': 'Starting Unreal Editor …',
    'Prüfung in der Warteschlange.': 'Verification queued.',
    '„{title}“ wirklich entfernen?\n\nAlle Dateien im Installationsordner werden gelöscht.':
      'Really remove “{title}”?\n\nAll files in the installation folder will be deleted.',
    'Die halb fertige Installation wird gelöscht.': 'The partial installation will be deleted.',
    'Die Zwischendateien werden gelöscht.': 'The temporary files will be deleted.',
    'Die Installation ist danach evtl. unvollständig – später „Update“ oder „Prüfen“ ausführen.':
      'The installation may be incomplete afterwards – run “Update” or “Verify” later.',
    'Die Installation ist danach evtl. unvollständig – später erneut „Prüfen“.':
      'The installation may be incomplete afterwards – run “Verify” again later.',
    'Wirklich abbrechen?\n\n{what}\n\nZum späteren Weitermachen stattdessen „Pause“ nutzen.':
      'Really cancel?\n\n{what}\n\nTo continue later, use “Pause” instead.',
    'Update verfügbar: {list}': 'Update available: {list}',

    // Einstellungen
    'Einstellungen': 'Settings',
    'Änderungen werden sofort gespeichert.': 'Changes are saved immediately.',
    'Allgemein': 'General',
    'Sprache der Oberfläche. Beim ersten Start wird die Windows-Sprache übernommen.':
      'Interface language. On first start the Windows language is used.',
    'Bereich „Spiele“ anzeigen': 'Show “Games” section',
    'Der Launcher ist aufs Arbeiten mit Unreal ausgerichtet. Ausgeblendet verschwindet „Spiele“ aus dem Menü.':
      'The launcher is built for working with Unreal. When hidden, “Games” disappears from the menu.',
    'Installationsordner': 'Installation folder',
    'Hier landen neu installierte Spiele, Engines und DevKits. Updates bleiben immer im vorhandenen Ordner.':
      'Newly installed games, engines and DevKits go here. Updates always stay in their existing folder.',
    'Zwischenordner für Fab-Assets': 'Temporary folder for Fab assets',
    'Fab-Assets werden hier zwischengespeichert und danach ins Projekt kopiert. Der Ordner wird danach wieder geleert.':
      'Fab assets are stored here temporarily and then copied into the project. The folder is emptied afterwards.',
    'Parallele Verbindungen': 'Parallel connections',
    'Epic begrenzt das Tempo je Verbindung – mehr Verbindungen laden schneller, brauchen aber mehr Arbeitsspeicher (ca. 40 MB je Verbindung). Gilt ab dem nächsten Start oder Fortsetzen eines Downloads. Bei einem Tempolimit nutzt der Launcher nur so viele, wie dafür nötig sind.':
      'Epic limits the speed per connection – more connections download faster but need more memory (about 40 MB each). Applies from the next start or resume of a download. With a speed limit the launcher only uses as many as needed.',
    'Standard': 'Default',
    'Gespeichert.': 'Saved.',
    'Assets behalten': 'Keep assets',
    'Geladene Fab-Assets bleiben im Zwischenordner liegen – für weitere Projekte ist dann kein neuer Download nötig. Braucht entsprechend Speicherplatz.':
      'Downloaded Fab assets stay in the temporary folder – no new download is needed for further projects. Uses disk space accordingly.',
    'Epics Vault-Cache mitnutzen': 'Use Epic’s vault cache',
    'Liegt ein Asset schon vollständig und aktuell in Epics Vault-Cache, wird es von dort kopiert statt neu geladen. Gelöscht wird dort nur, was du selbst unter „Lokal gespeichert“ entfernst.':
      'If an asset is already complete and current in Epic’s vault cache, it is copied from there instead of downloaded. Only what you remove yourself under “Stored locally” is deleted there.',
    'Gefundene Vault-Ordner des Epic Launchers:': 'Vault folders found from the Epic Launcher:',
    'keine': 'none',

    // Optionen (Komponenten)
    'Optionen': 'Options',
    'Übernehmen': 'Apply',
    '{title} – Optionen': '{title} – Options',
    'Prüfe installierte Dateien … bei DevKits bis zu 2 Minuten.': 'Checking installed files … up to 2 minutes for DevKits.',
    'Keine optionalen Komponenten.': 'No optional components.',
    'Hochauflösende Texturen': 'High Resolution Textures',
    'The Center': 'The Center',
    'Lost Colony': 'Lost Colony',
    'Scorched Earth': 'Scorched Earth',
    'Engine-Quellcode': 'Engine source code',
    'Templates & Feature Packs': 'Templates & Feature Packs',
    'Starter Content': 'Starter Content',
    'Editor-Symbole zum Debuggen': 'Editor symbols for debugging',
    'MetaHuman-Inhalte': 'MetaHuman content',
    'Zielplattform {p}': 'Target platform {p}',
    'Download (unkomprimiert, höchstens)': 'Download (uncompressed, at most)',
    'Wird frei': 'Freed',
    'Benötigter Speicher': 'Required storage',
    'Frei auf dem Laufwerk': 'Free on drive',
    '{n} Dateien ({size}) bleiben stehen, weil weiterhin gewählte Komponenten sie mitbenutzen – der Ordner der abgewählten Komponente verschwindet deshalb evtl. nicht ganz.':
      '{n} files ({size}) stay because components that remain selected also use them – so the folder of the deselected component may not disappear completely.',
    'Stand: {ago}': 'Checked {ago}',
    'Neu prüfen': 'Re-check',
    'Für dieses Element steht ein Update aus – es wird beim Hinzufügen mit installiert.':
      'An update is pending for this item – it will be installed along with the new components.',
    'Wirklich entfernen?\n\n{n} Dateien ({size}) der Komponenten {list} werden gelöscht.\nDeine eigenen Dateien und alle übrigen Komponenten sind nicht betroffen.':
      'Really remove?\n\n{n} files ({size}) of the components {list} will be deleted.\nYour own files and all other components are not affected.',

    // UE-Projekte
    'UE-Projekte': 'UE projects',
    'Suche Projekte …': 'Searching projects …',
    '{n} von {total} Projekten': '{n} of {total} projects',
    'Zuletzt geöffnet {ago}': 'Last opened {ago}',
    'Geändert {ago}': 'Modified {ago}',
    'Engine unbekannt ({a})': 'Unknown engine ({a})',
    'Öffnen': 'Open',
    'Öffnen …': 'Open …',
    'Passende Engine nicht gefunden – Windows fragt nach der Engine.': 'Matching engine not found – Windows will ask which engine to use.',
    'Assets': 'Assets',
    'Fab-Assets zu diesem Projekt hinzufügen': 'Add Fab assets to this project',
    'Aus der Liste entfernen': 'Remove from list',
    '„{name}“ aus der Liste ausblenden?\n\nDas Projekt selbst bleibt unverändert auf der Festplatte. Über „Projekt hinzufügen …“ holst du es zurück.':
      'Hide “{name}” from the list?\n\nThe project itself stays unchanged on disk. Use “Add project …” to bring it back.',
    'Projekt hinzufügen …': 'Add project …',
    'Projektordner hinzufügen …': 'Add project folder …',
    'Gefunden werden zuletzt geöffnete Projekte, Projekte in den Projektordnern von Unreal und dem Epic Launcher sowie in installierten DevKits.':
      'Shows recently opened projects, projects in the project folders of Unreal and the Epic Games Launcher, and projects of installed DevKits.',
    'Ziel für „Zum Projekt“:': 'Target for “Add to project”:',
    'Ziel aufheben': 'Clear target',
    'Anderes …': 'Other …',

    // Projekt loeschen
    'Löschen': 'Delete',
    'Projekt löschen': 'Delete project',
    'Projektordner in den Papierkorb verschieben': 'Move the project folder to the Recycle Bin',
    'In den Papierkorb': 'Move to Recycle Bin',
    'Prüfe Projektordner …': 'Checking project folder …',
    'Inhalt': 'Contents',
    '{n} Dateien · {size}': '{n} files · {size}',
    'und {n} weitere': 'and {n} more',
    'Der komplette Projektordner wird in den Papierkorb verschoben – mit allem, was darin liegt, auch eigenen Dateien. Passt er nicht in den Papierkorb, fragt Windows, ob endgültig gelöscht werden soll.':
      'The entire project folder is moved to the Recycle Bin – with everything in it, including your own files. If it does not fit into the Recycle Bin, Windows asks whether to delete it permanently.',
    'Zur Bestätigung den Projektnamen eintippen:': 'Type the project name to confirm:',
    'Wird gelöscht …': 'Deleting …',
    '„{name}“ wurde in den Papierkorb verschoben ({size} frei).': '“{name}” was moved to the Recycle Bin ({size} freed).',

    // Aktivitaet
    'Aktivität': 'Activity',
    'Was der Launcher gerade tut': 'What the launcher is doing right now',
    'Noch keine Ausgabe.': 'No output yet.',
    'Geprüft: {num} von {total} Dateien · Lesen {read} MB/s · Probleme: {bad}':
      'Checked: {num} of {total} files · reading {read} MB/s · problems: {bad}',
    'Geladen {a}': 'Downloaded {a}',
    'Geschrieben {a}': 'Written {a}',
    'Schreiben {w} MB/s · Lesen {r} MB/s': 'writing {w} MB/s · reading {r} MB/s',
    '{n} aktive Aufgaben': '{n} active tasks',
    '{n} Dateien werden repariert': '{n} files being repaired',
    'Arbeitet … (Details unter „Aktivität“)': 'Working … (details under “Activity”)',

    // Fab-Filter
    'Alle Typen': 'All types',
    'Alle Kategorien': 'All categories',
    'Sortierung: Standard': 'Sort: default',
    'Name A–Z': 'Name A–Z',
    'Kategorie': 'Category',
    'Verkäufer': 'Seller',
    'Neueste UE-Version': 'Newest UE version',

    // Uebersicht
    'Übersicht': 'Home',
    '{title} wird gestartet …': 'Launching {title} …',
    '{e} Engines · {t} DevKits & Tools · {p} Projekte · {f} Fab-Assets': '{e} engines · {t} DevKits & tools · {p} projects · {f} Fab assets',
    'DevKit / Tool': 'DevKit / tool',
    'Spiel': 'Game',
    'zuletzt {ago}': 'last used {ago}',
    'angelegt {ago}': 'created {ago}',
    '{local} → {current}': '{local} → {current}',
    'in Epics Vault-Cache': 'in Epic’s vault cache',
    'behaltenes Asset': 'kept asset',
    'Zuletzt gestartet': 'Recently launched',
    'Noch nichts gestartet.': 'Nothing launched yet.',
    'Neueste Projekte': 'Newest projects',
    'Keine Projekte gefunden.': 'No projects found.',
    'Verfügbare Updates': 'Available updates',
    'Fab-Assets': 'Fab assets',
    'Alles aktuell – Engines, DevKits und lokal gespeicherte Assets.': 'Everything up to date – engines, DevKits and locally stored assets.',
    'Jetzt prüfen': 'Check now',
    'Updates werden beim Start und dann stündlich geprüft (Stand {ago}). Fab-Assets: verglichen werden die lokal gespeicherten Kopien (Epics Vault-Cache, behaltene Assets) mit der aktuellen Version bei Epic – Assets, die schon in Projekten liegen, kennt der Launcher nicht.':
      'Updates are checked at start and then hourly (as of {ago}). Fab assets: the locally stored copies (Epic’s vault cache, kept assets) are compared with the current version at Epic – assets already inside projects are not known to the launcher.',

    // Unreal-Bereich
    'Neue Engine installieren': 'Install New Engine',
    '{title} entfernen': 'Remove {title}',
    'Sonstige Software': 'Other software',
    'Neues DevKit installieren': 'Install New Devkit',
    'Unreal-Engine-Version': 'Unreal Engine version',
    'DevKit oder Tool': 'DevKit or tool',
    'Noch keine Engine installiert.': 'No engine installed yet.',
    'Noch kein DevKit installiert.': 'No DevKit installed yet.',
    'Alle verfügbaren Engines sind installiert.': 'All available engines are installed.',
    'Alle verfügbaren DevKits sind installiert.': 'All available DevKits are installed.',
    'Wird installiert …': 'Installing …',

    // Versionspruefung Fab
    'Ziel-Engine': 'Target engine',
    'Keine Engine installiert.': 'No engine installed.',
    'passt zum Ziel': 'matches target',
    'Engine-Version des Assets': 'Asset engine version',
    'Version passt: Asset und Ziel nutzen UE {t}.': 'Version matches: asset and target use UE {t}.',
    'Version passt nicht zum Ziel': 'Version does not match the target.',
    'Trotzdem installieren (Override)': 'Install anyway (override)',
    'Dieses Asset ist für eine neuere Engine (UE {a}) gebaut als das Ziel (UE {t}). Unreal kann Inhalte neuerer Versionen in der Regel gar nicht öffnen.':
      'This asset was built for a newer engine (UE {a}) than the target (UE {t}). Unreal usually cannot open content from newer versions at all.',
    'Dieses Asset ist für eine ältere Engine (UE {a}) gebaut, das Ziel nutzt UE {t}. Das klappt oft, kann aber zu Fehlern oder fehlenden Inhalten führen.':
      'This asset was built for an older engine (UE {a}), the target uses UE {t}. This often works, but can cause errors or missing content.',
    'Die Engine-Version des Ziels ist nicht bekannt, die Kompatibilität lässt sich nicht prüfen (Asset: UE {a}).':
      'The engine version of the target is unknown, compatibility cannot be checked (asset: UE {a}).',
    'Code-Plugins laden in einer anderen Engine-Version meist gar nicht.': 'Code plugins usually do not load in a different engine version.',
    'Asset trotzdem installieren?\n\n{warn}\n\nDas Asset funktioniert dann eventuell nicht ordnungsgemäß.':
      'Install the asset anyway?\n\n{warn}\n\nThe asset may not work properly.',

    // Rueckfragen
    'Trotzdem installieren': 'Install anyway',
    'Ja, abbrechen': 'Yes, cancel',
    'Weitermachen': 'Keep going',
    'Trotzdem schließen': 'Close anyway',
    'Downloads laufen noch': 'Downloads still running',
    'Beim Schließen wird der Download pausiert. Nach dem nächsten Start kannst du ihn unter „Downloads“ an derselben Stelle fortsetzen.':
      'Closing pauses the download. After the next start you can resume it under “Downloads” from the same point.',

    // Anzeigename
    'Anzeigename ändern': 'Change display name',
    'Speichern': 'Save',
    'Anzeigename für „{name}“\n\nDer Name gilt nur im Launcher. Projektordner und Projektdatei bleiben unverändert. Leer lassen für den Originalnamen.':
      'Display name for “{name}”\n\nThis name applies only in the launcher. The project folder and project file stay unchanged. Leave empty for the original name.',

    // Lokal gespeicherte Assets
    'Bibliothek': 'Library',
    'Lokal gespeichert': 'Stored locally',
    'Unvollständig': 'Incomplete',
    'Nicht neu ladbar': 'Cannot re-download',
    'Epics Vault-Cache': 'Epic’s vault cache',
    'Behaltenes Asset': 'Kept asset',
    'Lese lokale Assets …': 'Reading local assets …',
    '{n} Assets · {size} belegt': '{n} assets · {size} used',
    'Keine lokal gespeicherten Assets.': 'No locally stored assets.',
    'Downloads im Zwischenspeicher, aus denen Assets in Projekte kopiert werden. Löschen betrifft nur diesen Speicher – nie Engines, DevKits oder Projekte.':
      'Downloads in the cache that assets are copied into projects from. Deleting only affects this storage – never engines, DevKits or projects.',
    '{title} löschen': 'Delete {title}',
    '„{title}“ löschen?': 'Delete “{title}”?',
    'Das ist ein abgebrochener Download, er ist nicht nutzbar.': 'This is an interrupted download and cannot be used.',
    'Das Asset lässt sich jederzeit neu laden.': 'The asset can be downloaded again at any time.',
    'Achtung: Der Launcher kann dieses Asset nicht selbst neu laden. Das geht danach nur noch über das Fab-Plugin im Editor.':
      'Warning: the launcher cannot download this asset again itself. Afterwards this is only possible through the Fab plugin in the editor.',
    'Achtung: Dieses Asset steht nicht in deiner Fab-Bibliothek und lässt sich danach evtl. nicht mehr laden.':
      'Warning: this asset is not in your Fab library and may not be downloadable afterwards.',
    '{size} werden endgültig gelöscht, nicht in den Papierkorb. Projekte, in die das Asset schon kopiert wurde, sind nicht betroffen.':
      '{size} will be permanently deleted, not moved to the Recycle Bin. Projects the asset was already copied into are not affected.',
    '„{title}“ gelöscht – {size} frei.': '“{title}” deleted – {size} freed.',

    // Projektkarte
    'Ausblenden': 'Hide from list',
    'Nur aus dieser Liste nehmen. Das Projekt bleibt auf der Festplatte.': 'Only removes it from this list. The project stays on disk.',
    'Projektordner von der Festplatte in den Papierkorb verschieben': 'Moves the project folder from disk to the Recycle Bin',

    // Spiele
    'Installierte Spiele': 'Installed games',

    // Status-Spalte
    'Updates': 'Updates',
    'Zum Asset': 'Go to asset',
    'Speicherplatz': 'Disk space',
    'Fab-Downloads': 'Fab downloads',
    '{free} GB von {total} GB frei': '{free} GB of {total} GB free',

    // Konto und Tempo
    'Konto verwalten': 'Manage account',
    'Download-Tempo': 'Download speed',
    'Maximal': 'Maximum',
    'Begrenzt das Tempo aller Downloads, damit genug Leitung für anderes bleibt. Gilt sofort, auch für laufende Downloads.':
      'Limits the speed of all downloads so enough bandwidth stays free for other things. Applies immediately, including running downloads.',

    // Startseite
    'gestern': 'yesterday',
    'Gratis auf Fab': 'Free on Fab',
    'Alle auf Fab ansehen': 'View all on Fab',
    'Letzte Projekte': 'Recent projects',
    'Alle Projekte': 'All projects',
    'Stand {ago}': 'Checked {ago}',
    'Suche nach Updates …': 'Checking for updates …',
    'Alles aktuell': 'Everything is up to date',
    '1 Update verfügbar': '1 update available',
    '{n} Updates verfügbar': '{n} updates available',
    'In deiner Bibliothek': 'In your library',
    'Gratis': 'Free',
    'bis {date}': 'until {date}',
    'Fab ist gerade nicht erreichbar.': 'Fab cannot be reached right now.',
    'Gerade keine Gratis-Assets.': 'No free assets right now.',

    // Quellen
    'Im Epic-Cache': 'In Epic cache',
    'Quelle': 'Source',
    'Epics Vault-Cache – kein Download nötig': 'Epic’s vault cache – no download needed',
    'Behaltenes Asset – kein Download nötig': 'Kept asset – no download needed',
    'Download ({size})': 'Download ({size})',
    'Epic liefert diese Version nicht direkt aus – verwendet wird die vollständige Kopie aus Epics Vault-Cache (Version {v}). Ob sie die neueste ist, lässt sich nicht prüfen.':
      'Epic does not deliver this version directly – the complete copy from Epic’s vault cache is used (version {v}). Whether it is the newest cannot be checked.',
    'Mit Windows starten': 'Start with Windows',
    'Startet den Launcher bei der Windows-Anmeldung – normal im Fenster oder still im Infobereich neben der Uhr.': 'Starts the launcher when you sign in to Windows – normally in its window or quietly in the notification area next to the clock.',
    'Aus': 'Off',
    'Normal': 'Normal',
    'Im Infobereich': 'In the notification area',
    'Beim Schließen im Infobereich weiterlaufen': 'Keep running in the notification area when closed',
    'Das X schließt nur das Fenster, der Launcher läuft neben der Uhr weiter – z. B. für Downloads. Ganz beenden über das Symbol dort.': 'The X only closes the window; the launcher keeps running next to the clock – e.g. for downloads. To quit completely, use the icon there.',
    'Auf GitHub': 'On GitHub',
    'Update auf {v} verfügbar': 'Update to {v} available',
    'Siccora Launcher ist aktuell': 'Siccora Launcher is up to date',
    'Siccora Launcher {v} installieren?\n\nDas Update wird geladen und geprüft. Danach schließt sich der Launcher kurz und startet von selbst neu.': 'Install Siccora Launcher {v}?\n\nThe update is downloaded and verified. The launcher then closes briefly and restarts on its own.',
    'Laufende Downloads werden pausiert und lassen sich danach fortsetzen.': 'Running downloads are paused and can be resumed afterwards.',
    'Jetzt aktualisieren': 'Update now',
    'Lade Update …': 'Downloading update …',
  },
};

let LANG = 'de';

function t(key, vars) {
  // Deutsch ist der Schluessel; fehlt eine Uebersetzung, gilt Englisch
  let s = LANG === 'de' ? key : (I18N[LANG] && I18N[LANG][key]) || I18N.en[key] || key;
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  return s;
}

function detectLanguage(saved) {
  if (saved && LANGUAGES[saved]) return saved;
  const nav = (navigator.language || 'de').slice(0, 2).toLowerCase();
  return LANGUAGES[nav] ? nav : 'en';
}

// Feste Texte im HTML: data-i18n (Text), data-i18n-html (mit Markup, nur eigene Texte),
// data-i18n-ph (Platzhalter), data-i18n-title (Tooltip)
function applyStatic(root = document) {
  document.documentElement.lang = LANG;
  root.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-html]').forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
  root.querySelectorAll('[data-i18n-ph]').forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
  root.querySelectorAll('[data-i18n-title]').forEach((el) => { el.title = t(el.dataset.i18nTitle); });
}

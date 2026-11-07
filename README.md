# Siccora Launcher

A lightweight replacement for the Epic Games Launcher, built for working with
Unreal Engine, DevKits and Fab. Windows only.

## Features

- **Home:** slim update bar with direct links (engines, DevKits, locally stored
  Fab assets; checked at every start), the current free Fab assets, the 3 most
  recently launched editors/DevKits (also counts projects opened outside the
  launcher) and the 3 most recent projects
- **Launch** engines and DevKits with the same parameters as the Epic Games
  Launcher (e.g. a DevKit's project and flags)
- **Library:** games, Unreal Engine versions, DevKits and tools (every DevKit
  available through Epic). Install, update (with preview), verify, remove;
  pause, resume and cancel downloads
- **Options:** add and remove optional components (e.g. DLC maps, high-res
  textures, templates), just like in the Epic Games Launcher
- **UE projects:** all your Unreal projects in one place (recently opened,
  Unreal/Epic project folders, projects of installed DevKits, added manually),
  open them with the matching engine or DevKit, add Fab assets directly,
  delete plain UE projects (to the Recycle Bin, after typing the project name;
  never DevKit/ModKit projects, engines, games, drives or folders that contain
  other projects; refused while the project is open)
- **Stored locally:** see what Fab downloads occupy in Epic's vault cache and
  delete them to free disk space (only there, never in engines or projects)
- **Activity view:** live progress while verifying (files checked, read
  speed, problems found) and downloading (written, write/read speed),
  plus the raw log per job
- **Fab library:** filter by type and category, sort by name, category,
  seller or newest UE version; pick the exact engine version when installing,
  with a version check against the target (DevKits included) and an override
  that warns first; add assets to projects, plugins to engines, or create
  complete projects; reuses Epic's vault cache if an asset is already there
- **Store:** Fab and the Epic Games Store on the right side of the window;
  you stay signed in
- **Sign-in** through Epic's own login window
- **Behaves like Windows software:** start with Windows (normally or quietly
  in the notification area), keep running next to the clock when closed,
  only one instance at a time
- English, German, French, Spanish, Italian, Polish, Portuguese, Dutch; settings, automatic update check,
  download speed limit
- ~200 MB RAM, 0 % CPU when idle

An installed Epic Games Launcher is **not** required.

## Install

Download `SiccoraLauncher-<version>-Setup.exe` and run it. It installs for the
current user to `%LOCALAPPDATA%\Programs\Siccora Launcher`, without admin
rights. Alternatively unpack `SiccoraLauncher-<version>-portable.zip` and start
`SiccoraLauncher.exe`.

Requirements: Windows 10 (version 1809 or newer) or Windows 11. The installer
checks everything else: if Microsoft Edge WebView2 is missing, it installs it
with Microsoft's official installer.

The program is not code-signed yet, so Windows SmartScreen may show a warning
on first start ("More info" → "Run anyway").

## Development

Siccora Launcher is designed, directed and tested by me. Much of the code was
written with AI assistance. Every feature was tested on real installations,
including fresh Windows VMs, engine and DevKit installs, updates and Fab
downloads.

## Running from source

`Start.bat` runs the launcher from source using the Python environment in
`spike/.venv` (Python 3.12 with `legendary-gl`, `pywebview`, `requests`).

```
app/
  main.py              window + interface to the UI (Api)
  entry.py             entry point of the packaged exe
  backend/
    epic.py            sign-in, library, Fab library, cache
    downloads.py       queue (two lanes), pause/resume/cancel
    lgd_run.py         Legendary wrapper with safety guards (see below)
    egl_bridge.py      sync with the Epic Games Launcher, set/remove components
    preview.py         update preview (read-only)
    components.py      component analysis + saved state
    fab_install.py     Fab assets into projects/engines
    vault.py           Epic's vault cache / kept assets
    storepanel.py      store as a second WebView2 in the main window
    tray.py            icon in the notification area
    autostart.py       start with Windows
    settings.py        settings
    i18n.py            translations (backend)
  ui/                  user interface (HTML/CSS/JS, i18n.js)
  dev_server.py        browser preview (development only, localhost only)
packaging/             PyInstaller spec, Inno Setup script, build script
spike/                 feasibility test + Python environment
```

Data is stored in `%LOCALAPPDATA%\SiccoraLauncher` (cache, settings, browser
profile); Legendary's data in `%USERPROFILE%\.config\legendary`.

## Safety guards (do not remove)

Legendary on its own deletes files of "deselected" components. For
installations taken over from the Epic Games Launcher it does not know the
selection, which once deleted the templates/source code of an engine during
testing. Therefore:

- `lgd_run.py` disables `uninstall_tag` and drops silent delete tasks
  (`DELETE_FILE|SILENT`), unless `SICCORA_ALLOW_TAG_DELETE=1`
- `egl_bridge.py` detects installed components from the files on disk
- Removing components is done by the launcher itself, and only for files of
  just-deselected components that no selected component also uses
- Cancelling only deletes unfinished new installations below the install
  folder, never anything installed; Epic's vault cache only changes when you
  delete a download there yourself under "Stored locally"

## Building the package and installer

```
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Creates in `dist\`:

- `SiccoraLauncher\SiccoraLauncher.exe`: standalone package (no Python needed)
- `SiccoraLauncher-<version>-portable.zip`: unpack and run
- `SiccoraLauncher-<version>-Setup.exe`: installer (requires Inno Setup 6)

New version: raise `APP_VERSION` in `app/main.py` and run `build.ps1`. The new
setup installs over the old one (fixed `AppId` in `packaging/installer.iss`,
never change it). Sign-in, settings and library are kept; uninstalling removes
only the program, never installed games, engines or DevKits.

## License

Siccora Launcher is licensed under the [GNU General Public License v3.0](LICENSE).

It uses Epic's unofficial interfaces through
[Legendary](https://github.com/derrod/legendary) (GPL-3.0). Not affiliated with
or endorsed by Epic Games. Unreal Engine, Fab and Epic Games Store are
trademarks of Epic Games, Inc.

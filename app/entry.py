"""Startpunkt des fertigen Pakets (SiccoraLauncher.exe).

Im Paket gibt es kein python.exe. Die Hintergrundarbeit, die in der Entwicklung
eigene Python-Prozesse erledigen, uebernimmt deshalb dieselbe exe:
  SiccoraLauncher.exe                 -> Oberflaeche
  SiccoraLauncher.exe --lgd ...       -> Legendary (Downloads, Updates, Entfernen)
  SiccoraLauncher.exe --bridge ...    -> Abgleich Epic Launcher / Komponenten
  SiccoraLauncher.exe --selftest DATEI -> Oberflaeche oeffnen, Zustand in DATEI schreiben, beenden
"""
import multiprocessing
import os
import sys


def _console_streams():
    # Das Paket ist eine Fenster-Anwendung: ohne Konsole ist sys.stdout None.
    # Die Hintergrund-Modi schreiben ihren Fortschritt in die vom Launcher
    # bereitgestellte Pipe - die Standard-Handles darauf wieder oeffnen.
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(fd, "w", encoding="utf-8", errors="replace", buffering=1, closefd=False))
            except OSError:
                setattr(sys, name, open(os.devnull, "w"))


def _background(task):
    """Hintergrundaufgabe ausfuehren. Fehler gehen als Text an den Launcher (Pipe) -
    NIE als Fehlerfenster: das Paket wuerde sonst auf einen Klick warten und der
    Download haengen bleiben."""
    import traceback
    _console_streams()
    try:
        code = task()
    except SystemExit as e:
        code = e.code
    except BaseException:  # noqa: BLE001 - alles abfangen, sonst zeigt PyInstaller ein Fenster
        print("CRITICAL: " + traceback.format_exc().strip().splitlines()[-1], file=sys.stdout, flush=True)
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code if isinstance(code, int) else (0 if code is None else 1))


def _lgd():
    args = sys.argv[2:]
    sys.argv = ["legendary"] + args  # lgd_run liest sys.argv schon beim Import
    from backend import lgd_run
    return lgd_run.run(args)


def _bridge():
    sys.argv = ["egl_bridge"] + sys.argv[2:]
    from backend import egl_bridge
    return egl_bridge.main()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Legendarys Download-Arbeiter starten diese exe erneut
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--lgd":
        _background(_lgd)
    elif mode == "--bridge":
        _background(_bridge)
    else:
        import main
        main.main(selftest=sys.argv[2] if mode == "--selftest" and len(sys.argv) > 2 else None)

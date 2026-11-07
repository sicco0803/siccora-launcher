"""Mit Windows starten: Eintrag unter HKCU\\...\\Run (nur fuer diesen Benutzer, keine Adminrechte).

Der Eintrag in Windows ist die einzige Quelle - schaltet ihn jemand im Task-Manager
ab, zeigt der Launcher das auch so an. Der Installer entfernt ihn beim Deinstallieren.
"""
import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Hier merkt sich der Task-Manager "Autostart deaktiviert" (erstes Byte ungerade = aus)
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
NAME = "SiccoraLauncher"
MODES = ("off", "normal", "tray")
TRAY_ARG = "--tray"


def _command(mode):
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}"'
    else:  # Entwicklung: wie Start.bat, ohne Konsolenfenster
        main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        cmd = f'"{os.path.join(os.path.dirname(sys.executable), "pythonw.exe")}" "{main_py}"'
    return f"{cmd} {TRAY_ARG}" if mode == "tray" else cmd


def _disabled_in_task_manager():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            data, _ = winreg.QueryValueEx(key, NAME)
        return bool(data) and data[0] % 2 == 1
    except OSError:
        return False


def get():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, NAME)
    except OSError:
        return "off"
    if _disabled_in_task_manager():
        return "off"
    return "tray" if TRAY_ARG in str(value) else "normal"


def set_mode(mode):
    if mode not in MODES:
        raise ValueError(mode)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if mode == "off":
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, _command(mode))
    # eine fruehere Abschaltung im Task-Manager aufheben - der Nutzer hat es hier bewusst eingestellt
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, NAME)
    except OSError:
        pass
    return get()

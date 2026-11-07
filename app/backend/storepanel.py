"""Fab / Epic Store rechts im Hauptfenster.

Fab und Epic verbieten das Einbetten per iframe. Stattdessen liegt ein
zweites WebView2-Element im selben Windows-Formular wie die Launcher-
Oberflaeche und deckt genau die Flaeche ab, die die Oberflaeche dafuer
freihaelt (Position kommt aus dem HTML, in CSS-Pixeln * devicePixelRatio).
Es nutzt dieselben Erstellungs-Eigenschaften wie das Hauptelement - also
dasselbe dauerhafte Profil: einmal bei Fab/Epic angemeldet, bleibt man es.

Alle WinForms-Zugriffe muessen im UI-Thread laufen -> _ui().
"""
import threading
import urllib.parse

_lock = threading.Lock()


def guard_main(window):
    """Das Hauptfenster darf nur die eigene Oberflaeche zeigen. pywebview gibt JEDER Seite im
    Fenster Zugriff auf die Launcher-Funktionen - eine fremde Seite (Link, hineingezogene Datei)
    koennte sonst z. B. Programme starten oder Projekte loeschen. Einmal nach dem ersten Laden aufrufen."""
    from System import Action
    from Microsoft.Web.WebView2.WinForms import WebView2

    form = window.native
    parts = urllib.parse.urlsplit(window.get_current_url() or "")
    home = f"{parts.scheme}://{parts.netloc}/"
    if parts.scheme != "http" or parts.hostname != "127.0.0.1":
        return  # unbekannter Start - lieber nichts sperren als die Oberflaeche

    def starting(sender, args):
        if not str(args.Uri).startswith(home):
            args.Cancel = True

    def attach():
        main = next(c for c in form.Controls if isinstance(c, WebView2))
        main.CoreWebView2.NavigationStarting += starting
        main.CoreWebView2.FrameNavigationStarting += starting
    form.Invoke(Action(attach))


class StorePanel:
    def __init__(self, window):
        self._window = window
        self._view = None
        self._ready = threading.Event()

    # --- UI-Thread ---------------------------------------------------------
    def _form(self):
        return self._window.native  # pywebview: das WinForms-Formular des Fensters

    def _ui(self, fn):
        from System import Action
        form = self._form()
        result = {}

        def run():
            result["value"] = fn()
        if form.InvokeRequired:
            form.Invoke(Action(run))
        else:
            run()
        return result.get("value")

    def _later(self, fn):
        """Im Fenster-Thread ausfuehren, ohne darauf zu warten. CoreWebView2 nur dort anfassen:
        aus anderen Threads blockiert der Zugriff und der ganze Launcher friert ein."""
        from System import Action
        self._form().BeginInvoke(Action(fn))

    def _ensure(self):
        if self._view is not None:
            return self._view
        from Microsoft.Web.WebView2.WinForms import WebView2
        from System.Drawing import Color

        form = self._form()
        main = next(c for c in form.Controls if isinstance(c, WebView2))
        view = WebView2()
        view.CreationProperties = main.CreationProperties  # gleiches Profil = gleiche Anmeldung
        view.DefaultBackgroundColor = Color.FromArgb(255, 0x15, 0x11, 0x0E)
        view.Visible = False

        def ready(sender, args):
            if args.IsSuccess:
                view.CoreWebView2.Settings.AreDevToolsEnabled = False
                # Links, die ein neues Fenster wollen, im selben Bereich oeffnen - nur https,
                # keine lokalen Dateien oder Programm-Links (z. B. file:, ms-settings:)
                def new_window(s, e):
                    e.Handled = True
                    if str(e.Uri).startswith("https://"):
                        view.CoreWebView2.Navigate(e.Uri)
                view.CoreWebView2.NewWindowRequested += new_window
            self._ready.set()
        view.CoreWebView2InitializationCompleted += ready
        form.Controls.Add(view)
        view.BringToFront()
        view.EnsureCoreWebView2Async(None)
        self._view = view
        return view

    # --- oeffentlich (aus beliebigen Threads) --------------------------------
    def show(self, url, rect):
        """rect = {x, y, w, h} in Geraetepixeln, relativ zum Fensterinhalt."""
        with _lock:
            def run():
                view = self._ensure()
                self._place(view, rect)
                view.Visible = True
                view.BringToFront()
            self._ui(run)
        self._ready.wait(15)
        if url:
            self.navigate(url)
        return {"ok": True}

    def _place(self, view, rect):
        from System.Drawing import Point, Size
        view.Location = Point(int(rect["x"]), int(rect["y"]))
        view.Size = Size(max(int(rect["w"]), 1), max(int(rect["h"]), 1))

    def resize(self, rect):
        if self._view is not None:
            self._ui(lambda: self._place(self._view, rect))
        return {"ok": True}

    def hide(self):
        if self._view is not None:
            self._ui(lambda: setattr(self._view, "Visible", False))
        return {"ok": True}

    def navigate(self, url):
        if self._view is None or not url.startswith("https://"):
            return {"ok": False}
        self._ui(lambda: self._view.CoreWebView2.Navigate(url))
        return {"ok": True}

    def go(self, action):
        if self._view is None:
            return {"ok": False}
        script = {"back": "history.back()", "forward": "history.forward()", "reload": "location.reload()"}.get(action)
        if script:
            self._later(lambda: self._view.CoreWebView2 and self._view.CoreWebView2.ExecuteScriptAsync(script))
        return {"ok": True}

    def current(self):
        if self._view is None:
            return {"url": None}

        def run():
            v = self._view
            if v.CoreWebView2 is None:
                return {"url": None}
            return {"url": v.CoreWebView2.Source, "title": v.CoreWebView2.DocumentTitle, "visible": bool(v.Visible),
                    "bounds": [v.Left, v.Top, v.Width, v.Height]}
        return self._ui(run)

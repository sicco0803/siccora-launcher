"""Symbol im Infobereich (neben der Uhr).

Laeuft in einem eigenen Windows-Thread mit eigener Nachrichtenschleife - so haengt es
nie vom Launcher-Fenster ab und bleibt auch bei verstecktem Fenster bedienbar.
Linksklick oeffnet den Launcher, Rechtsklick zeigt "Oeffnen" und "Beenden".
"""
import threading

# Farben wie in ui/styles.css
_COLORS = {"bg": "#15110E", "surface": "#1E1A17", "raised": "#2A2420", "line": "#3A322C", "line_soft": "#2C2622",
           "ink": "#F4F0EA", "muted": "#A79C93", "brand": "#E8A030"}
ITEM_W, ITEM_H, HEAD_H = 236, 36, 44


def _color(name):
    from System.Drawing import ColorTranslator
    return ColorTranslator.FromHtml(_COLORS[name])


def _font(size, bold=False):
    """Schmale Schrift wie Oswald im Launcher: Bahnschrift ist ab Windows 10 dabei."""
    from System.Drawing import Font, FontStyle
    font = Font("Bahnschrift SemiBold Condensed" if bold else "Bahnschrift Condensed", size)
    if not font.Name.startswith("Bahnschrift"):  # aeltere Windows-Versionen
        font = Font("Segoe UI Semibold" if bold else "Segoe UI", size - 1, FontStyle.Regular)
    return font


_renderer = {}


def _menu_renderer():
    """Hintergrund und Rahmen des Menues in Launcher-Farben (Windows zeichnet sonst hellgrau)."""
    # Python kann hier nur oeffentliche Eigenschaften ueberschreiben - deshalb eine Farbtabelle
    # fuer Windows' eigenen Menue-Zeichner statt eines eigenen Zeichners
    if "cls" not in _renderer:
        import clr
        from System.Drawing import Color
        from System.Windows.Forms import ProfessionalColorTable

        class SiccoraMenuColors(ProfessionalColorTable):
            __namespace__ = "Siccora.Launcher"

            @clr.clrproperty(Color)
            def MenuBorder(self):
                return _color("line")

            @clr.clrproperty(Color)
            def ToolStripDropDownBackground(self):
                return _color("surface")

            @clr.clrproperty(Color)
            def ImageMarginGradientBegin(self):
                return _color("surface")

            @clr.clrproperty(Color)
            def ImageMarginGradientMiddle(self):
                return _color("surface")

            @clr.clrproperty(Color)
            def ImageMarginGradientEnd(self):
                return _color("surface")
        _renderer["cls"] = SiccoraMenuColors
    from System.Windows.Forms import ToolStripProfessionalRenderer
    renderer = ToolStripProfessionalRenderer(_renderer["cls"]())
    renderer.RoundedEdges = False
    return renderer


def _styled_menu():
    from System.Windows.Forms import ContextMenuStrip, Padding
    menu = ContextMenuStrip()
    menu.Renderer = _menu_renderer()
    menu.ShowImageMargin = False
    menu.ShowCheckMargin = False
    menu.BackColor = _color("surface")
    menu.Padding = Padding(1)
    menu.Opened += lambda s, e: _square_frame(s.Handle.ToInt64())
    return menu


def _square_frame(hwnd):
    """Windows 11 zeichnet Menues mit runden Ecken und hellgrauem Rahmen - hier eckig und in
    Launcher-Farbe. Auf Windows 10 gibt es beides nicht, der Aufruf schadet dort nicht."""
    import ctypes
    try:
        dwm = ctypes.WinDLL("dwmapi")
        hwnd = ctypes.c_void_p(hwnd)
        square = ctypes.c_int(1)  # DWMWCP_DONOTROUND
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(square), 4)
        c = _COLORS["line"].lstrip("#")
        border = ctypes.c_uint(int(c[4:6] + c[2:4] + c[0:2], 16))  # COLORREF = 0x00BBGGRR
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), 4)
    except OSError:
        pass


def _item(menu, text, header=False, divider=False, icon_path=None):
    """Menuepunkt komplett selbst gezeichnet - wie die Menuepunkte links im Launcher:
    gedaempfte Grossschrift, beim Darueberfahren hellere Flaeche mit orangem Balken."""
    from System.Drawing import Icon, Rectangle, Size, SolidBrush
    from System.Windows.Forms import TextFormatFlags, TextRenderer, ToolStripMenuItem
    item = ToolStripMenuItem(text)
    item.AutoSize = False
    item.Size = Size(ITEM_W, HEAD_H if header else ITEM_H)
    item.Enabled = not header
    font = _font(12 if header else 11, bold=header)
    small = Icon(icon_path, 20, 20) if icon_path else None
    flags = TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.EndEllipsis

    def paint(s, e):
        g, w, h = e.Graphics, s.Width, s.Height
        hot = s.Selected and s.Enabled
        g.FillRectangle(SolidBrush(_color("raised" if hot else ("bg" if header else "surface"))), Rectangle(0, 0, w, h))
        if hot:
            g.FillRectangle(SolidBrush(_color("brand")), Rectangle(0, 0, 3, h))
        if divider or header:
            y = 0 if divider else h - 1
            g.FillRectangle(SolidBrush(_color("line_soft")), Rectangle(0, y, w, 1))
        x = 16
        if small is not None:
            g.DrawIcon(small, Rectangle(14, (h - 20) // 2, 20, 20))
            x = 44
        color = _color("ink" if header or hot else "muted")
        TextRenderer.DrawText(g, s.Text.upper(), font, Rectangle(x, 0, w - x - 12, h), color, flags)
    item.Paint += paint
    menu.Items.Add(item)
    return item


class Tray:
    def __init__(self, icon_path, on_open, on_quit, texts):
        self._icon_path = icon_path
        self._on_open, self._on_quit = on_open, on_quit
        self._texts = texts  # {"open": ..., "quit": ...}
        self._ready = threading.Event()
        self._icon = self._menu = self._control = self._context = None

        from System.Threading import ApartmentState, Thread, ThreadStart
        thread = Thread(ThreadStart(self._run))
        thread.SetApartmentState(ApartmentState.STA)  # Windows-Menues brauchen das
        thread.IsBackground = True
        thread.Start()
        self._ready.wait(10)

    # --- im Tray-Thread ------------------------------------------------------
    def _run(self):
        from System.Drawing import Icon
        from System.Windows.Forms import (Application, ApplicationContext, ContextMenuStrip, Control,
                                          MouseButtons, NotifyIcon)
        try:
            self._control = Control()
            self._control.CreateControl()  # Fenster-Handle, damit andere Threads hierher melden koennen
            self._menu = _styled_menu()
            self._header = _item(self._menu, "Siccora Launcher", header=True, icon_path=self._icon_path)
            self._open_item = _item(self._menu, self._texts["open"])
            self._open_item.Click += lambda s, e: self._call(self._on_open)
            self._quit_item = _item(self._menu, self._texts["quit"], divider=True)
            self._quit_item.Click += lambda s, e: self._call(self._on_quit)

            icon = NotifyIcon()
            icon.Icon = Icon(self._icon_path)
            icon.Text = "Siccora Launcher"
            icon.ContextMenuStrip = self._menu
            icon.MouseClick += lambda s, e: self._call(self._on_open) if e.Button == MouseButtons.Left else None
            icon.Visible = True
            self._icon = icon
            self._context = ApplicationContext()
        finally:
            self._ready.set()
        Application.Run(self._context)

    @staticmethod
    def _call(fn):
        # nie im Tray-Thread warten (Fenster oeffnen/schliessen braucht den Fenster-Thread)
        threading.Thread(target=fn, daemon=True).start()

    def _invoke(self, fn):
        if self._control is None:
            return
        from System import Action
        try:
            self._control.Invoke(Action(fn))
        except Exception:  # Thread schon beendet
            pass

    # --- oeffentlich -----------------------------------------------------------
    def set_texts(self, texts):
        self._texts = texts

        def apply():
            self._open_item.Text, self._quit_item.Text = texts["open"], texts["quit"]
        self._invoke(apply)

    def notify(self, text):
        """Kurze Windows-Benachrichtigung am Symbol."""
        from System.Windows.Forms import ToolTipIcon
        self._invoke(lambda: self._icon.ShowBalloonTip(4000, "Siccora Launcher", text, ToolTipIcon.Info))

    def close(self):
        """Symbol sofort entfernen - sonst bleibt bis zum Darueberfahren ein Geist-Symbol stehen."""
        def stop():
            self._icon.Visible = False
            self._icon.Dispose()
            self._context.ExitThread()
        if self._icon is None:
            return
        self._invoke(stop)
        try:
            if self._icon.Visible:  # Nachrichtenschleife schon beendet - direkt entfernen
                self._icon.Visible = False
                self._icon.Dispose()
        except Exception:
            pass

"""Absturzberichte verstaendlich machen. Liest nur, alles lokal, nichts geht ins Internet.

Unreal legt je Absturz einen Ordner unter <Projekt>/Saved/Crashes an, darin die Datei
CrashContext.runtime-xml mit Absturzart und Fehlermeldung. Eine feste Regelliste ordnet sie ein;
die Oberflaeche zeigt dazu Erklaerung und Schritte. Gleiche Fehler werden zusammengefasst.
Fuer den neuesten Bericht jeder Gruppe kommen Details dazu: was im Editor gerade offen war,
welches Plugin oder welcher Engine-Bereich beteiligt war, das genannte Asset, Speicherwerte und
die letzten Warnungen/Fehler aus dem Log vor dem Absturz.
Nicht lesbare Berichte stuerzen nie ab, sondern erscheinen als "unreadable".
"""
import glob
import html
import json
import os
import re

REPORT = "CrashContext.runtime-xml"
MAX_READ = 256 * 1024
MAX_REPORTS = 1500  # je Projekt, die neuesten

# Reihenfolge zaehlt: Besonderes vor Allgemeinem
RULES = [
    ("vram", r"out of video memory|video memory"),
    ("gpu", r"DEVICE_REMOVED|DEVICE_HUNG|DEVICE_RESET|DEVICE_LOST|GPU crash|D3D1[12]\w*.*(?:failed|hung)"),
    ("memory", r"out of (?:video )?memory|Ran out of|Failed to allocate|\bOOM\b|MallocBinned"),
    ("shader", r"shader"),
    ("worldpartition", r"WorldPartition|\bHLOD\b|Landscape"),
    ("save", r"not mapped when saving|SavePackage|Failed to save|Illegal reference"),
    ("asset", r"Serial size mismatch|corrupt|LinkerLoad|Failed to load|Couldn't find file|Package .* (?:missing|not found)"),
    ("blueprint", r"Blueprint|Kismet|\bBP_\w+"),
]
RULES = [(k, re.compile(r, re.I)) for k, r in RULES]


LOG_TAIL = 768 * 1024
LOG_LINES = 10
# Stack-Eintraege ohne Aussagekraft (Windows, Absturzbehandlung)
SKIP_MODULES = re.compile(r"^(KERNELBASE|ntdll|kernel32|ucrtbase|VCRUNTIME\d*|Core|Sentry|TraceLog|ApplicationCore|CrashReport\w*|"
                          r"BuildSettings|TelemetryUtils)$", re.I)
# Engine-Module, die fuer Modder etwas bedeuten (Rest ist zu allgemein, z. B. Engine oder CoreUObject)
ENGINE_AREAS = [
    ("directx", r"^D3D1[12]RHI$|^RHI$|^RHICore$"), ("vulkan", r"^VulkanRHI$"), ("render", r"^Renderer$|^RenderCore$"),
    ("landscape", r"^Landscape"), ("foliage", r"^Foliage"), ("worldpartition", r"WorldPartition"),
    ("ddc", r"^Zen|^DerivedDataCache"), ("audio", r"^Audio"), ("shader", r"^Shader"), ("material", r"^MaterialEditor$"),
    ("niagara", r"^Niagara"), ("browser", r"^libcef$|^WebBrowser"), ("physics", r"^Chaos|^PhysicsCore$"),
]
ENGINE_AREAS = [(k, re.compile(r, re.I)) for k, r in ENGINE_AREAS]
RE_ASSET = re.compile(r"(?<![\w.:/])(/(?!Script/|Temp/|Memory/|Engine/Transient)[A-Za-z_][\w-]*/[\w/.-]*\w)")
RE_LOG_PREFIX = re.compile(r"^\[[^\]]*\]\[\s*\d+\]")
RE_CRASH_LINE = re.compile(r"appError called|=== Critical error|Fatal error!|Assertion failed|Unhandled Exception|"
                           r"=== Handled ensure|Ensure condition failed")
RE_NOISE_CAT = re.compile(r"^Log(Http|StreamlineAPI|Trace|Online\w*|Sentry|Telemetry|EOS\w*|Analytics|CrowdFollowing|"
                          r"Horde|Derived\w*Cache|Zen\w*):")
RE_NOISE = re.compile(r"Memory Stats|Budget:|Used:|Windows GetLastError|=== Critical error|appError called|Fatal error|"
                      r"Assertion failed|Ensure condition failed", re.I)


def _tag(text, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def classify(crash_type, message):
    if crash_type == "GPUCrash":
        return "gpu"
    for key, rule in RULES:
        if rule.search(message):
            return key
    return {"Assert": "assert", "Ensure": "ensure", "Crash": "access", "Hang": "hang"}.get(crash_type) or (
        "access" if re.search(r"ACCESS_VIOLATION|Unhandled Exception", message, re.I) else "unknown")


def _signature(message):
    """Gleiche Fehler erkennen: Pfade, Zahlen und Adressen sind von Absturz zu Absturz anders."""
    text = re.sub(r"\[File:[^\]]*\]|\[Line:[^\]]*\]", " ", message)
    text = re.sub(r"[A-Za-z]:[\\/]\S+|/Game/\S+|0x[0-9a-fA-F]+|\d+", "#", text)
    return re.sub(r"\s+", " ", text).strip()[:140]


def read_report(folder):
    """Ein Bericht oder None, wenn keiner da ist. Kaputte Dateien liefern category "unreadable"."""
    path = os.path.join(folder, REPORT)
    try:
        when = os.path.getmtime(path)
        with open(path, "rb") as f:
            raw = f.read(MAX_READ)
        # je nach Engine-Version UTF-8 oder UTF-16 (erkennbar an den ersten Bytes)
        text = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8", errors="replace")
    except FileNotFoundError:
        return None
    except OSError:
        return {"category": "unreadable", "message": "", "version": "", "time": 0, "ensure": False}
    if "<FGenericCrashContext" not in text and "<RuntimeProperties" not in text:
        return {"category": "unreadable", "message": "", "version": "", "time": when, "ensure": False}
    crash_type, message = _tag(text, "CrashType"), _tag(text, "ErrorMessage")
    if not crash_type and not message:
        return {"category": "unreadable", "message": "", "version": "", "time": when, "ensure": False}
    return {"category": classify(crash_type, message), "message": message, "version": _tag(text, "EngineVersion").split("-")[0],
            "time": when, "ensure": crash_type == "Ensure"}


def activity(hint):
    """Was im Editor gerade offen war, z. B. {"kind": "mode", "name": "Landscape"}."""
    hint = hint.strip()
    if not hint:
        return None
    if hint == "EditorExit":
        return {"kind": "exit", "name": ""}
    layout = re.search(r'Layout="([^"]*)"', hint)
    label = re.search(r'Label="([^"]*)"', hint)
    layout, label = (layout.group(1) if layout else ""), (label.group(1) if label else "")
    if layout.startswith("/"):  # eigenes Editor-Werkzeug (Widget), z. B. Local Cook der ARK-DevKits
        name = layout.rsplit(".", 1)[-1] or layout.rsplit("/", 1)[-1]
        return {"kind": "tool", "name": re.sub(r"^(UEW|EUW|EWBP|WBP)_|_BP$", "", name)}
    if not label:
        return None
    if layout == "TopLeftModeTab":
        return {"kind": "mode", "name": label}
    if layout == "LevelEditorViewport":
        return {"kind": "viewport", "name": label}
    if layout in ("Document", "StandaloneToolkit") or layout.endswith(("Editor_MaterialProperties", "_Grid")):
        return {"kind": "editor", "name": label}
    return {"kind": "window", "name": label}


def _module_names(text):
    m = re.search(r"<PCallStack>(.*?)</PCallStack>", text, re.S)
    if not m:
        return []
    names = []
    for line in m.group(1).splitlines():
        parts = line.split()
        if not parts or ("-" not in parts[0] and parts[0].endswith("Editor")):
            continue  # die exe selbst (z. B. ShooterGameEditor) sagt nichts aus
        names.append(re.sub(r"^[A-Za-z0-9_]*Editor-", "", parts[0]))  # "ShooterGameEditor-D3D12RHI" -> "D3D12RHI"
    return names


def _plugin_modules(project_dir, engine_dir, cache):
    """Modulnamen -> Plugin-Name aus Projekt-Plugins und Marketplace/Fab-Plugins der Engine."""
    key = (project_dir, engine_dir)
    if key in cache:
        return cache[key]
    found = {}
    roots = [os.path.join(project_dir, "Plugins")]
    if engine_dir:
        roots += [os.path.join(engine_dir, "Plugins", "Marketplace"), os.path.join(engine_dir, "Plugins", "Fab")]
    for root in roots:
        for depth in ("*", "*/*", "*/*/*"):
            for path in glob.glob(os.path.join(root, depth, "*.uplugin")):
                try:
                    with open(path, encoding="utf-8-sig") as f:
                        data = json.load(f)
                except (OSError, ValueError):
                    continue
                name = data.get("FriendlyName") or os.path.splitext(os.path.basename(path))[0]
                for mod in data.get("Modules") or []:
                    if isinstance(mod, dict) and mod.get("Name"):
                        found.setdefault(mod["Name"].lower(), name)
    cache[key] = found
    return found


def _project_modules(project_dir):
    try:
        project = next(f for f in os.listdir(project_dir) if f.lower().endswith(".uproject"))
        with open(os.path.join(project_dir, project), encoding="utf-8-sig") as f:
            return {m["Name"].lower() for m in json.load(f).get("Modules") or [] if isinstance(m, dict) and m.get("Name")}
    except (OSError, ValueError, StopIteration):
        return set()


def culprit(modules, plugins, own, in_kit=False):
    """Beteiligtes Plugin, eigener Code oder ein verstaendlicher Engine-Bereich - sonst None."""
    frames = [m for m in modules if not SKIP_MODULES.match(m)][:20]
    for m in frames:  # Plugins und Projektcode zuerst, auch wenn sie weiter unten im Stack stehen
        if m.lower() in plugins:
            return {"kind": "plugin", "name": plugins[m.lower()]}
        if m.lower() in own:
            return {"kind": "game" if in_kit else "project", "name": m}
    for m in frames[:6]:
        for area, rule in ENGINE_AREAS:
            if rule.search(m):
                return {"kind": "engine", "name": area}
    return None


def _read_log(folder):
    """Ende des Logs im Absturzordner (der groesste .log) als Zeilen."""
    try:
        logs = sorted((e for e in os.scandir(folder) if e.name.lower().endswith(".log") and e.is_file()),
                      key=lambda e: e.stat().st_size, reverse=True)
    except OSError:
        return []
    if not logs:
        return []
    try:
        with open(logs[0].path, "rb") as f:
            head = f.read(2)
            size = os.fstat(f.fileno()).st_size
            f.seek(max(0, size - LOG_TAIL))
            raw = f.read()
    except OSError:
        return []
    if head in (b"\xff\xfe", b"\xfe\xff"):
        raw = raw[len(raw) % 2:]
        text = raw.decode("utf-16-le" if head == b"\xff\xfe" else "utf-16-be", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    return text.splitlines()[1:]  # erste Zeile ist abgeschnitten


def log_details(lines):
    """Letzte Warnungen/Fehler vor dem Absturz und die gemeldeten Speicherwerte."""
    end = next((i for i, l in enumerate(lines) if RE_CRASH_LINE.search(l)), len(lines))
    before = lines[max(0, end - 4000):end]
    picked = []
    for line in before:
        if ": Error:" not in line and ": Warning:" not in line:
            continue
        text = RE_LOG_PREFIX.sub("", line).strip()
        if RE_NOISE.search(text) or RE_NOISE_CAT.search(text) or re.search(r"(Error|Warning):\s*$", text):
            continue
        text = text[:300]
        count = next((n for t, n in picked if t == text), 0)  # gleiche Zeile nur einmal, an ihrer letzten Stelle
        picked = [p for p in picked if p[0] != text] + [[text, count + 1]]
    facts = {}
    window = lines[max(0, end - 400):end + 40]
    for line in window:
        m = re.search(r"Local Budget:\s*([\d.]+) MB", line)
        if m:
            facts["vramBudget"] = float(m.group(1))
        m = re.search(r"Local Used:\s*([\d.]+) MB", line)
        if m:
            facts["vramUsed"] = float(m.group(1))
        m = re.search(r"Physical Memory: ([\d.]+) MB used,\s*([\d.]+) MB free, ([\d.]+) MB total", line)
        if m:
            facts["ramUsed"], facts["ramTotal"] = float(m.group(1)), float(m.group(3))
    return [{"text": t, "count": n} for t, n in picked[-LOG_LINES:]], facts


def details(folder, project_dir, message, cache):
    """Zusaetzliche Angaben zum Bericht in folder (nur fuer den neuesten je Gruppe, das Log ist gross)."""
    try:
        with open(os.path.join(folder, REPORT), "rb") as f:
            raw = f.read(MAX_READ * 2)
        text = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8", errors="replace")
    except OSError:
        text = ""
    base = _tag(text, "BaseDir").replace("\\", "/").rstrip("/")  # .../Engine/Binaries/Win64
    engine_dir = os.path.dirname(os.path.dirname(base)) if base.lower().endswith("binaries/win64") else ""
    plugins = _plugin_modules(project_dir, engine_dir, cache)
    own = cache.setdefault(("own", project_dir), _project_modules(project_dir))
    in_kit = bool(engine_dir) and os.path.normcase(os.path.abspath(project_dir)).startswith(
        os.path.normcase(os.path.abspath(os.path.dirname(engine_dir))) + os.sep)
    lines, facts = log_details(_read_log(folder))
    asset, source = RE_ASSET.search(message), "message"
    if not asset:  # sonst das zuletzt genannte Asset aus den Log-Zeilen davor
        source = "log"
        for entry in reversed(lines):
            asset = RE_ASSET.search(entry["text"])
            if asset:
                break
    name = re.sub(r"UEDPIE_\d+_", "", asset.group(1)) if asset else ""  # Kopie fuers Testspielen -> eigentliche Map
    return {"activity": activity(_tag(text, "UserActivityHint")), "culprit": culprit(_module_names(text), plugins, own, in_kit),
            "asset": name, "assetSource": source if name else "", "log": lines, "facts": facts}


def scan(projects):
    """projects: [{dir, name, displayName}] -> Gruppen gleicher Fehler, die haeufigsten zuerst."""
    groups, total, used, seen = {}, 0, set(), set()
    for proj in projects:
        root = os.path.normcase(os.path.abspath(proj["dir"]))
        if root in seen:
            continue
        seen.add(root)
        crash_dir = os.path.join(proj["dir"], "Saved", "Crashes")
        try:
            folders = [e.path for e in os.scandir(crash_dir) if e.is_dir()]
        except OSError:
            continue
        folders.sort(key=lambda p: _mtime(p), reverse=True)
        name = proj.get("displayName") or proj["name"]
        for folder in folders[:MAX_REPORTS]:
            report = read_report(folder)
            if not report:
                continue
            total += 1
            used.add(root)
            key = (root, report["category"], _signature(report["message"]))
            g = groups.get(key)
            if g is None:
                g = groups[key] = {"project": name, "dir": proj["dir"], "category": report["category"], "ensure": report["ensure"],
                                   "message": report["message"][:800], "version": report["version"], "count": 0, "last": 0, "folder": folder}
            g["count"] += 1
            if report["time"] >= g["last"]:
                g.update(last=report["time"], folder=folder, version=report["version"] or g["version"])
    items = sorted(groups.values(), key=lambda g: (-g["count"], -g["last"]))
    cache = {}
    for g in items:
        if g["category"] == "unreadable":
            continue
        try:
            g.update(details(g["folder"], g["dir"], g["message"], cache))
        except Exception:  # Details sind Zugabe - ohne sie bleibt die Karte wie bisher
            pass
    return {"items": items, "total": total, "projects": len(used)}


# --- "KI fragen": Text vor dem Senden von persoenlichen Angaben befreien ---------------
AI_PROVIDERS = {  # nur diese Adressen werden geoeffnet; der Text haengt als ?q= an
    "claude": "https://claude.ai/new?q=",
    "chatgpt": "https://chatgpt.com/?q=",
    "gemini": "https://gemini.google.com/app?q=",  # nicht offiziell dokumentiert - Text liegt auch in der Zwischenablage
    "grok": "https://grok.com/?q=",
}
AI_MAX_URL = 7000  # laengere Adressen lehnen manche Dienste ab
RE_USERDIR = re.compile(r"[A-Za-z]:[\\/]+(?:Users|Benutzer)[\\/]+[^\\/\s'\"\]\)]+", re.I)
RE_UNC = re.compile(r"\\\\[^\s'\"\]\)]+")
RE_PATH = re.compile(r"(?<![\w%])[A-Za-z]:[\\/][^\s'\"\]\)<>|,;]*")
RE_GUID = re.compile(r"\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?")
RE_HEXID = re.compile(r"\b[0-9a-fA-F]{24,}\b")
RE_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RE_URLQ = re.compile(r"(https?://[^\s?'\"\]]+)\?[^\s'\"\]]*")


def _short_path(m):
    """Nur die letzten Teile eines Pfads behalten - sie sagen, welche Datei betroffen ist."""
    parts = [p for p in re.split(r"[\\/]+", m.group(0)) if p]
    return "…\\" + "\\".join(parts[-3:]) if len(parts) > 3 else m.group(0)


def scrub(text, names=()):
    """Benutzerordner, Laufwerkspfade, Netzwerkpfade, IDs, E-Mails, URL-Parameter und Namen entfernen."""
    text = RE_USERDIR.sub("%USERPROFILE%", text)
    text = RE_UNC.sub("<network path>", text)
    text = RE_PATH.sub(_short_path, text)
    text = RE_URLQ.sub(r"\1", text)
    text = RE_GUID.sub("<id>", text)
    text = RE_HEXID.sub("<id>", text)
    text = RE_MAIL.sub("<e-mail>", text)
    for name in sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True):
        text = re.sub(re.escape(name), "<user>", text, flags=re.I)
    return text


def ai_url(provider, text):
    """Fertige Adresse oder None; zu lange Texte werden hinten gekuerzt."""
    from urllib.parse import quote
    base = AI_PROVIDERS.get(provider)
    if not base:
        return None
    text = text.strip()
    url = base + quote(text, safe="")
    while len(url) > AI_MAX_URL and text:
        text = text[: int(len(text) * 0.9)].rstrip()
        url = base + quote(text + "\n…", safe="")
    return url


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0

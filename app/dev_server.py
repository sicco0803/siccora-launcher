"""Nur fuer die Entwicklung: dieselbe Oberflaeche im Browser statt im App-Fenster.

Stellt ui/ unter http://127.0.0.1:8765 bereit und leitet /api/<methode>
an dieselbe Api-Klasse weiter, die auch das App-Fenster nutzt.
Lauscht nur lokal.
"""
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from main import HERE, Api

PORT = 8765
api = Api()
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ORIGINS = {f"http://{h}" for h in HOSTS}
ALLOWED = {"account", "library", "fab", "open_url", "open_folder", "open_login_page", "login",
           "settings", "downloads_list", "check_updates", "update_preview", "fab_options", "fab_plan", "set_language", "save_settings", "components", "components_summary",
           "projects", "project_thumb", "delete_project_info", "home", "free_assets", "rename_project", "local_assets", "home_storage"}  # Installieren usw. nur im echten App-Fenster


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(HERE, "ui"), **kwargs)

    def do_POST(self):
        # Schutz gegen fremde Webseiten (CSRF/DNS-Rebinding): nur eigene Herkunft,
        # nur JSON - das erzwingt beim Browser eine Vorabpruefung, die hier nie beantwortet wird
        origin = self.headers.get("Origin")
        if (self.headers.get("Host") not in HOSTS or (origin and origin not in ORIGINS)
                or self.headers.get("Content-Type") != "application/json"):
            self.send_error(403)
            return
        name = self.path.removeprefix("/api/")
        if name not in ALLOWED:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        args = json.loads(self.rfile.read(length) or b"[]")
        body = json.dumps(getattr(api, name)(*args)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Vorschau: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

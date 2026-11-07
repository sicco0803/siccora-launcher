"""Epic-Anmeldung fuer den Machbarkeitstest.

Oeffnet die Epic-Login-Seite im Browser. Danach den kompletten angezeigten
Text (oder nur den Code) hier einfuegen - beides wird erkannt.
"""
import re
import webbrowser

from legendary.core import LegendaryCore

LOGIN_URL = "https://legendary.gl/epiclogin"

core = LegendaryCore()
if core.lgd.userdata and core.login():
    print(f"Bereits angemeldet als: {core.lgd.userdata['displayName']}")
    raise SystemExit(0)

print("Die Epic-Login-Seite wird im Browser geoeffnet...")
webbrowser.open(LOGIN_URL)
print(f"(Falls nicht: {LOGIN_URL} von Hand oeffnen)\n")

text = input("Angezeigten Text hier einfuegen und Enter druecken: ").strip()
match = re.search(r'"authorizationCode"\s*:\s*"([0-9a-f]{32})"', text) or re.search(r"\b([0-9a-f]{32})\b", text)
if not match:
    print("Kein Code erkannt. Bitte das Skript neu starten.")
    raise SystemExit(1)

if core.auth_code(match.group(1)):
    print(f"\nAnmeldung erfolgreich: {core.lgd.userdata['displayName']}")
    print("Du kannst diesen Tab jetzt schliessen.")
else:
    print("\nAnmeldung fehlgeschlagen (Code evtl. abgelaufen). Bitte Skript neu starten und schnell einfuegen.")

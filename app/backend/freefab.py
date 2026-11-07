"""Die aktuellen Gratis-Assets von Fab ("Limited-Time Free") fuer die Startseite.

Fab liefert sie ueber eine oeffentliche Adresse - ohne Anmeldung, es werden keine
Kontodaten gesendet. Zwischengespeichert fuer einige Stunden; ist Fab nicht
erreichbar, bleibt der letzte Stand sichtbar, solange die Aktion noch laeuft.
"""
import calendar
import time

import requests

from .epic import _load, _save

BLADE_URL = "https://www.fab.com/i/blades/free_content_blade"
PAGE_URL = "https://www.fab.com/limited-time-free"
CACHE = "free_fab.json"
MAX_AGE = 6 * 3600
IMAGE_WIDTH = 960  # bleibt auch im maximierten Fenster scharf


def _image(listing):
    """Vorschaubild passender Groesse: das kleinste, das breit genug ist."""
    thumbs = listing.get("thumbnails") or []
    images = sorted((thumbs[0].get("images") or []) if thumbs else [], key=lambda i: i.get("width") or 0)
    pick = next((i for i in images if (i.get("width") or 0) >= IMAGE_WIDTH), images[-1] if images else None)
    return pick.get("url") if pick else None


def _offer(listing):
    """Normalpreis und Ende der Aktion aus der guenstigsten Lizenz."""
    tiers = [lic.get("priceTier") or {} for lic in listing.get("licenses") or []]
    tiers = [t for t in tiers if t.get("price") is not None]
    if not tiers:
        return None, None, None
    tier = min(tiers, key=lambda t: t["price"])
    return tier["price"], tier.get("currencyCode"), tier.get("discountEndDate")


def _parse(blade):
    items = []
    for tile in blade.get("tiles") or []:
        listing = tile.get("listing") or {}
        if not listing.get("uid"):
            continue
        price, currency, until = _offer(listing)
        items.append({
            "id": listing["uid"],
            "title": listing.get("title") or "",
            "seller": (listing.get("user") or {}).get("sellerName") or "",
            "image": _image(listing),
            "url": f"https://www.fab.com/listings/{listing['uid']}",
            "price": price, "currency": currency, "until": until,
        })
    return items


def _ended(until):
    try:
        return calendar.timegm(time.strptime(until[:19], "%Y-%m-%dT%H:%M:%S")) < time.time()
    except (TypeError, ValueError):
        return False


def current(library_urls=(), refresh=False):
    """Gratis-Assets; owned = schon in der eigenen Fab-Bibliothek."""
    cached = _load(CACHE, None)
    stale = (not cached or refresh or time.time() - cached.get("fetched", 0) > MAX_AGE
             or any(_ended(i.get("until")) for i in cached.get("items", [])))
    failed = False
    if stale:
        try:
            r = requests.get(BLADE_URL, headers={"Accept": "application/json", "User-Agent": "SiccoraLauncher"},
                             timeout=15)
            r.raise_for_status()
            cached = {"fetched": time.time(), "items": _parse(r.json())}
            _save(CACHE, cached)
        except (requests.RequestException, ValueError):
            failed = True
    items = [i for i in (cached or {}).get("items", []) if not _ended(i.get("until"))]
    urls = set(library_urls)
    return {"items": [{**i, "owned": i["url"] in urls} for i in items], "url": PAGE_URL, "failed": failed and not items}

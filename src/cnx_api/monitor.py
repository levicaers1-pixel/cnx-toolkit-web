"""Lezen via de API van new Central: lijsten met paginering en nette foutmeldingen, voor cnx web.

Paden en velden volgens de referentie op developer.arubanetworks.com/new-central/reference (november 2026).
Gebruikt de sessie en het aanmelden van cnx api (alias_api).
"""
import re
from urllib.parse import quote

from . import alias_api as cx
from .taal import _

MON = "/network-monitoring/v1"
MAX_PAGINAS = 50
SERIAL = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class ApiFout(Exception):
    def __init__(self, status, melding):
        super().__init__(melding)
        self.status, self.melding = status, melding


def _json(r):
    try:
        return r.json()
    except ValueError:
        return None


def _melding(r):
    j = _json(r)
    if isinstance(j, dict):
        return str(j.get("message") or j.get("errorCode") or r.text[:300])
    return r.text[:300]


def haal(pad, params=None):
    r = cx.api("GET", pad, params)
    if r.status_code >= 300:
        raise ApiFout(r.status_code, _melding(r))
    return _json(r)


def _items(j):
    if isinstance(j, dict):
        for k in ("items", "events"):
            if isinstance(j.get(k), list):
                return j[k]
    return j if isinstance(j, list) else []


def alles_next(pad, params):
    """Pagina's met een next-cursor (in de praktijk een paginanummer) aflopen."""
    params, items, j = dict(params), [], {}
    for _pagina in range(MAX_PAGINAS):
        j = haal(pad, params) or {}
        items += _items(j)
        nxt = j.get("next") if isinstance(j, dict) else None
        if not nxt:
            return {"items": items, "total": j.get("total", len(items)) if isinstance(j, dict) else len(items)}
        params["next"] = nxt
    return {"items": items, "total": j.get("total"), "afgekapt": True}


def alles_offset(pad, params):
    """Pagina's met offset en total aflopen."""
    params, items, j = dict(params), [], {}
    params.setdefault("limit", 1000)
    off = 0
    for _pagina in range(MAX_PAGINAS):
        params["offset"] = off
        j = haal(pad, params) or {}
        nieuw = _items(j)
        items += nieuw
        total = j.get("total") if isinstance(j, dict) else None
        if not nieuw or total is None or len(items) >= int(total):
            return {"items": items, "total": total if total is not None else len(items)}
        off += len(nieuw)
    return {"items": items, "total": j.get("total"), "afgekapt": True}


def serial(s):
    s = str(s or "").strip()
    if not SERIAL.match(s):
        raise Invoer(_("ongeldig serienummer of stack-ID"))
    return quote(s, safe="")


def filter_tekst(f):
    f = str(f or "").strip()
    if len(f) > 256 or "\n" in f:
        raise Invoer(_("filter te lang of ongeldig"))
    return f


# ---------------------------------------------------------------- lijsten (alleen-lezen)

LIJSTEN = {
    "switches": (MON + "/switches", alles_next, {"limit": 1000}),
    "devices": (MON + "/devices", alles_next, {"limit": 1000}),
    "inventaris": (MON + "/device-inventory", alles_next, {"limit": 1000}),
    "firmware": ("/network-services/v1/firmware-details", alles_next, {"limit": 1000}),
    "sites": (MON + "/sites-health", alles_offset, {"limit": 1000}),
    "sitesdevices": (MON + "/sites-device-health", alles_offset, {"limit": 1000}),
    "alerts": ("/network-notifications/v1/alerts", alles_next, {"limit": 100}),
}


def lijst(soort, filter_=""):
    if soort not in LIJSTEN:
        raise Invoer(_("onbekende lijst"))
    pad, functie, params = LIJSTEN[soort]
    params = dict(params)
    f = filter_tekst(filter_)
    if f:
        params["filter"] = f
    return functie(pad, params)


# ---------------------------------------------------------------- een switch (alleen-lezen)


# ---------------------------------------------------------------- probleemoplossing (AOS-CX)

class Invoer(ApiFout):
    def __init__(self, melding):
        super().__init__(400, melding)



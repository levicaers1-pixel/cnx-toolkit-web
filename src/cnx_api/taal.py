"""Taal van de webapp: Nederlands (standaard) of Engels.

De browser bewaart de keuze in de cookie cnx_taal; zonder cookie geldt de taal van de browser (Accept-Language).
Per aanvraag zet de webserver de taal in een contextvar, zodat meldingen in configapi, aos8 en migratieplan in de
juiste taal komen. De commandolijn blijft Nederlands.

Vertalen: _("Nederlandse tekst met {naam}", naam=...) geeft de Engelse versie uit data/en-server.json als de taal
Engels is. De Nederlandse tekst is de sleutel; ontbreekt een vertaling, dan blijft het Nederlands (een test bewaakt
dat er geen ontbreekt).
"""
import contextvars
import json

from . import resource

TALEN = ("nl", "en")
_HUIDIG = contextvars.ContextVar("cnx_taal", default="nl")
_EN = None


def _en():
    global _EN
    if _EN is None:
        with open(resource("en-server.json"), encoding="utf-8") as f:
            _EN = json.load(f)
    return _EN


def kies(cookie_taal, accept_language):
    """De taal van een aanvraag: de cookie als die geldig is, anders de eerste taal van de browser (nl of en)."""
    if cookie_taal in TALEN:
        return cookie_taal
    for deel in (accept_language or "").split(","):
        code = deel.split(";")[0].strip().lower()[:2]
        if code in TALEN:
            return code
        if code:
            return "en"                    # een andere taal dan nl of en: Engels
    return "nl"


def zet(taal):
    _HUIDIG.set(taal if taal in TALEN else "nl")


def huidig():
    return _HUIDIG.get()


def _(sjabloon, /, **waarden):
    """Vertaal een vaste tekst (de Nederlandse versie is de sleutel) en vul de {namen} in."""
    if _HUIDIG.get() == "en":
        sjabloon = _en().get(sjabloon, sjabloon)
    return sjabloon.format(**waarden) if waarden else sjabloon

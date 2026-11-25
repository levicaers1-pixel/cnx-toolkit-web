"""Servermodus: elke browser een eigen verbinding met Central. Twee gebruikers mogen elkaars aanmelding, data,
ophalingen en wisplannen nooit zien, ook niet bij gelijktijdige aanvragen."""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import nep_central  # noqa: E402
from cnx_api import alias_api as cx, web  # noqa: E402
from test_web import server  # noqa: E402,F401


class Browser:
    """Een gebruiker met een eigen cookie, zoals een eigen browser. Opent eerst de pagina: daar komen de sessie en het
    eigen token (CSRF) vandaan. De cookie wordt met de hand bijgehouden (ze is Secure in servermodus)."""

    def __init__(self, server, pagina=True):
        self.server, self.cookie, self.token = server, None, None
        if pagina:
            s, html = self.ruw("/")
            assert s == 200, s
            self.token = re.search(r'const T = "([^"]+)"', html.decode()).group(1)

    def ruw(self, pad, body=None, token=None, headers=None):
        h = dict(headers or {})
        if token:
            h["X-Token"] = token
        if self.cookie:
            h["Cookie"] = "cnx_sessie=" + self.cookie
        data = None
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        try:
            r = urllib.request.urlopen(urllib.request.Request(self.server + pad, data=data, headers=h), timeout=10)
        except urllib.error.HTTPError as e:
            r = e
        with r:
            self.koppen = r.headers
            for c in r.headers.get_all("Set-Cookie") or []:
                m = re.match(r"cnx_sessie=([^;]+)", c)
                if m:
                    self.cookie, self.set_cookie = m.group(1), c
            return r.status, r.read()

    def vraag(self, pad, body=None):
        s, b = self.ruw(pad, body, token=self.token)
        return s, json.loads(b or b"null")


@pytest.fixture
def twee(server, monkeypatch):
    monkeypatch.setattr(web, "PER_SESSIE", True)
    monkeypatch.setattr(web, "SESSIES", {})
    monkeypatch.setattr(web, "_NIEUW", {})
    # Aanmelden zonder echte Central: het token draagt de client-ID, zodat we zien welke verbinding een aanvraag deed.
    monkeypatch.setattr(cx, "_token", lambda v, cid, secret: v.s.headers.update(Authorization="Bearer " + cid) and None)
    gezien = []

    def api(method, pad, params=None, body=None):
        v = cx.verbinding()
        gezien.append((threading.current_thread().name, v.base, v.s.headers.get("Authorization")))
        time.sleep(0.005)             # aanvragen overlappen echt
        return nep_central.api(method, pad, params, body)

    monkeypatch.setattr(cx, "api", api)
    a, b = Browser(server), Browser(server)
    assert a.vraag("/api/aanmelden", {"base": "https://central-a", "id": "anna", "secret": "x"})[1]["ok"]
    return a, b, gezien


def test_aanmelding_is_per_browser(twee):
    a, b, gezien = twee
    assert a.vraag("/api/status")[1]["aangemeld"] is True
    s, r = b.vraag("/api/status")
    assert r["aangemeld"] is False and r["base"] == ""
    s, r = b.vraag("/api/web/ov/groepswitches?groep=ACCESS")
    assert s == 401
    s, r = a.vraag("/api/web/ov/groepswitches?groep=ACCESS")
    assert s == 200 and r["rijen"]
    assert gezien and {(base, tok) for _, base, tok in gezien} == {("https://central-a", "Bearer anna")}


def test_gelijktijdige_aanvragen_blijven_gescheiden(twee):
    a, b, gezien = twee
    assert b.vraag("/api/aanmelden", {"base": "https://central-b", "id": "bert", "secret": "y"})[1]["ok"]
    gezien.clear()
    fouten = []

    def lees(browser):
        s, r = browser.vraag("/api/web/ov/groepswitches?groep=ACCESS")
        if s != 200:
            fouten.append(s)

    draden = [threading.Thread(target=lees, args=(x,)) for x in (a, b) * 6]
    [d.start() for d in draden]
    [d.join() for d in draden]
    assert not fouten
    # Elke aanvraag naar Central ging met de URL en het token van dezelfde gebruiker, nooit gemengd.
    assert {(base, tok) for _, base, tok in gezien} == {("https://central-a", "Bearer anna"), ("https://central-b", "Bearer bert")}


def test_afmelden_raakt_enkel_de_eigen_sessie(twee):
    a, b, _ = twee
    assert b.vraag("/api/aanmelden", {"base": "https://central-b", "id": "bert", "secret": "y"})[1]["ok"]
    b.vraag("/api/web/afmelden", {})
    assert b.vraag("/api/status")[1]["aangemeld"] is False
    assert a.vraag("/api/status")[1]["aangemeld"] is True


def test_ophaling_enkel_zichtbaar_voor_eigenaar(twee):
    a, b, gezien = twee
    s, r = a.vraag("/api/web/ov/ophaal", {"soort": "afwijkingen", "opties": {"serials": ["SG00TEST01"]}})
    assert s == 200, r
    oid = r["id"]
    for _ in range(200):
        s, info = a.vraag("/api/web/ov/ophaling?id=" + oid)
        if info["status"] != "bezig":
            break
        time.sleep(0.02)
    assert s == 200 and info["status"] == "klaar", info
    # De achtergrondtaak gebruikte de verbinding van a.
    assert ("https://central-a", "Bearer anna") in {(base, tok) for _, base, tok in gezien}
    assert all(base == "https://central-a" for _, base, _ in gezien)
    assert b.vraag("/api/web/ov/ophaling?id=" + oid)[0] == 404


def test_wisplan_van_een_ander_niet_uitvoerbaar(twee):
    a, b, _ = twee
    assert b.vraag("/api/aanmelden", {"base": "https://central-b", "id": "bert", "secret": "y"})[1]["ok"]
    sessie_a = next(s for s in web.SESSIES.values() if s.verbinding.base == "https://central-a")
    sessie_a.wisplannen["wis-test"] = ([], "ACCESS_SWITCH")
    s, r = b.vraag("/api/web/ov/ophaal", {"soort": "wissen", "opties": {"plan": "wis-test"}})
    assert s == 400 and "verlopen" in r["fout"]
    assert "wis-test" in sessie_a.wisplannen


def test_lokale_modus_deelt_de_standaardverbinding(server, monkeypatch):
    """Zonder servermodus (de exe op je eigen pc) blijft alles zoals vroeger: een verbinding voor iedereen."""
    monkeypatch.setattr(web, "PER_SESSIE", False)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    a, b = Browser(server), Browser(server)
    assert a.vraag("/api/status")[1]["aangemeld"] is True and b.vraag("/api/status")[1]["aangemeld"] is True
    assert a.cookie is None                  # geen cookie nodig

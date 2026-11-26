"""Servermodus (cnx web --server): toegelaten hosts, sessie en CSRF-token per browser, time-out, limieten, logs zonder
gegevens, veiligheidskoppen en enkel URL's van Central bij het aanmelden."""
import json
import urllib.error
import urllib.request
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import nep_central  # noqa: E402
from cnx_api import alias_api as cx, web  # noqa: E402
from test_sessies import Browser  # noqa: E402

CENTRAL = "https://de1.api.central.arubanetworks.com"


@pytest.fixture
def srv(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "SERVER", True)
    monkeypatch.setattr(web, "PER_SESSIE", True)
    monkeypatch.setattr(web, "OPSLAG", False)
    monkeypatch.setattr(web, "TOEGELATEN_HOSTS", {"127.0.0.1"})
    monkeypatch.setattr(web, "SESSIES", {})
    monkeypatch.setattr(web, "_NIEUW", {})
    monkeypatch.setattr(web, "_PILOT_FOUT", {})
    monkeypatch.setattr(web, "PILOTCODE", "")
    monkeypatch.setattr(web, "WERKMAP", str(tmp_path / "cnx-web"))
    monkeypatch.setattr(cx, "_token", lambda v, cid, secret: v.s.headers.update(Authorization="Bearer " + cid) and None)
    monkeypatch.setattr(cx, "api", nep_central.api)
    s = web.maak_server(0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}", None
    s.shutdown()
    s.server_close()
    assert not (tmp_path / "cnx-web").exists()


def test_gezondheidscheck_zonder_sessie_of_host(srv):
    server, _ = srv
    b = Browser(server, pagina=False)
    assert b.ruw("/gezond", headers={"Host": "intern:8080"}) == (200, b'{"ok": true}')
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(server + "/gezond", method="HEAD"), timeout=5) as r:
        assert r.status == 200
    assert b.ruw("/favicon.ico")[0] == 204
    assert web.SESSIES == {}


def test_enkel_toegelaten_hosts(srv):
    server, _ = srv
    b = Browser(server, pagina=False)
    assert b.ruw("/", headers={"Host": "evil.example"})[0] == 403
    assert b.ruw("/", headers={"Host": "127.0.0.1:1234"})[0] == 200


def test_sessie_enkel_via_de_pagina_met_veilige_cookie(srv):
    server, _ = srv
    zonder = Browser(server, pagina=False)
    assert zonder.ruw("/api/status")[0] == 401 and web.SESSIES == {}       # een losse aanvraag maakt geen sessie
    b = Browser(server)
    assert len(web.SESSIES) == 1
    vlaggen = {x.strip().lower() for x in b.set_cookie.split(";")[1:]}
    assert {"httponly", "secure", "samesite=strict", "path=/"} <= vlaggen
    assert b.vraag("/api/status") == (200, {"aangemeld": False, "base": "", "env": False, "glp": False, "glp_gedeeld": False})


def test_csrf_token_per_sessie(srv):
    server, _ = srv
    a, b = Browser(server), Browser(server)
    assert a.token != b.token and a.token != web.TOKEN
    assert a.ruw("/api/status", token=b.token)[0] == 403           # token van een ander
    assert a.ruw("/api/status", token=web.TOKEN)[0] == 403      # het vaste token van de lokale app
    assert a.ruw("/api/status")[0] == 403                           # geen token
    assert a.ruw("/api/web/afmelden", {}, token=b.token)[0] == 403
    assert a.vraag("/api/status")[0] == 200


def test_aanmelden_enkel_bij_central_en_nieuw_sessie_id(srv):
    server, _ = srv
    b = Browser(server)
    for slecht in ("http://de1.api.central.arubanetworks.com", "https://169.254.169.254", "https://evil.example",
                   "https://arubanetworks.com.evil.example", "https://x@de1.api.central.arubanetworks.com",
                   "https://de1.api.central.arubanetworks.com:8443", "file:///etc/passwd", ""):
        s, r = b.vraag("/api/aanmelden", {"base": slecht, "id": "anna", "secret": "x"})
        assert s == 200 and r["ok"] is False, slecht
    oud = b.cookie
    assert b.vraag("/api/aanmelden", {"base": CENTRAL, "id": "anna", "secret": "x"})[1]["ok"] is True
    assert b.cookie != oud                                           # nieuw sessie-id na aanmelden
    oude = Browser(server, pagina=False)
    oude.cookie, oude.token = oud, b.token
    assert oude.vraag("/api/status")[0] == 401                       # het oude id werkt niet meer
    assert b.vraag("/api/status")[1]["aangemeld"] is True


def test_sessie_verloopt_en_wist_het_secret(srv, monkeypatch):
    server, _ = srv
    b = Browser(server)
    b.vraag("/api/aanmelden", {"base": CENTRAL, "id": "anna", "secret": "geheim"})
    sessie = next(iter(web.SESSIES.values()))
    assert sessie.verbinding.gegevens["secret"] == "geheim"
    sessie.laatst -= web.SESSIE_DUUR + 1
    assert b.vraag("/api/status")[0] == 401
    assert web.SESSIES == {} and sessie.verbinding.gegevens == {} and not sessie.verbinding.aangemeld


def test_afmelden_wist_alles_van_de_sessie(srv):
    server, _ = srv
    b = Browser(server)
    b.vraag("/api/aanmelden", {"base": CENTRAL, "id": "anna", "secret": "geheim"})
    sessie = next(iter(web.SESSIES.values()))
    sessie.wisplannen["wis-x"] = ([], "ACCESS_SWITCH")
    assert b.vraag("/api/web/afmelden", {})[0] == 200
    assert sessie.verbinding.gegevens == {} and not sessie.verbinding.aangemeld and sessie.wisplannen == {}


def test_maximum_aantal_sessies(srv, monkeypatch):
    server, _ = srv
    monkeypatch.setattr(web, "MAX_SESSIES", 2)
    Browser(server), Browser(server)
    s, _ = Browser(server, pagina=False).ruw("/")
    assert s == 503 and len(web.SESSIES) == 2


def test_maximum_lopende_taken(srv, monkeypatch):
    server, _ = srv
    b = Browser(server)
    b.vraag("/api/aanmelden", {"base": CENTRAL, "id": "anna", "secret": "x"})
    stop = threading.Event()
    monkeypatch.setattr(web.configapi, "afwijkingen_scan", lambda *a: stop.wait(5) or {})
    try:
        for _ in range(web.MAX_TAKEN):
            assert b.vraag("/api/web/ov/ophaal", {"soort": "afwijkingen", "opties": {}})[0] == 200
        s, r = b.vraag("/api/web/ov/ophaal", {"soort": "afwijkingen", "opties": {}})
        assert s == 400 and "taken" in r["fout"]
    finally:
        stop.set()


def test_te_grote_aanvraag(srv, monkeypatch):
    server, _ = srv
    monkeypatch.setattr(web, "MAX_BODY_SERVER", 1000)
    monkeypatch.setattr(web, "MAX_BODY_AOS8", 500)
    b = Browser(server)
    s, r = b.vraag("/api/web/onboard/bestand", {"groep": "x", "rijen": ["A" * 2000]})
    assert s == 413
    s, r = b.vraag("/api/web/aos8/gereedheid", {"bestanden": [{"naam": "x.txt", "inhoud": "A" * 700}]})
    assert s == 413


def test_oude_overrides_routes_zijn_dicht(srv):
    server, _ = srv
    b = Browser(server)
    assert b.vraag("/api/switches")[0] == 404
    assert b.vraag("/api/overrides?serial=X")[0] == 404
    assert b.vraag("/api/wissen", {"serial": "X", "items": [], "echt": True})[0] == 404


def test_logs_zonder_parameters_en_met_veiligheidskoppen(srv, capsys):
    server, _ = srv
    b = Browser(server)
    b.vraag("/api/aanmelden", {"base": CENTRAL, "id": "anna", "secret": "geheim"})
    s, _ = b.vraag("/api/web/ov/groepswitches?groep=ACCESS&vlan=120&x=GEHEIME_GROEP")
    assert s == 200
    time.sleep(0.05)
    tekst = capsys.readouterr().err
    assert "GET /api/web/ov/groepswitches 200" in tekst and "POST /api/aanmelden 200" in tekst
    for geheim in ("GEHEIME_GROEP", "geheim", "anna", b.token, b.cookie, "127.0.0.1", "SG00TEST"):
        assert geheim not in tekst, geheim
    for k, v in (("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "SAMEORIGIN"),
                 ("Referrer-Policy", "no-referrer"), ("Cache-Control", "no-store")):
        assert b.koppen.get(k) == v, k


def test_servermodus_vraagt_een_hostnaam(monkeypatch):
    monkeypatch.setattr(web, "TOEGELATEN_HOSTS", set())
    monkeypatch.delenv("CNX_HOSTS", raising=False)
    monkeypatch.setattr(sys, "argv", ["cnx", "--server"])
    for k, v in (("SERVER", False), ("PER_SESSIE", False), ("OPSLAG", True)):
        monkeypatch.setattr(web, k, v)
    with pytest.raises(SystemExit, match="host-naam"):
        web.main()


def test_central_url_ok():
    assert web.central_url_ok("https://de1.api.central.arubanetworks.com")
    assert web.central_url_ok("https://us4.api.central.arubanetworks.com/")
    assert not web.central_url_ok("https://evilarubanetworks.com")


def test_nieuwe_sessies_per_bezoeker_begrensd(srv, monkeypatch):
    server, _ = srv
    monkeypatch.setattr(web, "VERTROUW_PROXY", True)          # achter Azure Container Apps (CNX_PROXY=1)
    monkeypatch.setattr(web, "NIEUW_PER_MINUUT", 3)
    van = lambda ip: {"X-Forwarded-For": "6.6.6.6, " + ip}  # noqa: E731  (het eerste adres kan de bezoeker verzinnen)
    for _ in range(3):
        assert Browser(server, pagina=False).ruw("/", headers=van("10.0.0.1"))[0] == 200
    assert Browser(server, pagina=False).ruw("/", headers=van("10.0.0.1"))[0] == 503
    assert Browser(server, pagina=False).ruw("/", headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"})[0] == 503
    assert Browser(server, pagina=False).ruw("/", headers=van("10.0.0.2"))[0] == 200     # een andere bezoeker wel
    assert len(web.SESSIES) == 4


def test_sessie_zonder_aanmelding_verloopt_sneller(srv):
    server, _ = srv
    anoniem, aangemeld = Browser(server), Browser(server)
    aangemeld.vraag("/api/aanmelden", {"base": CENTRAL, "id": "anna", "secret": "x"})
    for s in web.SESSIES.values():
        s.laatst -= web.SESSIE_DUUR_ANONIEM + 1
    assert anoniem.vraag("/api/status")[0] == 401
    assert aangemeld.vraag("/api/status")[1]["aangemeld"] is True


def test_voettekst_enkel_in_servermodus(srv, monkeypatch):
    server, _ = srv
    s, html = Browser(server, pagina=False).ruw("/")
    assert s == 200 and b"niet gemaakt of ondersteund door HPE" in html and b"De server bewaart niets" in html
    monkeypatch.setattr(web, "SERVER", False)
    monkeypatch.setattr(web, "PER_SESSIE", False)
    s, html = Browser(server, pagina=False).ruw("/", headers={"Host": server.split("//")[1]})
    assert s == 200 and b"<footer" not in html


def _pilot_post(b, code, token=None):
    import urllib.parse
    data = urllib.parse.urlencode({"t": token or b.token_pilot, "code": code}).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    if b.cookie:
        h["Cookie"] = "cnx_sessie=" + b.cookie
    import urllib.request, urllib.error
    class Geen(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(Geen)
    try:
        r = opener.open(urllib.request.Request(b.server + "/pilot", data=data, headers=h), timeout=10)
    except urllib.error.HTTPError as e:
        r = e
    with r:
        for c in r.headers.get_all("Set-Cookie") or []:
            if c.startswith("cnx_sessie="):
                b.cookie = c.split(";")[0].split("=", 1)[1]
        return r.status, r.headers.get("Location"), r.read()


def _met_pilot(server):
    """Opent de pagina met een pilotcode actief: geeft de browser met het token van het formulier."""
    import re
    b = Browser(server, pagina=False)
    s, html = b.ruw("/")
    assert s == 200 and b"Pilotcode" in html and b"const T =" not in html
    b.token_pilot = re.search(rb'name="t" value="([^"]+)"', html).group(1).decode()
    return b


def test_pilotcode_houdt_de_app_dicht(srv, monkeypatch):
    server, _ = srv
    monkeypatch.setattr(web, "PILOTCODE", "geheim-123")
    b = _met_pilot(server)
    b.token = b.token_pilot
    assert b.vraag("/api/status")[0] == 401                    # API dicht zonder code
    assert b.ruw("/hulp")[0] == 401
    assert b.vraag("/api/web/aos8/plan", {"clusters": []})[0] == 401
    s, waar, html = _pilot_post(b, "fout")
    assert s == 403 and "klopt niet".encode() in html
    import urllib.request
    class Geen(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        urllib.request.build_opener(Geen).open(urllib.request.Request(server + "/pilot", headers={"Cookie": "cnx_sessie=" + b.cookie}), timeout=5)
        assert False, "verwacht een doorverwijzing"
    except urllib.error.HTTPError as e:
        assert e.code == 303 and e.headers["Location"] == "/"         # herladen na een foute code
    oud = b.cookie
    s, waar, _ = _pilot_post(b, "geheim-123")
    assert s == 303 and waar == "/" and b.cookie != oud         # nieuw sessie-id na de juiste code
    s, html = b.ruw("/")
    assert s == 200 and b"const T =" in html                     # nu de app zelf
    import re
    b.token = re.search(r'const T = "([^"]+)"', html.decode()).group(1)
    assert b.vraag("/api/status")[0] == 200


def test_pilotcode_vraagt_het_token_van_de_sessie(srv, monkeypatch):
    server, _ = srv
    monkeypatch.setattr(web, "PILOTCODE", "geheim-123")
    a, b = _met_pilot(server), _met_pilot(server)
    s, waar, _ = _pilot_post(a, "geheim-123", token=b.token_pilot)     # formulier van een ander (CSRF)
    assert s == 303 and next(x for x in web.SESSIES.values() if x.csrf == a.token_pilot).pilot_ok is False


def test_pilotcode_pogingen_begrensd(srv, monkeypatch):
    server, _ = srv
    monkeypatch.setattr(web, "PILOTCODE", "geheim-123")
    monkeypatch.setattr(web, "PILOT_POGINGEN", 3)
    b = _met_pilot(server)
    for _ in range(3):
        assert _pilot_post(b, "fout")[0] == 403
    s, _, html = _pilot_post(b, "geheim-123")                    # ook de juiste code even niet meer
    assert s == 429 and "Te veel".encode() in html


def test_pilotcode_niet_in_logs(srv, monkeypatch, capsys):
    server, _ = srv
    monkeypatch.setattr(web, "PILOTCODE", "geheim-123")
    b = _met_pilot(server)
    _pilot_post(b, "geheim-123")
    _pilot_post(_met_pilot(server), "verkeerd-456")
    time.sleep(0.05)
    tekst = capsys.readouterr().err
    assert "POST /pilot 303" in tekst and "geheim-123" not in tekst and "verkeerd-456" not in tekst


def test_zonder_pilotcode_open(srv):
    server, _ = srv
    s, html = Browser(server, pagina=False).ruw("/")
    assert s == 200 and b"const T =" in html and b"Pilotcode" not in html


def test_zonder_proxy_telt_het_echte_adres(srv, monkeypatch):
    """Zonder CNX_PROXY is X-Forwarded-For verzinbaar: een ander adres in de kop helpt niet om de grens te omzeilen."""
    server, _ = srv
    monkeypatch.setattr(web, "VERTROUW_PROXY", False)
    monkeypatch.setattr(web, "NIEUW_PER_MINUUT", 2)
    for i in range(2):
        assert Browser(server, pagina=False).ruw("/", headers={"X-Forwarded-For": f"10.9.9.{i}"})[0] == 200
    assert Browser(server, pagina=False).ruw("/", headers={"X-Forwarded-For": "10.9.9.99"})[0] == 503


def test_pilotcode_grens_voor_de_hele_server(srv, monkeypatch):
    server, _ = srv
    monkeypatch.setattr(web, "VERTROUW_PROXY", True)
    monkeypatch.setattr(web, "PILOTCODE", "geheim-123")
    monkeypatch.setattr(web, "PILOT_GLOBAAL", 4)
    monkeypatch.setattr(web, "_PILOT_ALLE", [])
    for i in range(4):                                          # elk een ander adres, elk een foute code
        b = _met_pilot(server)
        assert _pilot_post_van(b, "fout", f"10.1.1.{i}")[0] == 403
    b = _met_pilot(server)
    assert _pilot_post_van(b, "geheim-123", "10.1.1.50")[0] == 429


def _pilot_post_van(b, code, ip):
    import urllib.parse
    data = urllib.parse.urlencode({"t": b.token_pilot, "code": code}).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded", "Cookie": "cnx_sessie=" + b.cookie, "X-Forwarded-For": ip}
    try:
        with urllib.request.urlopen(urllib.request.Request(b.server + "/pilot", data=data, headers=h), timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_csp_hsts_en_nonce(srv):
    import re
    server, _ = srv
    b = Browser(server, pagina=False)
    s, html = b.ruw("/")
    csp = b.koppen.get("Content-Security-Policy")
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert f'<script nonce="{nonce}">'.encode() in html and b"<script>" not in html
    assert "frame-ancestors 'self'" in csp and "object-src 'none'" in csp and "unsafe-eval" not in csp
    assert b.koppen.get("Strict-Transport-Security") == "max-age=31536000"
    s2, html2 = Browser(server, pagina=False).ruw("/")
    assert nonce.encode() not in html2                                         # elke pagina een nieuwe nonce


def test_algemene_foutmelding_in_servermodus(srv, monkeypatch, capsys):
    server, _ = srv
    b = Browser(server)
    b.vraag("/api/aanmelden", {"base": CENTRAL, "id": "anna", "secret": "x"})
    def kapot(*a, **k):
        raise RuntimeError("interne details van /pad/naar/bestand")
    monkeypatch.setattr(web.configapi, "keuzes", kapot)
    s, r = b.vraag("/api/web/ov/keuzes")
    assert s == 500 and "interne details" not in r["fout"] and "Onverwachte fout" in r["fout"]
    assert "onverwachte fout: RuntimeError" in capsys.readouterr().err


def test_zware_verwerkingen_begrensd(srv, monkeypatch):
    """Lopen er al zoveel AP-migraties als de grens toelaat, dan krijgt de volgende 503 (na het wachten)."""
    server, _ = srv

    class Vol:
        def acquire(self, timeout=None):
            return False

    monkeypatch.setattr(web, "ZWAAR", Vol())
    s, r = Browser(server).vraag("/api/web/aos8/plan", {"clusters": []})
    assert s == 503 and "druk" in r["fout"]


def test_privacy_zonder_sessie_en_tijdens_pilot(srv, monkeypatch):
    server, _ = srv
    monkeypatch.setattr(web, "PILOTCODE", "geheim-123")
    b = Browser(server, pagina=False)
    s, html = b.ruw("/privacy", headers={"Cookie": "cnx_taal=en"})
    assert s == 200 and b"Privacy statement" in html and b"cnx_sessie" in html
    s, html = b.ruw("/privacy", headers={"Cookie": "cnx_taal=nl"})
    assert s == 200 and b"Privacyverklaring" in html
    s, html = b.ruw("/")                                         # de pilotpagina linkt naar de verklaring
    assert b'href="/privacy"' in html
    monkeypatch.setattr(web, "PILOTCODE", "")
    s, html = Browser(server, pagina=False).ruw("/")             # en de voettekst van de app
    assert b'href="/privacy"' in html

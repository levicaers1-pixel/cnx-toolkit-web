"""Servermodus (cnx web --server): toegelaten hosts, sessie en CSRF-token per browser, time-out, limieten, logs zonder
gegevens, veiligheidskoppen en enkel URL's van Central bij het aanmelden."""
import json
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
    assert b.vraag("/api/status") == (200, {"aangemeld": False, "base": "", "env": False})


def test_csrf_token_per_sessie(srv):
    server, _ = srv
    a, b = Browser(server), Browser(server)
    assert a.token != b.token and a.token != web.ov.TOKEN
    assert a.ruw("/api/status", token=b.token)[0] == 403           # token van een ander
    assert a.ruw("/api/status", token=web.ov.TOKEN)[0] == 403      # het vaste token van de lokale app
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
    b = Browser(server)
    s, r = b.vraag("/api/web/aos8/gereedheid", {"bestanden": [{"naam": "x.txt", "inhoud": "A" * 2000}]})
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

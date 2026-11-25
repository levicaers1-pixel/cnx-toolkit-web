"""Vertaling NL/EN: geen tekst zonder Engelse versie, dezelfde invulplaatsen, en de taal komt goed door (cookie,
Accept-Language, achtergrondtaken, rapport en migratieplan)."""
import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))
import i18n_server  # noqa: E402
import i18n_web  # noqa: E402
from cnx_api import aos8, migratieplan, taal, web  # noqa: E402
from test_aos8 import AP_KOP, APS, CTRL_KOP, CTRLS, bestand, xlsx  # noqa: E402
from test_sessies import Browser  # noqa: E402
from test_web import server  # noqa: E402,F401

DATA = os.path.join(os.path.dirname(__file__), "..", "src", "cnx_api", "data")


def _lees(naam):
    return json.load(open(os.path.join(DATA, naam), encoding="utf-8"))


def test_geen_webtekst_zonder_vertaling():
    assert i18n_web.ontbrekend() == {}, "tekst in web.html zonder Engelse versie in en-web.json"


def test_geen_servertekst_zonder_vertaling():
    assert i18n_server.ontbrekend() == {}, "_()-tekst zonder Engelse versie in en-server.json"


def test_zelfde_invulplaatsen():
    plaats = lambda t: sorted(re.findall(r"(?<!\{)\{(\w+)\}(?!\})", t))  # noqa: E731
    for k, v in _lees("en-server.json").items():
        assert plaats(k) == plaats(v), k
    for k, v in _lees("en-web.json").items():
        assert sorted(re.findall(r"\{\d\}", k)) == sorted(re.findall(r"\{\d\}", v)), k
        assert k.startswith(" ") == v.startswith(" ") or not v, f"spatie vooraan: {k!r}"
        assert k.endswith(" ") == v.endswith(" ") or not v, f"spatie achteraan: {k!r}"


def test_taalkeuze():
    assert taal.kies("en", "nl-BE,nl") == "en"
    assert taal.kies(None, "nl-BE,nl;q=0.9,en;q=0.8") == "nl"
    assert taal.kies(None, "en-GB,en") == "en"
    assert taal.kies(None, "fr-BE,fr") == "en"           # een andere taal: Engels
    assert taal.kies("xx", "") == "nl"


def _inventaris():
    return aos8.analyseer([bestand("inv.xlsx", xlsx({"AP Inventory": [AP_KOP] + APS, "Controllers": [CTRL_KOP] + CTRLS}))], "Klant")


def test_rapport_en_plan_in_het_engels():
    taal.zet("en")
    try:
        res = _inventaris()
        assert "<html lang='en'>" in res["rapport"] and "AOS-10 readiness" in res["rapport"] and "Gereedheid" not in res["rapport"]
        plan = migratieplan.maak_plan(res, ["CTRL-B"])
        assert [f["fase"] for f in plan["clusters"][0]["fasen"]] == ["Prepare", "Convert the gateway", "Convert APs", "Finish"]
        h = migratieplan.plan_html(plan)
        assert "Migration plan AOS-8 to AOS-10" in h and "Voorbereiden" not in h
        assert any("200 series" in m["opmerking"] for m in res["modellen"])
        assert res["modellen"][0]["aos10_label"] in aos8.STATUS_LABEL.values()     # labels blijven sleutels
    finally:
        taal.zet("nl")
    res = _inventaris()
    assert "AOS-10 gereedheid" in res["rapport"]                                    # standaard Nederlands


def test_pagina_en_api_volgen_de_cookie(server):
    b = Browser(server, pagina=False)
    s, html = b.ruw("/", headers={"Cookie": "cnx_taal=en"})
    assert s == 200 and b'<html lang="en">' in html and b'"Onboarden": "Onboarding"' in html
    s, html = b.ruw("/", headers={"Accept-Language": "nl-BE,nl;q=0.9"})
    assert b'<html lang="nl">' in html
    tok = web.TOKEN
    s, r = b.ruw("/api/web/aos8/plan", {"clusters": ["x"]}, token=tok, headers={"Cookie": "cnx_taal=en"})
    assert s == 400 and json.loads(r)["fout"] == "Read in this customer's inventory first."
    s, r = b.ruw("/api/web/aos8/plan", {"clusters": ["x"]}, token=tok, headers={"Cookie": "cnx_taal=nl"})
    assert json.loads(r)["fout"] == "Lees eerst de inventaris van deze klant in."


def test_achtergrondtaak_in_de_taal_van_wie_ze_startte(monkeypatch):
    class S:
        ophalingen, wisplannen = {}, {}
        verbinding = web.cx.Verbinding()
    monkeypatch.setattr(web.configapi, "afwijkingen_scan", lambda *a: (_ for _ in ()).throw(web.monitor.ApiFout(500, "x")))
    taal.zet("en")
    try:
        o = web.start_ophaling(S, "afwijkingen", {})
    finally:
        taal.zet("nl")
    for _ in range(100):
        if o.status != "bezig":
            break
        time.sleep(0.02)
    assert o.fout == "Central returned 500: x"


def test_pilotpagina_in_het_engels(monkeypatch):
    taal.zet("en")
    try:
        h = web.pilot_pagina("tok")
    finally:
        taal.zet("nl")
    assert 'lang="en"' in h and "closed pilot" in h and "Continue" in h


def test_handleiding_in_de_gekozen_taal(server):
    b = Browser(server, pagina=False)
    s, html = b.ruw("/hulp", headers={"Cookie": "cnx_taal=en"})
    assert s == 200 and b'lang="en"' in html and b"<strong>Manual</strong>" in html and b'id="onboarding"' in html
    s, html = b.ruw("/hulp", headers={"Cookie": "cnx_taal=nl"})
    assert b'lang="nl"' in html and b"<strong>Handleiding</strong>" in html and b'id="onboarden"' in html
    assert b'href="docs/' not in html and b'href="SECURITY.md' not in html      # links naar de repo gaan naar GitHub

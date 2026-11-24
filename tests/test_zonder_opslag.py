"""Zonder opslag (servermodus): de webapp schrijft niets op schijf. Importbestanden, logboeken en de AP-migratie gaan
enkel naar de browser."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import nep_central  # noqa: E402
from cnx_api import alias_api as cx, web  # noqa: E402
from test_aos8 import AP_KOP, APS, CTRL_KOP, CTRLS, bestand, xlsx  # noqa: E402
from test_web import vraag  # noqa: E402


@pytest.fixture
def leeg(tmp_path, monkeypatch):
    """Server zonder opslag. Elke poging om een bestand te schrijven doet de test falen."""
    werkmap = tmp_path / "cnx-web"
    monkeypatch.setattr(web, "WERKMAP", str(werkmap))
    monkeypatch.setattr(web, "OPSLAG", False)
    monkeypatch.chdir(tmp_path)
    srv = web.maak_server(0)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    echt_open = open
    geschreven = []

    def bewaakt_open(pad, mode="r", *a, **k):
        if any(m in mode for m in "wax+"):
            geschreven.append(str(pad))
        return echt_open(pad, mode, *a, **k)

    monkeypatch.setattr("builtins.open", bewaakt_open)
    yield f"http://127.0.0.1:{srv.server_address[1]}", geschreven
    srv.shutdown()
    srv.server_close()
    assert not werkmap.exists()
    assert list(tmp_path.iterdir()) == []


def j(antwoord):
    return json.loads(antwoord[1])


def test_onboarding_bestand_enkel_naar_de_browser(leeg, monkeypatch):
    server, geschreven = leeg
    monkeypatch.setattr(cx, "api", nep_central.api)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    rijen = j(vraag(server + "/api/web/ov/groepswitches?groep=ACCESS"))["rijen"]
    r = j(vraag(server + "/api/web/onboard/bestand", {"groep": "ACCESS", "rijen": rijen}))
    assert r["bestanden"] and all(b["pad"] is None and b["inhoud"].startswith("#ALIAS_IPV4_ADDRESS_TYPE") for b in r["bestanden"])
    assert geschreven == []


def test_wissen_geeft_het_logboek_aan_de_browser(leeg, monkeypatch):
    server, geschreven = leeg
    monkeypatch.setattr(cx, "api", nep_central.api)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    monkeypatch.setattr(web.configapi, "wis_uitvoeren", lambda acties, df, v: [{"naam": "SW1", "resultaat": "gewist"}])
    web.LOKAAL.wisplannen["wis-x"] = ([{"x": 1}], "ACCESS_SWITCH")
    oid = j(vraag(server + "/api/web/ov/ophaal", {"soort": "wissen", "opties": {"plan": "wis-x"}}))["id"]
    for _ in range(200):
        info = j(vraag(server + "/api/web/ov/ophaling?id=" + oid))
        if info["status"] != "bezig":
            break
    assert info["status"] == "klaar" and info["resultaat"]["logboek"] is None
    assert info["resultaat"]["resultaten"] == [{"naam": "SW1", "resultaat": "gewist"}] and info["resultaat"]["versie"]
    assert geschreven == []


def test_aos8_en_plan_zonder_opslag(leeg):
    server, geschreven = leeg
    data = xlsx({"AP Inventory": [AP_KOP] + APS, "Controllers": [CTRL_KOP] + CTRLS})
    inv = j(vraag(server + "/api/web/aos8/gereedheid", {"bestanden": [bestand("inv.xlsx", data)], "klant": "Klant X"}))
    del inv["rapport"]
    plan = j(vraag(server + "/api/web/aos8/plan", {"inventaris": inv, "voortgang": {}, "clusters": ["CTRL-B"]}))
    assert plan["clusters"][0]["naam"] == "CTRL-B"
    assert geschreven == []


def test_klantconfig_en_instellingen_niet_beschikbaar(leeg):
    server, geschreven = leeg
    assert vraag(server + "/api/web/klantconfig")[0] == 404
    assert vraag(server + "/api/web/klantconfig", {"klant": "x"})[0] == 404
    assert vraag(server + "/api/web/klantconfig/voorstel", {"bestand": {}})[0] == 404
    s, b = vraag(server + "/", token=False)
    assert s == 200 and b"const OPSLAG = false;" in b
    assert geschreven == []

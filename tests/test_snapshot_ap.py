"""Voor/na-snapshot en het afwerken van APs na de migratie, tegen de nagemaakte Central."""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import nep_central  # noqa: E402
from cnx_api import alias_api as cx  # noqa: E402
from cnx_api import apafwerking, snapshot  # noqa: E402
from test_configapi import central, ophalen  # noqa: E402,F401
from test_web import server, vraag  # noqa: E402,F401


@pytest.fixture
def met_aps(monkeypatch):
    monkeypatch.setattr(nep_central, "MET_APS", True)
    monkeypatch.setattr(nep_central, "APS", copy.deepcopy(nep_central.APS))
    monkeypatch.setattr(nep_central, "HOSTNAMES", {})
    monkeypatch.setattr(nep_central, "POORT_WIJZIGING", {})


def test_snapshot_leest_toestellen_poorten_en_tellingen(central, met_aps):
    s = snapshot.maak("", "2026-11-26T10:00:00")
    assert s["soort"] == "cnx-snapshot" and s["tijd"] == "2026-11-26T10:00:00"
    assert {d["serial"] for d in s["toestellen"]} >= {"SG00TEST01", "CNAP0001"}
    assert set(s["poorten"]) == {"SG00TEST01", "SG00TEST03"}          # enkel online switches
    assert s["clients"]["per_ssid"] == {"CORP": 6} and s["clients"]["bedraad"] == 1
    assert "11:11:11:11:11:01" not in json.dumps(s)                  # geen clientgegevens, enkel tellingen


def test_snapshot_met_site_filtert(central, met_aps):
    snapshot.maak("SITE01")
    f = [p for m, pad, p, b in central if pad.endswith("/devices")][0]
    assert f["filter"] == "siteName eq 'SITE01'"
    with pytest.raises(snapshot.Invoer):
        snapshot.maak("x' or 1 eq 1")


def test_vergelijk_vindt_wat_wegviel(central, met_aps, monkeypatch):
    voor = snapshot.maak()
    nep_central.POORT_WIJZIGING[("SG00TEST01", "1/1/1")] = {"operStatus": "Down", "status": "Down", "neighbour": ""}
    nep_central.POORT_WIJZIGING[("SG00TEST01", "1/1/49")] = {"neighbour": "CORE-02"}
    nep_central.APS[0]["status"] = "OFFLINE"
    monkeypatch.setattr(nep_central, "CLIENTS", nep_central.CLIENTS[-1:])
    na = snapshot.maak()
    r = snapshot.vergelijk(voor, na)
    tekst = [(x["ernst"], x["soort"], x["wat"], x["detail"]) for x in r["rijen"]]
    assert ("bad", "Toestel", "aa:bb:cc:00:00:01", "ONLINE naar OFFLINE") in tekst
    assert any(e == "bad" and w == "SITE01-SW01 1/1/1" and d.startswith("up naar Down") for e, s, w, d in tekst)
    assert any(e == "warn" and w == "SITE01-SW01 1/1/49" and "CORE-02" in d for e, s, w, d in tekst)
    assert ("bad", "Clients", "CORP", "6 naar 0 clients") in tekst
    assert r["ernst"]["bad"] >= 3 and r["voor"]["clients"] == 7 and r["na"]["clients"] == 1
    assert snapshot.vergelijk(voor, voor)["rijen"] == []


def test_vergelijk_weigert_iets_anders():
    with pytest.raises(ValueError):
        snapshot.vergelijk({"soort": "iets"}, {})


def test_snapshot_via_de_server(server, central, met_aps):
    info = ophalen(server, "snapshot", {"site": ""})
    assert info["status"] == "klaar", info
    s = info["resultaat"]
    st, b = vraag(server + "/api/web/snapshot/vergelijk", {"voor": s, "na": s})
    assert st == 200 and json.loads(b)["rijen"] == []
    assert vraag(server + "/api/web/snapshot/vergelijk", {"voor": {}, "na": s})[0] == 400


AOS8 = [{"naam": "GEB1-AP01", "serial": "CNAP0001", "mac": "AA:BB:CC:00:00:01", "groep": "GEB1"},
        {"naam": "GEB1-AP02", "serial": "", "mac": "aa-bb-cc-00-00-02", "groep": "GEB1"},
        {"naam": "GEB2-AP01", "serial": "ONBEKEND1", "mac": "", "groep": "GEB2"}]


def test_plan_koppelt_op_serial_en_mac(central, met_aps):
    p = apafwerking.plan(AOS8, {"GEB1": {"site": "SITE02", "groep": "WIRELESS"}})
    assert [x["naam"] for x in p["niet_gevonden"]] == ["GEB2-AP01"]
    a = {x["serial"]: x for x in p["acties"]}
    assert a["CNAP0001"]["naam"] == "GEB1-AP01" and a["CNAP0001"]["site_id"] == "1002" and a["CNAP0001"]["dg_id"] == "g12"
    assert a["CNAP0002"]["naam"] == "GEB1-AP02" and a["CNAP0002"]["site"] == "SITE02" and a["CNAP0002"]["dg"] == ""   # al in WIRELESS
    assert not any(m == "POST" for m, *_ in central)                 # een plan wijzigt niets


def test_plan_weigert_slechte_namen_en_onbekende_scopes(central, met_aps):
    aps = [dict(AOS8[0], naam="GEB1 AP01"), dict(AOS8[1], naam="OUD-AP-2")]
    p = apafwerking.plan(aps, {"GEB1": {"site": "BESTAAT-NIET", "groep": ""}})
    assert any("GEB1 AP01" in g for g in p["geweigerd"]) and any("BESTAAT-NIET" in g for g in p["geweigerd"])
    assert p["acties"] == [] and p["gelijk"] == 2
    p = apafwerking.plan([AOS8[0], dict(AOS8[1], naam="GEB1-AP01")], {})
    assert sum("meer dan eens" in g for g in p["geweigerd"]) == 2


def test_uitvoeren_wijst_toe_en_hernoemt(central, met_aps):
    p = apafwerking.plan(AOS8, {"GEB1": {"site": "SITE02", "groep": "WIRELESS"}})
    res = {x["serial"]: x for x in apafwerking.uitvoeren(p["acties"])}
    assert res["CNAP0001"]["site_uit"] == "ok" and res["CNAP0001"]["dg_uit"] == "ok" and res["CNAP0001"]["naam_uit"] == "ok"
    assert nep_central.HOSTNAMES == {"a1": "GEB1-AP01", "a2": "GEB1-AP02"}
    assert {a["siteName"] for a in nep_central.APS} == {"SITE02"}
    posts = [(pad, b) for m, pad, prm, b in central if m == "POST" and "add-devices" in pad]
    assert ("/network-config/v1/site-add-devices", {"desScopeId": "1002", "devices": ["CNAP0001", "CNAP0002"]}) in posts
    # nog eens: het profiel bestaat nu, de toolkit werkt het bij (PATCH)
    p2 = apafwerking.plan([dict(AOS8[0], naam="GEB1-AP09")], {})
    assert apafwerking.uitvoeren(p2["acties"])[0]["naam_uit"] == "ok" and nep_central.HOSTNAMES["a1"] == "GEB1-AP09"


def test_ap_plan_en_uitvoeren_via_de_server(server, central, met_aps):
    info = ophalen(server, "applan", {"aps": AOS8, "koppeling": {"GEB1": {"site": "SITE02"}}, "hernoemen": False})
    assert info["status"] == "klaar", info
    plan = info["resultaat"]
    assert all(not a["naam"] for a in plan["acties"]) and len(plan["acties"]) == 2
    info = ophalen(server, "apuitvoeren", {"plan": plan["id"]})
    assert info["status"] == "klaar" and all(r["site_uit"] == "ok" for r in info["resultaat"]["resultaten"])
    assert vraag(server + "/api/web/ov/ophaal", {"soort": "apuitvoeren", "opties": {"plan": plan["id"]}})[0] == 400   # maar een keer

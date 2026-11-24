"""Alias-overzicht, gereedheid voor migratie en snapshots (cnx web), tegen de nagemaakte Central."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import nep_central  # noqa: E402
from cnx_api import alias_api as cx  # noqa: E402
from cnx_api import configapi, web  # noqa: E402
from test_web import server, vraag  # noqa: E402,F401


@pytest.fixture
def central(monkeypatch, tmp_path):
    nep_central.AANROEPEN.clear()
    monkeypatch.setattr(cx, "api", nep_central.api)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    return nep_central.AANROEPEN


def ophalen(server, soort, opties):
    s, b = vraag(server + "/api/web/ov/ophaal", {"soort": soort, "opties": opties})
    assert s == 200, b
    oid = json.loads(b)["id"]
    for _ in range(100):
        info = json.loads(vraag(server + "/api/web/ov/ophaling?id=" + oid)[1])
        if info["status"] != "bezig":
            return info
        time.sleep(0.05)
    raise AssertionError("ophaling blijft bezig")


def test_ongeldige_opties(server, central):
    assert vraag(server + "/api/web/ov/ophaal", {"soort": "wissen", "opties": {"plan": "bestaat-niet"}})[0] == 400
    assert vraag(server + "/api/web/ov/ophaal", {"soort": "schrijf", "opties": {}})[0] == 400


def test_afwijkingen_per_switch(server, central):
    r = json.loads(vraag(server + "/api/web/sw/afwijkingen?serial=SG00TEST01")[1])
    assert r["switch"]["naam"] == "SITE01-SW01" and r["switch"]["groep"] == "ACCESS"
    per = {(x["profiel"], x["object"], x["veld"]): x for x in r["rijen"]}
    v10 = per[("VLAN's", "10", "name")]
    assert v10["status"] == "verschilt" and v10["lokaal"] == "DATA-OUD" and v10["geerfd"] == "DATA" and v10["van"] == "Device group ACCESS"
    assert per[("VLAN's", "999", "")]["status"] == "enkel lokaal"
    assert per[("VLAN's", "120", "")]["status"] == "gelijk"
    assert per[("Aliassen", "sys_vlan_ipv4_120", "")]["status"] == "per switch"
    besch = next(x for x in r["rijen"] if x["object"] == "sys_vlan_120_description")
    assert besch["status"] == "verschilt" and besch["veld"] == "description" and besch["lokaal"] == "Beheer-oud" and besch["geerfd"] == "Beheer" and besch["van"] == "Site SITE01"
    assert any(f.startswith("SNMP") for f in r["fouten"])
    lokaal = [c for c in central if c[1].endswith("/layer2-vlan") and c[2].get("scope-id") == "d1"]
    # zelfde aanvraag als het oude overrides-scherm: view-type LOCAL, scope-id en de eigen device function
    assert lokaal and all(c[2] == {"view-type": "LOCAL", "scope-id": "d1", "device-function": "ACCESS_SWITCH"} for c in lokaal)
    assert r["switch"]["functie"] == "ACCESS_SWITCH"
    diag = {d["profiel"]: d for d in r["diagnose"]}
    assert diag["VLAN's"]["aantal"] == 3 and diag["VLAN's"]["antwoord"] == "200"
    assert diag["VLAN's"]["params"] == "view-type=LOCAL&scope-id=d1&device-function=ACCESS_SWITCH"
    assert diag["SNMP"]["antwoord"].startswith("500")
    assert not [c for c in central if c[0] != "GET"]
    # switch zonder device function: gelezen als ACCESS_SWITCH, met een melding
    r2 = json.loads(vraag(server + "/api/web/sw/afwijkingen?serial=SG00TEST02")[1])
    assert r2["switch"]["functie"] == "ACCESS_SWITCH" and any("geen device function" in f for f in r2["fouten"])
    assert r2["diagnose"] and all(d["aantal"] == 0 for d in r2["diagnose"] if d["profiel"] == "VLAN's")
    assert vraag(server + "/api/web/sw/afwijkingen?serial=ONBEKEND9")[0] == 400


def test_afwijkingen_scan_alle_switches(server, central):
    res = ophalen(server, "afwijkingen", {})["resultaat"]
    assert res["switches"] == 3
    assert {x["naam"] for x in res["rijen"] if x["status"] == "verschilt"} == {"SITE01-SW01"}
    n_global = len([c for c in central if c[1].endswith("/layer2-vlan") and c[2].get("scope-id") == "g1"])
    assert n_global == 1                                                    # hogere scopes een keer gelezen (cache)
    gekozen = ophalen(server, "afwijkingen", {"serials": ["SG00TEST02"]})["resultaat"]
    assert gekozen["switches"] == 1 and {x["serial"] for x in gekozen["rijen"]} <= {"SG00TEST02"}


def test_overbodige_overrides_wissen(server, central, monkeypatch, tmp_path):
    monkeypatch.setattr(nep_central, "GEWIST", set())
    monkeypatch.setattr(web, "WERKMAP", str(tmp_path))
    voor = json.loads(vraag(server + "/api/web/sw/afwijkingen?serial=SG00TEST01")[1])
    status = {(x["profiel"], x["object"]): x["status"] for x in voor["rijen"]}
    assert status[("VLAN's", "120")] == "gelijk" and status[("VLAN's", "10")] == "verschilt"
    items = [{"serial": "SG00TEST01", "profiel": "VLAN's", "object": "120"},          # gelijk: mag weg
             {"serial": "SG00TEST01", "profiel": "VLAN's", "object": "10"},           # verschilt: geweigerd
             {"serial": "SG00TEST01", "profiel": "VLAN's", "object": "999"},          # enkel lokaal: geweigerd
             {"serial": "SG00TEST01", "profiel": "Firmwarebeleid", "object": "standaard"},
             {"serial": "SG00TEST01", "profiel": "Systeeminfo (hostname)", "object": "campus-access-sys"}]   # gelijk, maar nooit wissen
    central.clear()
    plan = ophalen(server, "wisplan", {"items": items})["resultaat"]
    assert not [c for c in central if c[0] != "GET"]                                  # een plan wist niets
    assert [(a["profiel"], a["object"]) for a in plan["acties"]] == [("VLAN's", "120")]
    assert len(plan["geweigerd"]) == 4 and any("verschilt" in g for g in plan["geweigerd"]) and any("enkel lokaal" in g for g in plan["geweigerd"])
    res = ophalen(server, "wissen", {"plan": plan["id"]})["resultaat"]["resultaten"]
    assert [(r["object"], r["resultaat"]) for r in res] == [("120", "gewist")]
    deletes = [c for c in central if c[0] == "DELETE"]
    assert len(deletes) == 1 and deletes[0][1].endswith("/layer2-vlan/120") and deletes[0][2] == {"object-type": "LOCAL", "scope-id": "d1", "device-function": "ACCESS_SWITCH"}
    assert any(n.startswith("overrides-wissen-log-") for n in os.listdir(tmp_path))
    na = json.loads(vraag(server + "/api/web/sw/afwijkingen?serial=SG00TEST01")[1])
    assert ("VLAN's", "120") not in {(x["profiel"], x["object"]) for x in na["rijen"]}
    assert vraag(server + "/api/web/ov/ophaal", {"soort": "wissen", "opties": {"plan": plan["id"]}})[0] == 400


def test_wissen_weigert_onbekend_profiel(monkeypatch):
    aanroepen = []
    monkeypatch.setattr(cx, "api", lambda *a, **k: aanroepen.append(a) or nep_central.Antwoord(200, {}))
    res = configapi.wis_uitvoeren([{"naam": "x", "serial": "S1", "scope": "d1", "profiel": "Iets", "object": "a"}])
    assert res[0]["resultaat"].startswith("fout") and aanroepen == []


def test_overrides_wissen_verschilt_en_enkel_lokaal(server, central, monkeypatch, tmp_path):
    monkeypatch.setattr(nep_central, "GEWIST", set())
    monkeypatch.setattr(web, "WERKMAP", str(tmp_path))
    items = [{"serial": "SG00TEST01", "profiel": "VLAN's", "object": "10", "status": "verschilt"},
             {"serial": "SG00TEST01", "profiel": "VLAN's", "object": "999", "status": "enkel lokaal"},
             {"serial": "SG00TEST01", "profiel": "VLAN's", "object": "120", "status": "verschilt"},      # is gelijk: geweigerd
             {"serial": "SG00TEST01", "profiel": "Aliassen", "object": "sys_vlan_ipv4_120", "status": "per switch"},
             {"serial": "SG00TEST01", "profiel": "Beheerinterface", "object": "mgmt", "status": "gelijk"}]
    central.clear()
    plan = ophalen(server, "wisplan", {"items": items})["resultaat"]
    assert not [c for c in central if c[0] != "GET"]
    acties = {a["object"]: a for a in plan["acties"]}
    assert set(acties) == {"10", "999"}
    assert acties["10"]["status"] == "verschilt" and "neemt de waarde van Device group ACCESS over" in acties["10"]["gevolg"]
    assert acties["10"]["velden"] == ["name: DATA-OUD -> DATA"]
    assert acties["999"]["status"] == "enkel lokaal" and "verdwijnt" in acties["999"]["gevolg"]
    assert len(plan["geweigerd"]) == 3 and any("is niet (meer) verschilt (gelijk)" in g for g in plan["geweigerd"])
    res = ophalen(server, "wissen", {"plan": plan["id"]})["resultaat"]["resultaten"]
    assert sorted((r["object"], r["resultaat"]) for r in res) == [("10", "gewist"), ("999", "gewist")]
    assert {r["object"]: r["status"] for r in res} == {"10": "verschilt", "999": "enkel lokaal"} and all(r["code"] == 200 for r in res)
    na = json.loads(vraag(server + "/api/web/sw/afwijkingen?serial=SG00TEST01")[1])
    over = {x["object"] for x in na["rijen"] if x["profiel"] == "VLAN's"}
    assert "10" not in over and "999" not in over and "120" in over

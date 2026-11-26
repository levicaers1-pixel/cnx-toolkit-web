"""GreenLake Onboarding tegen een nagemaakte GreenLake en Central."""
import base64
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import nep_central  # noqa: E402
import nep_greenlake  # noqa: E402
from cnx_api import alias_api as cx  # noqa: E402
from cnx_api import glponboard, web  # noqa: E402
from test_configapi import central, ophalen  # noqa: E402,F401
from test_web import _Antwoord, server, vraag  # noqa: E402,F401

LIJST = ("serial;mac;soort;site;device group;device function;subscription\n"
         "SGNIEUW01;AA:BB:CC:11:22:01;switch;SITE02;ACCESS;Access Switch;\n"
         "CNAP0002;aa:bb:cc:00:00:02;AP;SITE02;WIRELESS;;\n"
         "FOUT00001;aa:bb:cc:11:22:09;AP;;;;\n")


@pytest.fixture
def greenlake(monkeypatch, central):
    staat = nep_greenlake.nieuw()
    monkeypatch.setattr(nep_greenlake, "STAAT", staat)
    monkeypatch.setattr(glponboard, "_verzend", nep_greenlake.verzend)
    monkeypatch.setattr(glponboard, "slaap", lambda s: None)
    monkeypatch.setattr(glponboard, "WACHT_CENTRAL", 0)
    monkeypatch.setattr(cx.requests, "post", lambda *a, **k: _Antwoord(200, {"access_token": "glp-token"}))
    monkeypatch.setattr(nep_central, "SWITCHES", copy.deepcopy(nep_central.SWITCHES))
    monkeypatch.setattr(nep_central, "APS", copy.deepcopy(nep_central.APS))
    monkeypatch.setattr(nep_central, "MET_APS", False)

    def in_central(d):                       # na het toevoegen verschijnt het toestel ook in Central
        if d["serialNumber"].startswith("SG"):
            nep_central.SWITCHES.append({"id": d["serialNumber"], "serialNumber": d["serialNumber"], "macAddress": d["macAddress"],
                                         "deviceName": d["serialNumber"], "siteName": "", "deviceGroupName": "", "deviceFunction": "",
                                         "scopeId": "dn", "status": "OFFLINE", "model": "6200F"})
    staat["na_toevoegen"].append(in_central)
    v = cx.Verbinding(glponboard.GLP)
    ok, melding = glponboard.aanmelden(v, "cid", "geheim")
    assert ok, melding
    return v, staat


def test_lees_csv_xlsx_en_fouten():
    r = glponboard.lees(tekst=LIJST)
    assert [x["serial"] for x in r["rijen"]] == ["SGNIEUW01", "CNAP0002", "FOUT00001"]
    assert r["rijen"][0]["functie"] == "ACCESS_SWITCH" and r["rijen"][0]["mac"] == "aa:bb:cc:11:22:01"
    assert r["rijen"][1]["functie"] == "CAMPUS_AP"
    r = glponboard.lees(tekst="Serial\tMAC\tType\nX1\tnee\trouter\nX1\taabbccddeeff\tAP\n")
    f = r["rijen"][0]["fouten"]
    assert any("MAC" in x for x in f) and any("router" in x for x in f)
    assert any("rij 1" in x for x in r["rijen"][1]["fouten"])        # dubbel serienummer
    with pytest.raises(glponboard.Invoer):
        glponboard.lees(tekst="naam;ip\na;b\n")
    with pytest.raises(glponboard.Invoer):
        glponboard.lees(bestand={"naam": "x.xlsx", "inhoud": base64.b64encode(b"geen zip").decode()})


def test_keuzes(greenlake):
    v, _staat = greenlake
    k = glponboard.keuzes(v)
    assert k["applicaties"][0] == {"id": nep_greenlake.SM_CENTRAL, "naam": "HPE Aruba Networking Central", "regio": "eu-central"}
    assert {s["key"]: s["vrij"] for s in k["subscriptions"]} == {"KEYAP": 4, "KEYSW": 1}


def _plan(v, proef_keuze=None):
    rijen = glponboard.lees(tekst=LIJST)["rijen"]
    keuze = proef_keuze or {"applicatie": nep_greenlake.SM_CENTRAL + "|eu-central", "subscriptions": {"AP": "sub-ap", "SWITCH": "sub-sw"}}
    return glponboard.plan(v, rijen, keuze, True)


def test_plan_leest_enkel(greenlake):
    v, staat = greenlake
    p = _plan(v)
    a = {x["serial"]: x for x in p["acties"]}
    assert a["SGNIEUW01"]["toevoegen"] and a["SGNIEUW01"]["functie"] == "ACCESS_SWITCH" and a["SGNIEUW01"]["sub_id"] == "sub-sw"
    assert not a["CNAP0002"]["toevoegen"] and a["CNAP0002"]["app_id"] == nep_greenlake.SM_CENTRAL and a["CNAP0002"]["site"] == "SITE02"
    assert a["CNAP0002"]["functie"] == ""                       # APs krijgen hun functie vanzelf
    assert p["in_glp"] == 1 and p["geweigerd"] == []
    assert all(m == "GET" for m, *_ in staat["aanroepen"])


def test_plan_te_weinig_licenties_en_ander_mac(greenlake):
    v, staat = greenlake
    staat["subs"][1]["availableQuantity"] = "0"
    staat["devices"]["CNAP0002"]["macAddress"] = "aa:bb:cc:99:99:99"
    p = _plan(v)
    assert any("KEYSW" in g and "0 vrij" in g for g in p["geweigerd"])
    assert any("CNAP0002" in g and "MAC" in g for g in p["geweigerd"])


def test_proef_wijzigt_niets(greenlake):
    v, staat = greenlake
    res = {r["serial"]: r for r in glponboard.uitvoeren(v, _plan(v)["acties"], proef=True)}
    assert res["SGNIEUW01"]["toevoegen_uit"] == "ok" and res["FOUT00001"]["toevoegen_uit"].startswith("fout: Device not found")
    assert res["SGNIEUW01"]["app_uit"] == "proef: kan pas na het toevoegen" and res["CNAP0002"]["app_uit"] == "ok"
    assert res["SGNIEUW01"]["site_uit"] == "proef: niet gedaan in Central"
    assert all(p.get("dry-run") == "true" for m, pad, p, *_ in staat["aanroepen"] if m in ("POST", "PATCH"))
    assert set(staat["devices"]) == {"CNAP0002"} and staat["devices"]["CNAP0002"]["application"] is None
    assert not any(m == "POST" for m, *_ in central_aanroepen())


def central_aanroepen():
    return nep_central.AANROEPEN


def test_echt_uitvoeren(greenlake):
    v, staat = greenlake
    res = {r["serial"]: r for r in glponboard.uitvoeren(v, _plan(v)["acties"], proef=False)}
    sw, ap = res["SGNIEUW01"], res["CNAP0002"]
    assert (sw["toevoegen_uit"], sw["app_uit"], sw["sub_uit"]) == ("ok", "ok", "ok")
    assert staat["devices"]["SGNIEUW01"]["application"] == {"id": nep_greenlake.SM_CENTRAL}
    assert staat["devices"]["SGNIEUW01"]["subscription"] == [{"id": "sub-sw"}] and staat["devices"]["CNAP0002"]["subscription"] == [{"id": "sub-ap"}]
    patches = [b for m, pad, p, b, k in staat["aanroepen"] if m == "PATCH"]
    assert all(len(b) == 2 and "application" in b or list(b) == ["subscription"] for b in patches)
    assert (sw["site_uit"], sw["dg_uit"], sw["functie_uit"]) == ("ok", "ok", "ok")
    nieuw = next(s for s in nep_central.SWITCHES if s["serialNumber"] == "SGNIEUW01")
    assert nieuw["siteName"] == "SITE02" and nieuw["deviceFunction"] == "ACCESS_SWITCH"
    assert ap["site_uit"].startswith("niet gedaan")              # de AP staat (nog) niet in deze Central
    assert res["FOUT00001"]["toevoegen_uit"].startswith("fout") and res["FOUT00001"]["sub_uit"] == "niet gedaan: toevoegen mislukte"


def test_via_de_server(server, greenlake, monkeypatch):
    monkeypatch.setattr(web.LOKAAL, "glp", greenlake[0])
    st, b = vraag(server + "/api/web/glp/lees", {"tekst": LIJST})
    rijen = json.loads(b)["rijen"]
    assert st == 200 and len(rijen) == 3
    st, b = vraag(server + "/api/web/glp/keuzes", {})
    assert st == 200 and json.loads(b)["applicaties"]
    assert json.loads(vraag(server + "/api/status")[1])["glp"] is True
    info = ophalen(server, "glpplan", {"rijen": rijen, "keuze": {"applicatie": nep_greenlake.SM_CENTRAL + "|eu-central", "subscriptions": {"AP": "sub-ap"}}})
    assert info["status"] == "klaar", info
    pid = info["resultaat"]["id"]
    info = ophalen(server, "glpuitvoeren", {"plan": pid, "proef": True})
    assert info["status"] == "klaar" and info["resultaat"]["proef"] is True
    info = ophalen(server, "glpuitvoeren", {"plan": pid})           # zonder proef=False blijft het een proef
    assert info["resultaat"]["proef"] is True
    assert vraag(server + "/api/web/glp/afmelden", {})[0] == 200 and not greenlake[0].aangemeld
    assert vraag(server + "/api/web/glp/keuzes", {})[0] == 401


def test_aanmelden_zonder_rechten(monkeypatch):
    monkeypatch.setattr(cx.requests, "post", lambda *a, **k: _Antwoord(200, {"access_token": "t"}))
    monkeypatch.setattr(glponboard, "_verzend", lambda *a: nep_greenlake.Antwoord(403, {"message": "Forbidden"}))
    v = cx.Verbinding()
    ok, melding = glponboard.aanmelden(v, "cid", "x")
    assert not ok and "403" in melding and not v.aangemeld and not v.gegevens


def test_aanmelding_bij_central_delen(greenlake, central):
    v = cx.Verbinding(glponboard.GLP)
    centraal = cx.verbinding()                    # de nagemaakte Central: aangemeld met "Bearer test"
    centraal.gegevens.update(id="cid", secret="geheim")
    assert glponboard.gebruik_central(v, centraal) is True
    assert v.aangemeld and v.gedeeld and v.s.headers["Authorization"] == "Bearer test" and v.gegevens["id"] == "cid"
    with cx.gebruik(v):
        assert glponboard.glp("GET", "/devices/v1/devices").status_code == 200


def test_aanmelding_bij_central_niet_toegelaten(monkeypatch, central):
    monkeypatch.setattr(glponboard, "_verzend", lambda *a: nep_greenlake.Antwoord(403, {"message": "Forbidden"}))
    v = cx.Verbinding(glponboard.GLP)
    assert glponboard.gebruik_central(v, cx.verbinding()) is False and not v.aangemeld
    assert glponboard.gebruik_central(v, cx.Verbinding()) is False          # niet aangemeld bij Central


def test_token_met_workspace(monkeypatch):
    urls = []
    monkeypatch.setattr(cx.requests, "post", lambda url, **k: urls.append(url) or _Antwoord(200, {"access_token": "t"}))
    monkeypatch.setattr(glponboard, "_verzend", lambda *a: nep_greenlake.Antwoord(200, {"items": []}))
    v = cx.Verbinding()
    assert glponboard.aanmelden(v, "cid", "x", "a1b2c3d4-0000-1111")[0]
    assert urls == ["https://global.api.greenlake.hpe.com/authorization/v2/oauth2/a1b2c3d4-0000-1111/token"]
    assert v.gegevens["token_url"] == urls[0]
    cx._token(v, "cid", "x")                       # vernieuwen gebruikt dezelfde URL
    assert urls[-1] == urls[0]
    with pytest.raises(glponboard.Invoer):
        glponboard.aanmelden(v, "cid", "x", "../evil")
    assert glponboard.aanmelden(cx.Verbinding(), "cid", "x")[0] and urls[-1] == cx.TOKEN_URL

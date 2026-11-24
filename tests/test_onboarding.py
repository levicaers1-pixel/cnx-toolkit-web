"""Onboarding: switches van een device group in new Central lezen en het importbestand maken, zonder klantconfig."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import nep_central  # noqa: E402
from cnx_api import alias_api as cx, web  # noqa: E402
from test_web import klantconfig, server, vraag  # noqa: E402,F401


def j(antwoord):
    return json.loads(antwoord[1])


def test_ip_en_vlan_uit_de_alias_van_de_switch(server, monkeypatch):
    monkeypatch.setattr(cx, "api", nep_central.api)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    r = j(vraag(server + "/api/web/ov/groepswitches?groep=ACCESS"))
    sw = r["rijen"][0]
    assert sw["sys_vlan_ip"] == "10.10.120.21/24" and sw["beheer_vlan"] == "120" and sw["bron_ip"] == "alias"
    assert sw["device_function"] == "Access Switch"
    # het profiel dat Central de switch echt geeft (hier van de device group), niet een lokaal profiel uit de lijst
    assert sw["systeemprofiel"] == "ORG_Hostname"
    stack = j(vraag(server + "/api/web/ov/groepswitches?groep=ACCESS_VSF&prefix=22"))["rijen"][0]
    assert stack["bron_ip"] == "monitoring" and stack["sys_vlan_ip"] == "10.20.120.20/22" and stack["beheer_vlan"] == ""
    assert stack["systeemprofiel"] == "sys-system-info-profile"


def test_importbestand_zonder_klantconfig(server, monkeypatch, tmp_path):
    monkeypatch.setattr(web, "WERKMAP", str(tmp_path))
    rijen = [{"serial": "SG00TEST01", "hostname": "SITE02-SW01", "site_collection": "Belgium", "site": "SITE02",
              "device_group": "STAGING", "device_function": "Core Switch", "sys_vlan_ip": "10.10.120.242/22",
              "beheer_vlan": "120", "systeemprofiel": "sys-system-info-profile"},
             {"serial": "SG00TEST02", "hostname": "", "site_collection": "Belgium", "site": "SITE02",
              "device_group": "STAGING", "device_function": "Access Switch", "sys_vlan_ip": "10.10.120.243/22",
              "beheer_vlan": "120", "systeemprofiel": ""}]
    r = j(vraag(server + "/api/web/onboard/bestand", {"groep": "STAGING", "rijen": rijen}))
    assert r["fouten"] == 0 and len(r["bestanden"]) == 1
    b = r["bestanden"][0]
    assert b["switches"] == 2 and os.path.isfile(os.path.join(str(tmp_path), b["pad"]))
    tekst = b["inhoud"]
    assert "#ALIAS_IPV4_ADDRESS_TYPE" in tekst and "#System-info" in tekst
    assert "sys_vlan_ipv4_120,ALIAS_IPV4_ADDRESS_TYPE,Core Switch,Device,Belgium,SITE02,STAGING,SG00TEST01,Yes,10.10.120.242/22" in tekst
    assert "hostname,sys-system-info-profile,Core Switch,Device,Belgium,SITE02,STAGING,SG00TEST01,Yes,SITE02-SW01" in tekst
    assert "SG00TEST02,Yes,10.10.120.243/22" in tekst and tekst.count("hostname,") == 1    # zonder hostname: enkel IP
    # fouten blokkeren het bestand
    slecht = [dict(rijen[0]), dict(rijen[1], sys_vlan_ip="10.10.120.242/22")]               # dubbel IP
    r = j(vraag(server + "/api/web/onboard/bestand", {"groep": "x", "rijen": slecht}))
    assert r["fouten"] >= 1 and not r["bestanden"] and any("keer voor" in x["bevinding"] for x in r["bevindingen"])
    assert vraag(server + "/api/web/onboard/bestand", {"groep": "x", "rijen": []})[0] == 400


def test_switchlijst_voor_overrides(server, monkeypatch):
    monkeypatch.setattr(cx, "api", nep_central.api)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    r = j(vraag(server + "/api/web/sw/overrides-lijst"))
    per = {x["serialNumber"]: x for x in r["items"]}
    assert set(per) == {"SG00TEST01", "SG00TEST02", "SG00TEST03"}
    assert per["SG00TEST01"]["deviceGroupName"] == "ACCESS" and per["SG00TEST01"]["siteName"] == "SITE01" and per["SG00TEST01"]["status"] == "ONLINE"
    assert per["SG00TEST03"]["stack"] is True and per["SG00TEST02"]["deviceGroupName"] == ""


def test_ip_zonder_prefix_krijgt_24(tmp_path):
    from cnx_api import aliassen
    cfg = json.loads(klantconfig(tmp_path).read_text(encoding="utf-8"))
    assert aliassen.met_prefix("10.1.1.10", cfg) == "10.1.1.10/24"
    assert aliassen.met_prefix("10.1.1.10/23", cfg) == "10.1.1.10/23" and aliassen.met_prefix("dhcp", cfg) == "dhcp"
    assert aliassen.met_prefix("10.1.1.10", dict(cfg, standaard_prefix=22)) == "10.1.1.10/22"
    t = {"serial": "SG00TEST09", "hostname": "SW9", "site": "S", "device_group": "G", "sys_vlan_ip": "10.1.1.10", "mgmt_ip": "192.168.1.5", "_regel": 2}
    b = aliassen.controleer([t], cfg, None)
    assert not b.fouten and sum("aangenomen" in x[4] for x in b.lijst) == 2
    waarden = [r[5][0] for r in aliassen.rijen_voor_toestel(t, cfg)]
    assert "10.1.1.10/24" in waarden and "192.168.1.5/24" in waarden


def test_keuzes_uit_central(server, monkeypatch):
    nep_central.AANROEPEN.clear()
    monkeypatch.setattr(cx, "api", nep_central.api)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    k = j(vraag(server + "/api/web/ov/keuzes"))
    assert [x["naam"] for x in k["systeeminfo"]] == ["campus-access-sys", "lab-profiel"]
    assert k["aanbevolen"] == {"systeeminfo": "campus-access-sys", "mgmt": "mgmt", "vlan": 120}
    assert {s["naam"]: s["collectie"] for s in k["sites"]} == {"SITE01": "Belgium", "SITE02": "Belgium"}
    assert k["groepen"] == ["ACCESS", "ACCESS_VSF", "WIRELESS"] and k["collecties"] == ["Belgium"]
    assert not [c for c in nep_central.AANROEPEN if c[0] != "GET"]


def test_hostname_staat_upload_niet_in_de_weg(tmp_path):
    from cnx_api import aliassen
    cfg = json.load(open(os.path.join(os.path.dirname(web.__file__), "data", "klantconfig.json"), encoding="utf-8"))
    cfg["velden"]["sys_vlan_ip"]["standaard_vlan"] = 120
    t = [{"serial": "SG00TEST01", "hostname": "", "site": "S", "device_group": "G", "sys_vlan_ip": "10.1.1.10/24", "_regel": 2},
         {"serial": "SG00TEST02", "hostname": "1-ongeldig", "site": "S", "device_group": "G", "sys_vlan_ip": "10.1.1.11/24", "_regel": 3},
         {"serial": "SG00TEST03", "hostname": "SW3", "site": "S", "device_group": "G", "sys_vlan_ip": "10.1.1.12/24", "_regel": 4}]
    b = aliassen.controleer(t, cfg, None)
    assert not b.fouten                                   # geen profiel, lege en ongeldige hostname: enkel aandachtspunten
    secties = [r[0] for x in t for r in aliassen.rijen_voor_toestel(x, cfg)]
    assert secties == ["#ALIAS_IPV4_ADDRESS_TYPE"] * 3    # enkel het IP, geen hostname zonder System-info-profiel
    cfg["velden"]["hostname"]["instance"] = "PROFIEL"
    secties = {x["serial"]: [r[0] for r in aliassen.rijen_voor_toestel(x, cfg)] for x in t}
    assert secties["SG00TEST03"] == ["#System-info", "#ALIAS_IPV4_ADDRESS_TYPE"] and secties["SG00TEST02"] == ["#ALIAS_IPV4_ADDRESS_TYPE"]
    # zonder profiel in de klantconfig: de hostname gaat mee in het eigen profiel van de switch (uit Central gelezen)
    cfg["velden"]["hostname"]["instance"] = "VUL-IN: naam"
    x = dict(t[2], systeemprofiel="sys-system-info-profile")
    rij = aliassen.rijen_voor_toestel(x, cfg)[0]
    assert rij[0] == "#System-info" and rij[3] == "sys-system-info-profile" and rij[5] == ("SW3",)


def test_eigen_device_function_in_upload():
    from cnx_api import aliassen
    cfg = json.load(open(os.path.join(os.path.dirname(web.__file__), "data", "klantconfig.json"), encoding="utf-8"))
    cfg["velden"]["sys_vlan_ip"]["standaard_vlan"] = 120
    t = [{"serial": "SG00TEST01", "hostname": "SW1", "site": "S", "device_group": "G", "device_function": "Core Switch", "sys_vlan_ip": "10.1.1.10/24", "_regel": 2},
         {"serial": "SG00TEST02", "hostname": "SW2", "site": "S", "device_group": "G", "device_function": "CORE", "sys_vlan_ip": "10.1.1.11/24", "_regel": 3},
         {"serial": "SG00TEST03", "hostname": "SW3", "site": "S", "device_group": "G", "device_function": "router", "sys_vlan_ip": "10.1.1.12/24", "_regel": 4}]
    b = aliassen.controleer(t, cfg, None)
    assert [f[2] for f in b.fouten] == ["SG00TEST03"]                       # onbekende functie is een fout, Core niet
    assert aliassen.rijen_voor_toestel(t[0], cfg)[0][4][0] == "Core Switch"
    assert aliassen.rijen_voor_toestel(t[1], cfg)[0][4][0] == "Core Switch"
    assert aliassen.rijen_voor_toestel(dict(t[0], device_function=""), cfg)[0][4][0] == "Access Switch"


def test_toestellen_uit_device_group(server, monkeypatch):
    import nep_central
    nep_central.AANROEPEN.clear()
    monkeypatch.setattr(cx, "api", nep_central.api)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    r = j(vraag(server + "/api/web/ov/groepswitches?groep=access&prefix=&vlan=120"))
    assert r["groep"] == "access" and [x["serial"] for x in r["rijen"]] == ["SG00TEST01"]
    x = r["rijen"][0]
    assert (x["hostname"], x["site_collection"], x["site"], x["device_function"], x["sys_vlan_ip"], x["beheer_vlan"]) ==         ("SITE01-SW01", "Belgium", "SITE01", "Access Switch", "10.10.120.21/24", "120")
    stack = j(vraag(server + "/api/web/ov/groepswitches?groep=ACCESS_VSF&prefix=23"))
    x = stack["rijen"][0]
    assert x["stack"] == "ja" and x["sys_vlan_ip"] == "10.20.120.20/23" and x["systeemprofiel"] == "sys-system-info-profile"
    assert any("VSF-stack" in m for m in stack["meldingen"])
    assert vraag(server + "/api/web/ov/groepswitches?groep=BESTAAT-NIET")[0] == 400
    assert vraag(server + "/api/web/ov/groepswitches?groep=ACCESS&prefix=99")[0] == 400
    assert not [c for c in nep_central.AANROEPEN if c[0] != "GET"]          # leest enkel


def test_gateway_in_device_group(server, monkeypatch, tmp_path):
    """Een Mobility Gateway in de device group: beheer-IP uit sys_vlan_ipv4_120 (niet de DHCP-uplink op 4094, niet het
    IP uit de monitoring), en in het importbestand Device Function Mobility Gateway, zoals Central's eigen download."""
    monkeypatch.setattr(cx, "api", nep_central.api)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    monkeypatch.setattr(web, "WERKMAP", str(tmp_path))
    r = j(vraag(server + "/api/web/ov/groepswitches?groep=WIRELESS"))
    assert [x["serial"] for x in r["rijen"]] == ["GW0TEST01"]
    gw = r["rijen"][0]
    assert (gw["soort"], gw["device_function"], gw["sys_vlan_ip"], gw["beheer_vlan"], gw["bron_ip"], gw["stack"], gw["systeemprofiel"]) == \
        ("gateway", "Mobility Gateway", "10.10.120.5/24", "120", "alias", "", "sys-system-info-profile")
    b = j(vraag(server + "/api/web/onboard/bestand", {"groep": "WIRELESS", "rijen": r["rijen"]}))
    assert b["fouten"] == 0
    tekst = b["bestanden"][0]["inhoud"]
    assert "sys_vlan_ipv4_120,ALIAS_IPV4_ADDRESS_TYPE,Mobility Gateway,Device,Belgium,SITE01,WIRELESS,GW0TEST01,Yes,10.10.120.5/24" in tekst
    assert "hostname,sys-system-info-profile,Mobility Gateway,Device,Belgium,SITE01,WIRELESS,GW0TEST01,Yes,GW-SITE01-01" in tekst
    assert "4094" not in tekst
    # zonder alias op de gateway: geen IP raden uit de monitoring (dat is meestal de uplink)
    monkeypatch.setitem(nep_central.ALIASSEN, "d9", [])
    gw = j(vraag(server + "/api/web/ov/groepswitches?groep=WIRELESS"))["rijen"][0]
    assert gw["sys_vlan_ip"] == "" and "controller in AOS-8" in gw["opmerking"]


def test_lange_opmerking_blokkeert_niet(server, monkeypatch, tmp_path):
    """De opmerking is enkel uitleg (kan lang worden met meerdere aandachtspunten) en komt niet in het bestand."""
    monkeypatch.setattr(web, "WERKMAP", str(tmp_path))
    rij = {"serial": "SG00TEST01", "hostname": "SITE02-SW01", "site_collection": "Belgium", "site": "SITE02",
           "device_group": "STAGING", "device_function": "Mobility Gateway", "sys_vlan_ip": "10.10.120.221/22",
           "beheer_vlan": "120", "systeemprofiel": "", "opmerking": "uit new Central. " * 30 + "\nnog een regel"}
    r = j(vraag(server + "/api/web/onboard/bestand", {"groep": "STAGING", "rijen": [rij]}))
    assert "fout" not in r and r["fouten"] == 0
    tekst = r["bestanden"][0]["inhoud"]
    assert "sys_vlan_ipv4_120,ALIAS_IPV4_ADDRESS_TYPE,Mobility Gateway" in tekst and "#System-info" not in tekst

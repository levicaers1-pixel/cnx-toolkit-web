"""Rooktests zonder API: de commando's die lokaal werken, en de API-logica tegen een nagemaakte API."""
import csv
import json
import os
import subprocess
import sys

import pytest

HIER = os.path.dirname(__file__)
DATA = os.path.join(HIER, "data")


def cnx(*args, cwd):
    return subprocess.run([sys.executable, "-m", "cnx_api", *args], cwd=cwd, capture_output=True, text=True)


def test_versie(tmp_path):
    from cnx_api import __version__
    r = cnx("--version", cwd=tmp_path)
    assert r.returncode == 0 and __version__ in r.stdout


def test_sjablonen_en_klantconfig_verplicht(tmp_path):
    assert cnx("sjablonen", cwd=tmp_path).returncode == 0
    assert (tmp_path / "klantconfig.json").exists()
    # zonder System-info-profiel weigert genereer niet meer: de hostname staat de IP-upload niet in de weg
    r = cnx("alias", "genereer", "--toestellen", "toestellen-sjabloon.csv", "--out", "uit", cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    up = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "uit").glob("*.csv") if p.name != "bevindingen.csv")
    assert "VUL-IN" not in up and "10.10.120.11/24" in up
    assert "SITE01-SW01" not in up and "SITE01-SW02" in up         # VOORBEELD01 heeft geen profiel, VOORBEELD02 wel
    # een fout in de klantconfig (ongeldig beheer-VLAN) blijft blokkeren
    c = json.loads((tmp_path / "klantconfig.json").read_text(encoding="utf-8"))
    c["velden"]["sys_vlan_ip"]["standaard_vlan"] = 5000
    (tmp_path / "klantconfig.json").write_text(json.dumps(c), encoding="utf-8")
    r = cnx("alias", "genereer", "--toestellen", "toestellen-sjabloon.csv", "--out", "uit2", cwd=tmp_path)
    assert r.returncode == 1 and "klantconfig" in r.stdout


def vul_klantconfig(pad, vlan=120):
    c = json.loads(pad.read_text(encoding="utf-8"))
    c["klant"] = "Test"
    c["velden"]["hostname"]["instance"] = "TEST_Hostname"
    c["velden"]["sys_vlan_ip"]["standaard_vlan"] = vlan
    pad.write_text(json.dumps(c), encoding="utf-8")


def test_classic_naar_upload(tmp_path):
    cnx("sjablonen", cwd=tmp_path)
    vul_klantconfig(tmp_path / "klantconfig.json")
    r = cnx("alias", "uit-classic-lijst", "--lijst", os.path.join(DATA, "classic_switchlijst.csv"),
            "--prefix", "24", "--site-collection", "Belgium", "--out", "toestellen.csv", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rijen = list(csv.DictReader(open(tmp_path / "toestellen.csv", encoding="utf-8")))
    assert len(rijen) == 8 and sum(1 for x in rijen if x["stack"] == "ja") == 1
    r = cnx("alias", "genereer", "--toestellen", "toestellen.csv", "--out", "uit", cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    up = (tmp_path / "uit" / "site01__access-switch.csv").read_text(encoding="utf-8")
    assert "sys_vlan_ipv4_120,ALIAS_IPV4_ADDRESS_TYPE,Access Switch,Device" in up
    assert "hostname,sys-system-info-profile" in up          # switches uit Classic
    assert ",Yes," in up and ",No," not in up
    assert (tmp_path / "uit" / "manueel-stacks.csv").exists()


def test_fouten_worden_geweigerd(tmp_path):
    cnx("sjablonen", cwd=tmp_path)
    vul_klantconfig(tmp_path / "klantconfig.json")
    (tmp_path / "t.csv").write_text(
        "serial,hostname,site,device_group,sys_vlan_ip\n"
        "SG00TEST01,SW1,S,G,10.0.0.1\n"          # prefix ontbreekt
        "SG00TEST01,SW1,S,G,10.0.0.0/24\n",      # dubbel serial en hostname, netwerkadres
        encoding="utf-8")
    r = cnx("alias", "controleer", "--toestellen", "t.csv", cwd=tmp_path)
    assert r.returncode == 1
    for woord in ("prefix", "keer in de lijst", "netwerk"):
        assert woord in r.stdout


class _R:
    def __init__(self, code, j):
        self.status_code, self._j, self.text, self.headers = code, j, json.dumps(j), {}

    def json(self):
        return self._j


def test_naar_library_valt_nooit_zonder_waarde(tmp_path, monkeypatch):
    from cnx_api import alias_api as m
    toestand = {"glob": True, "dev": False, "toegewezen": {"sys_vlan_2000_description"}}
    A = {"name": "sys_vlan_2000_description", "type": "ALIAS_VLAN_DESCRIPTION",
         "default-value": {"vlan-description-value": {"description": "Client"}}}

    def api(meth, p, params=None, body=None):
        params = params or {}
        if p == "/network-config/v1/global":
            return _R(200, {"scopeId": "G"})
        if "config-assignments" in p and meth == "GET":
            return _R(200, {"config-assignment": [{"profile-type": "aliases", "profile-instance": n,
                                                   "device-function": "ACCESS_SWITCH"} for n in toestand["toegewezen"]]})
        if "config-assignments" in p and meth == "POST":
            toestand["toegewezen"].add(body["config-assignment"][0]["profile-instance"])
            return _R(200, {})
        if meth == "GET" and params.get("view-type") == "LIBRARY":
            return _R(200, A)
        if meth == "GET" and params.get("scope-id") == "G":
            return _R(200, A if toestand["glob"] else {})
        if meth == "GET" and params.get("scope-id") == "1":
            return _R(200, A if toestand["dev"] else {})
        if meth == "POST" and params.get("scope-id") == "1":
            toestand["dev"] = True
            return _R(200, {})
        if meth == "DELETE" and params.get("scope-id") == "G":
            toestand["glob"] = False
            toestand["toegewezen"].discard("sys_vlan_2000_description")   # toewijzing van de lokale kopie
            return _R(200, {})
        if meth == "DELETE" and params.get("scope-id") == "1":
            assert "sys_vlan_2000_description" in toestand["toegewezen"], "switch zou zonder waarde vallen"
            toestand["dev"] = False
            return _R(200, {})
        return _R(200, {})

    waarden = tmp_path / "w.csv"
    waarden.write_text("#ALIAS_VLAN_DESCRIPTION\nAlias Name,Alias Type,Device Function,Scope Level,Site Collection Name,"
                       "Site Name,Device Group Name,Device,Modified,description\nsys_vlan_2000_description,"
                       "ALIAS_VLAN_DESCRIPTION,Access Switch,Global,,,,,Yes,Client\n", encoding="utf-8")
    monkeypatch.setattr(m, "api", api)
    monkeypatch.setattr(m, "login", lambda: None)
    monkeypatch.setattr(m, "switches", lambda: {"SG00TEST01": {"scopeId": 1, "deviceFunction": "Access Switch",
                                                               "deviceName": "SW1"}})
    monkeypatch.setattr(sys, "argv", ["cnx api", "naar-library", "--waarden", str(waarden), "--serial", "SG00TEST01", "--apply"])
    assert m.main() == 0
    assert toestand == {"glob": False, "dev": False, "toegewezen": {"sys_vlan_2000_description"}}


def test_data_aanwezig():
    from cnx_api import resource
    for naam in ("web.html", "LEESMIJ.html", "MANUAL.html", "en-web.json", "en-server.json", "alias-config.json", "klantconfig.json",
                 "toestellen-sjabloon.csv", "aos10-modellen.json"):
        assert os.path.exists(resource(naam)), naam
    for weg in ("invoer.html",):
        assert not os.path.exists(resource(weg)), weg


def test_oude_commandos_zijn_weg():
    import importlib.util
    from cnx_api import __main__ as hoofd
    assert importlib.util.find_spec("cnx_api.overrides") is None
    assert "overrides" not in hoofd.COMMANDO_S and "invoer" not in hoofd.COMMANDO_S


def test_aanmaken_zet_beschrijving(tmp_path, monkeypatch):
    from cnx_api import alias_api as m
    gepost = []

    def api(meth, p, params=None, body=None):
        if p == "/network-config/v1/global":
            return _R(200, {"scopeId": "G"})
        if meth == "POST" and p.endswith("/aliases/sys_vlan_2000_description"):
            gepost.append(body)
            return _R(200, {})
        if meth == "GET" and p.endswith("/aliases/sys_vlan_2000_description"):
            return _R(200, dict(gepost[-1]) if gepost else {})
        return _R(200, {})

    waarden = tmp_path / "w.csv"
    waarden.write_text("#ALIAS_VLAN_DESCRIPTION\nAlias Name,Alias Type,Device Function,Scope Level,Site Collection Name,"
                       "Site Name,Device Group Name,Device,Modified,description\nsys_vlan_2000_description,"
                       "ALIAS_VLAN_DESCRIPTION,Access Switch,Global,,,,,Yes,Client\n", encoding="utf-8")
    monkeypatch.setattr(m, "api", api)
    monkeypatch.setattr(m, "login", lambda: None)
    monkeypatch.setattr(sys, "argv", ["cnx api", "aanmaken", "--waarden", str(waarden), "--apply"])
    assert m.main() == 0
    assert gepost and gepost[0]["description"] == "Alias aangemaakt via CNX API Tool"
    assert gepost[0]["default-value"] == {"vlan-description-value": {"description": "Client"}}

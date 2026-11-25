"""Tests voor de webapp (cnx web): pagina, toegang, klantconfig en aanmelden, zonder echte API."""
import base64
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request

import pytest

from cnx_api import alias_api as cx
from cnx_api import aliassen, web

DATA = os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "WERKMAP", str(tmp_path / "cnx-web"))
    os.makedirs(web.WERKMAP)
    srv = web.maak_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def vraag(url, body=None, token=True, headers=None):
    h = dict(headers or {})
    if token:
        h["X-Token"] = web.TOKEN
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def upload(pad, naam=None):
    with open(pad, "rb") as f:
        return {"naam": naam or os.path.basename(pad), "inhoud": base64.b64encode(f.read()).decode()}


def klantconfig(tmp_path):
    c = json.load(open(web.resource("klantconfig.json"), encoding="utf-8"))
    c["klant"] = "Test"
    c["velden"]["hostname"]["instance"] = "TEST_Hostname"
    c["velden"]["sys_vlan_ip"]["standaard_vlan"] = 120
    p = tmp_path / "klantconfig.json"
    p.write_text(json.dumps(c), encoding="utf-8")
    return p


class _Antwoord:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.headers = status, data or {}, {}
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


def test_verlopen_token_wordt_vernieuwd(monkeypatch):
    antwoorden = [_Antwoord(401), _Antwoord(200, {"ok": 1})]
    tokens = []
    monkeypatch.setattr(cx.S, "request", lambda *a, **k: antwoorden.pop(0))
    monkeypatch.setattr(cx.requests, "post", lambda *a, **k: tokens.append(k["data"]["client_id"]) or _Antwoord(200, {"access_token": "nieuw"}))
    monkeypatch.setattr(cx.verbinding(), "gegevens", {"id": "cid", "secret": "geheim"})
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer oud")
    r = cx.api("GET", "/x")
    assert r.status_code == 200 and tokens == ["cid"] and cx.S.headers["Authorization"] == "Bearer nieuw"


def test_zonder_gegevens_geen_nieuwe_aanmelding(monkeypatch):
    monkeypatch.setattr(cx.S, "request", lambda *a, **k: _Antwoord(401))
    monkeypatch.setattr(cx.requests, "post", lambda *a, **k: pytest.fail("mag niet aanmelden zonder gegevens"))
    monkeypatch.setattr(cx.verbinding(), "gegevens", {})
    assert cx.api("GET", "/x").status_code == 401


def test_cnx_zonder_argumenten_start_de_webapp(monkeypatch):
    import sys
    from cnx_api import __main__ as hoofd
    gestart = []
    monkeypatch.setattr(web, "main", lambda: gestart.append(sys.argv[1:]) or 0)
    monkeypatch.setattr(sys, "argv", ["cnx"])
    assert hoofd.main() == 0 and gestart == [[]]


def test_controleer_config():
    goed = {"modified": "Yes", "velden": {"hostname": {"instance": "P"}, "sys_vlan_ip": {"alias_patroon": "sys_vlan_ipv4_{vlan}",
                                                                                   "standaard_vlan": 120}, "mgmt_ip": {"instance": "mgmt"}}}
    assert aliassen.controleer_config(goed) == []
    slecht = json.loads(json.dumps(goed))
    slecht["velden"]["hostname"]["instance"] = ""
    slecht["velden"]["sys_vlan_ip"].update(standaard_vlan="5000", alias_patroon="abc")
    slecht.update(hostname_regex="([", modified="No")
    soorten = {veld.split(" (")[0]: soort for veld, _, soort in aliassen.controleer_config(slecht)}
    assert soorten == {"System-info-profiel": "ontbreekt", "Beheer-VLAN": "fout", "Aliaspatroon": "fout",
                       "Hostname-regel": "fout", "Modified": "fout"}


def test_klantconfig_lezen_opslaan_en_bak(server, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, b = vraag(server + "/api/web/klantconfig")
    info = json.loads(b)
    assert not info["bestaat"] and any(p["soort"] == "ontbreekt" for p in info["problemen"])

    cfg = info["config"]
    cfg["velden"]["sys_vlan_ip"]["standaard_vlan"] = "5000"
    s, b = vraag(server + "/api/web/klantconfig", {"config": cfg})
    assert s == 400 and b"4094" in b and not (tmp_path / "klantconfig.json").exists()

    cfg.update(klant="Test", modified="No", extra_veld="genegeerd")
    cfg["velden"]["hostname"]["instance"] = "TEST_Hostname"
    cfg["velden"]["sys_vlan_ip"]["standaard_vlan"] = "120"
    s, b = vraag(server + "/api/web/klantconfig", {"config": cfg})
    assert s == 200, b
    info = json.loads(b)
    opgeslagen = json.loads((tmp_path / "klantconfig.json").read_text(encoding="utf-8"))
    assert info["bestaat"] and info["problemen"] == []
    assert opgeslagen["velden"]["sys_vlan_ip"]["standaard_vlan"] == 120 and opgeslagen["modified"] == "Yes"
    assert "_uitleg" in opgeslagen and "extra_veld" not in opgeslagen

    cfg["klant"] = "Tweede"
    vraag(server + "/api/web/klantconfig", {"config": cfg})
    assert json.loads((tmp_path / "klantconfig.json.bak").read_text(encoding="utf-8"))["klant"] == "Test"
    s, b = vraag(server + "/api/web/klantconfig/bestand")
    assert s == 200 and json.loads(b)["klant"] == "Tweede"


def test_webpagina_script_syntax(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node niet beschikbaar")
    html = open(web.resource("web.html"), encoding="utf-8").read()
    js = tmp_path / "web.js"
    js.write_text(re.findall(r"<script>(.*?)</script>", html, re.S)[-1], encoding="utf-8")
    r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:500]


def test_toegang_en_paden(server):
    s, b = vraag(server + "/", token=False)
    assert s == 200 and web.TOKEN.encode() in b
    assert vraag(server + "/api/web/klantconfig", token=False)[0] == 403
    assert vraag(server + "/", token=False, headers={"Host": "evil.example"})[0] == 403
    for pad in ("../x", "..%2F..%2Fwin.ini", "C:/Windows/win.ini"):
        assert vraag(server + "/api/web/bestand?pad=" + pad)[0] == 404


def test_oude_onderdelen_zijn_weg(server):
    """De tabbladen onder Expert zijn verwijderd: hun aanvragen bestaan niet meer."""
    for pad in ("/api/web/commandos", "/api/web/taken", "/api/web/proj/lijst", "/api/web/sw/lijst", "/api/web/ov/snapshots"):
        assert vraag(server + pad)[0] == 404, pad
    for pad in ("/api/web/start", "/api/web/proj/nieuw", "/api/web/sw/test", "/api/web/herhaal"):
        assert vraag(server + pad, {})[0] == 404, pad
    for soort in ("aliassen", "gereedheid", "snapshot", "oplossen"):
        assert vraag(server + "/api/web/ov/ophaal", {"soort": soort, "opties": {}})[0] in (400, 401), soort


def test_klantconfig_voorstel_uit_bulk_download(server, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rijen = [{"serial": "SG00TEST01", "hostname": "SW1", "site": "S", "device_group": "G", "device_function": "Access Switch",
              "sys_vlan_ip": "10.1.1.10/24", "beheer_vlan": "130", "systeemprofiel": "sys-system-info-profile"}]
    r = json.loads(vraag(server + "/api/web/onboard/bestand", {"groep": "G", "rijen": rijen})[1])
    inhoud = base64.b64encode(r["bestanden"][0]["inhoud"].encode()).decode()
    s, b = vraag(server + "/api/web/klantconfig/voorstel", {"bestand": {"naam": "bulk.csv", "inhoud": inhoud}})
    voorstel = json.loads(b)["voorstel"]
    assert s == 200 and voorstel["standaard_vlan"]["waarde"] == 130
    assert vraag(server + "/api/web/klantconfig/voorstel", {"bestand": {"bron": "../x.csv"}})[0] == 400

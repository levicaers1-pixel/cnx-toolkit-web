"""AP-migratie: een AOS-8-inventaris (xlsx, csv of CLI-uitvoer) inlezen en beoordelen voor AOS-10."""
import base64
import io
import json
import os
import sys
import zipfile
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(__file__))
from cnx_api import aos8  # noqa: E402
from test_web import server, vraag  # noqa: E402,F401

AP_KOP = ["Name", "Group", "AP Type", "IP Address", "Status", "Flags", "Switch IP", "Standby IP", "Wired MAC Address", "Serial #", "Port", "FQLN", "Controller Name"]
APS = [
    ["AP-A-001", "SITE-A", 305, "10.1.0.1", "Up 3d:1h:2m:3s", "2", "10.0.0.1", "10.0.0.2", "aa:00:00:00:00:01", "SNA001", "N/A", "N/A", "CTRL-A1"],
    ["AP-A-002", "SITE-A", 514, "10.1.0.2", "Up 3d:1h:2m:3s", "2", "10.0.0.2", "10.0.0.1", "aa:00:00:00:00:02", "SNA002", "N/A", "N/A", "CTRL-A2"],
    ["AP-B-001", "SITE-B", 205, "10.2.0.1", "Down", "2", "10.0.0.3", "0.0.0.0", "aa:00:00:00:00:03", "SNB001", "N/A", "N/A", "CTRL-B"],
    ["aa:00:00:00:00:04", "default", 999, "10.2.0.2", "Up 1d", "2", "10.0.0.3", "0.0.0.0", "aa:00:00:00:00:04", "SNB002", "N/A", "N/A", "CTRL-B"],
]
CTRL_KOP = ["IP Address", "IPv6 Address", "Name", "Location", "Type", "Model", "Version", "Status", "Configuration State", "Linked AP Count"]
CTRLS = [
    ["10.0.0.10", "None", "MM1", "x", "conductor", "ArubaMM-VA", "8.13.3.0", "up", "UPDATE SUCCESSFUL", 0],
    ["10.0.0.1", "None", "CTRL-A1", "x", "MD", "Aruba7210", "8.10.0.21", "up", "UPDATE SUCCESSFUL", 1],
    ["10.0.0.2", "None", "CTRL-A2", "x", "MD", "Aruba7210", "8.10.0.21", "up", "UPDATE SUCCESSFUL", 1],
    ["10.0.0.3", "None", "CTRL-B", "x", "MD", "Aruba7030", "8.10.0.21", "down", "UPDATE SUCCESSFUL", 2],
]


def xlsx(bladen):
    """Een minimale .xlsx zoals Excel die schrijft: gedeelde tekst, getallen als <v>."""
    gedeeld, idx = [], {}

    def cel(ref, w):
        if isinstance(w, (int, float)):
            return f'<c r="{ref}"><v>{w}</v></c>'
        if w not in idx:
            idx[w] = len(gedeeld)
            gedeeld.append(w)
        return f'<c r="{ref}" t="s"><v>{idx[w]}</v></c>'
    sheets = []
    for rijen in bladen.values():
        xml = "".join(f'<row r="{i + 1}">' + "".join(cel(f"{chr(65 + j)}{i + 1}", w) for j, w in enumerate(r)) + "</row>" for i, r in enumerate(rijen))
        sheets.append(f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{xml}</sheetData></worksheet>')
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(bladen)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml" Type="x"/>' for i in range(len(bladen))) + "</Relationships>")
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f"<si><t>{escape(t)}</t></si>" for t in gedeeld) + "</sst>")
        for i, s in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", s)
    return b.getvalue()


def bestand(naam, data):
    return {"naam": naam, "inhoud": base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()}


def test_xlsx_met_ap_en_controllerlijst():
    data = xlsx({"Samenvatting": [["Inventaris"], [], ["Totaal", 4]], "AP Inventory": [AP_KOP] + APS, "Controllers": [CTRL_KOP] + CTRLS})
    r = aos8.analyseer([bestand("inv.xlsx", data)], "Klant")
    s = r["samenvatting"]
    assert (s["aps"], s["aps_up"], s["ok"], s["einde"], s["nee"], s["onbekend"]) == (4, 3, 1, 1, 1, 1)
    assert (s["controllers"], s["conductors"]) == (3, 1)
    ap = {a["serial"]: a for a in r["aps"]}
    assert ap["SNA001"]["model"] == "AP-305" and ap["SNA001"]["aos10"] == "einde"
    assert ap["SNB001"]["aos10"] == "nee" and ap["SNB002"]["aos10"] == "onbekend"
    # A1 en A2 zijn elkaars stand-by: een cluster, in stappen; B staat alleen en heeft een AP-205
    cl = {c["naam"]: c for c in r["clusters"]}
    assert cl["CTRL-A1 + CTRL-A2"]["redundant"] and cl["CTRL-A1 + CTRL-A2"]["klaar"]
    assert not cl["CTRL-B"]["redundant"] and not cl["CTRL-B"]["klaar"] and "vervangen" in cl["CTRL-B"]["blokkade"]
    ctrl = {c["naam"]: c for c in r["controllers"]}
    assert ctrl["MM1"]["aos10"] == "weg" and ctrl["CTRL-A1"]["model"] == "7210" and ctrl["CTRL-A1"]["aos10"] == "ok"
    soorten = {o["soort"] for o in r["opkuis"]}
    assert {"AP in groep default", "AP zonder naam (MAC)", "AP down", "controller down"} <= soorten
    assert "<html" in r["rapport"] and "AOS-10 gereedheid · Klant" in r["rapport"] and "CTRL-A1 + CTRL-A2" in r["rapport"]


def test_cli_uitvoer_van_de_conductor():
    tekst = """(MM1) *[mynode] #show ap database long

AP Database
-----------
Name      Group   AP Type  IP Address  Status           Flags  Switch IP  Standby IP  Wired MAC Address  Serial #  Port  FQLN
----      -----   -------  ----------  ------           -----  ---------  ----------  -----------------  --------  ----  ----
AP-A-001  SITE-A  505      10.1.0.1    Up 3d:1h:2m:3s   2      10.0.0.1   10.0.0.2    aa:00:00:00:00:01  SNA001    N/A   N/A
AP-A-002  SITE-A  615      10.1.0.2    Down             2      10.0.0.2   10.0.0.1    aa:00:00:00:00:02  SNA002    N/A   N/A

Flags: 2 = Using IKE version 2

(MM1) *[mynode] #show switches

All Switches
------------
IP Address  IPv6 Address  Name     Location  Type  Model      Version    Status  Configuration State
----------  ------------  ----     --------  ----  -----      -------    ------  -------------------
10.0.0.1    None          CTRL-A1  x         MD    Aruba7205  8.10.0.21  up      UPDATE SUCCESSFUL
10.0.0.2    None          CTRL-A2  x         MD    Aruba7205  8.10.0.21  up      UPDATE SUCCESSFUL

Total Switches:2
"""
    r = aos8.analyseer([bestand("mm.txt", tekst)])
    assert r["samenvatting"]["aps"] == 2 and r["samenvatting"]["ok"] == 2 and r["samenvatting"]["aps_up"] == 1
    a = {x["serial"]: x for x in r["aps"]}
    assert a["SNA001"]["controller"] == "CTRL-A1" and a["SNA001"]["standby"] == "CTRL-A2"      # namen via het IP van de controller
    assert [c["naam"] for c in r["clusters"]] == ["CTRL-A1 + CTRL-A2"]
    assert {c["model"] for c in r["controllers"]} == {"7205"}


def test_csv_zonder_controllerlijst():
    tekst = ";".join(AP_KOP) + "\n" + "\n".join(";".join(str(x) for x in a) for a in APS[:2])
    r = aos8.analyseer([bestand("aps.csv", tekst)])
    assert r["samenvatting"]["aps"] == 2
    assert any("geen controllerlijst" in m for m in r["meldingen"])


def test_fouten_en_route(server):
    for slecht in ([], [bestand("leeg.txt", "niets hier")], [bestand("kapot.xlsx", b"PK\x03\x04kapot")]):
        try:
            aos8.analyseer(slecht)
            assert False, slecht
        except aos8.Fout:
            pass
    status, tekst = vraag(server + "/api/web/aos8/gereedheid", {"bestanden": [bestand("leeg.txt", "niets")]})
    assert status == 400 and "geen AP-lijst" in json.loads(tekst)["fout"]
    data = xlsx({"AP Inventory": [AP_KOP] + APS})
    status, tekst = vraag(server + "/api/web/aos8/gereedheid", {"bestanden": [bestand("inv.xlsx", data)], "klant": "X"})
    r = json.loads(tekst)
    assert status == 200 and r["samenvatting"]["aps"] == 4 and r["klant"] == "X" and r["rapport"].startswith("<!DOCTYPE html>")


def test_migratieplan_per_cluster():
    from cnx_api import migratieplan as mp
    res = aos8.analyseer([bestand("inv.xlsx", xlsx({"AP Inventory": [AP_KOP] + APS, "Controllers": [CTRL_KOP] + CTRLS}))], "Klant")
    plan = mp.maak_plan(res, ["CTRL-A1 + CTRL-A2", "CTRL-B"])
    assert [f["fase"] for f in plan["klantbreed"]] == ["Eenmalig per klant"]
    a, b = plan["clusters"]
    assert [f["fase"] for f in a["fasen"]] == ["Voorbereiden", "Eerste gateway", "APs omzetten", "Tweede gateway", "Afronden"]
    assert [f["fase"] for f in b["fasen"]] == ["Voorbereiden", "Gateway omzetten", "APs omzetten", "Afronden"]
    ids_b = [s["id"] for f in b["fasen"] for s in f["stappen"]]
    assert "a-vervangen" in ids_b and "a-opkuis" in ids_b and "b-vrijmaken" not in ids_b
    vervangen = next(s for f in b["fasen"] for s in f["stappen"] if s["id"] == "a-vervangen")
    assert any("SNB001" in d for d in vervangen["data"])
    # een stap per AP-groep, met de echte groepsnaam in het commando
    assert any("ap convert add ap-group SITE-A" in c for f in a["fasen"] for s in f["stappen"] for c in s["cmd"])
    assert len({s["id"] for f in a["fasen"] for s in f["stappen"]}) == sum(len(f["stappen"]) for f in a["fasen"])
    assert [x["serial"] for x in a["ap_lijst"]] == ["SNA001", "SNA002"]
    for slecht in ([], ["bestaat niet"]):
        try:
            mp.maak_plan(res, slecht)
            assert False
        except ValueError:
            pass


def test_plan_en_voortgang_via_de_webapp(server):
    """De server bewaart niets: de browser stuurt de inventaris en de afgevinkte stappen mee."""
    data = xlsx({"AP Inventory": [AP_KOP] + APS, "Controllers": [CTRL_KOP] + CTRLS})
    status, _ = vraag(server + "/api/web/aos8/plan", {"clusters": ["CTRL-B"]})
    assert status == 400                                   # zonder inventaris geen plan
    status, tekst = vraag(server + "/api/web/aos8/gereedheid", {"bestanden": [bestand("inv.xlsx", data)], "klant": "Klant X"})
    inv = json.loads(tekst)
    assert status == 200
    del inv["rapport"]                                     # zo bewaart de browser het
    for weg in ("/api/web/aos8/laatste?klant=Klant%20X", "/api/web/aos8/voortgang?klant=Klant%20X"):
        assert vraag(server + weg + "&t=" + web_token())[0] == 404
    vg = {"CTRL-B": {"a-backup": "2026-11-24T10:00", "../x": "2026-11-24T10:00"}, "kapot": "x"}
    status, tekst = vraag(server + "/api/web/aos8/plan", {"inventaris": inv, "voortgang": vg, "clusters": ["CTRL-B"]})
    plan = json.loads(tekst)
    assert status == 200 and plan["clusters"][0]["naam"] == "CTRL-B" and "gedaan " in plan["html"] and "✓" in plan["html"]
    assert "../x" not in plan["html"]
    status, tekst = vraag(server + "/api/web/aos8/rapport", {"inventaris": inv})
    assert status == 200 and json.loads(tekst)["rapport"].startswith("<!DOCTYPE html>")
    assert vraag(server + "/api/web/aos8/plan", {"inventaris": {"clusters": "x"}, "clusters": ["CTRL-B"]})[0] == 400


def test_voortgang_uit_de_browser_wordt_nagekeken():
    from cnx_api import migratieplan as mp
    assert mp.voortgang_uit({"A": {"a-backup": "2026-11-24T10:00", "Slecht ID": "x", "b-x": 5}, "B": [], 3: {"c": "t" * 50}}) ==         {"A": {"a-backup": "2026-11-24T10:00"}, "3": {"c": "t" * 20}}
    assert mp.voortgang_uit(None) == {} and mp.voortgang_uit([1]) == {}


def web_token():
    from cnx_api import web
    return web.TOKEN

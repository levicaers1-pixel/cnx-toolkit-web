#!/usr/bin/env python3
"""Lokale overrides op switches in new Central bekijken en wissen, met een scherm in je browser.

  cnx overrides            start op http://127.0.0.1:8765 en opent de browser

Aanmelden: met de omgevingsvariabelen CNX_BASE_URL, CNX_CLIENT_ID en CNX_CLIENT_SECRET, of in het scherm zelf
(de gegevens blijven enkel in het geheugen van dit programma).

Wat het doet:
  - leest alle CX-switches uit de device inventory (een stack telt een keer)
  - per switch de lokale objecten op device-scope: VLAN's (layer2-vlan) en VLAN-beschrijvingen (aliases)
  - per override: bestaat er een vervanging op Global, site of device group voor dezelfde device function?
    Enkel dan is wissen veilig: de switch erft de waarde. Zonder vervanging verdwijnt de VLAN van de switch.
  - wissen = DELETE van het lokale object, met daarna een nieuwe scan van die switch
  - standaard een proefrun; "Echt uitvoeren" aanvinken om te wissen. Elke actie komt in overrides-log-<tijd>.json

Beschermd (standaard niet aan te vinken): VLAN 1 en het beheer-VLAN uit klantconfig.json. Aan te passen bovenaan in het scherm.
Enkel de module requests is nodig. Gebruikt de API-functies van cnx api.
"""
import datetime, json, os, secrets, sys, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from . import alias_api as cx
from . import __version__

POORT = int(os.environ.get("CNX_OVERRIDES_POORT", "8765"))
TOKEN = secrets.token_urlsafe(16)
LOGPAD = os.path.join(os.getcwd(), f"overrides-log-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
LOGBOEK, SLOT = [], threading.Lock()


def cache():
    """Leesgegevens uit Central (switches, scopes, toewijzingen), per verbinding: elke gebruiker de zijne."""
    c = cx.verbinding().cache
    c.setdefault("switches", None)
    c.setdefault("scopes", None)
    c.setdefault("toewijzingen", {})
    return c


TYPES = {
    "layer2-vlan": {"label": "VLAN", "sleutel": "vlan", "toewijzing": "layer2-vlan"},
    "aliases": {"label": "Alias", "sleutel": "name", "toewijzing": "aliases",
                "filter": lambda n: n.startswith("sys_vlan_") and n.endswith("_description")},
}


# ---------------------------------------------------------------- API

def aanmelden(base, cid, secret):
    """Via cnx api: die onthoudt de gegevens in het geheugen en vernieuwt een verlopen token zelf."""
    return cx.aanmelden(base, cid, secret)       # maakt ook de cache van de verbinding leeg


def lijst(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def scopes():
    """Naam -> scope-id voor sites en device groups."""
    if cache()["scopes"] is None:
        sites, groepen = {}, {}
        for pad, doel in (("/network-config/v1/sites", sites), ("/network-config/v1/device-groups", groepen)):
            off = 0
            while True:
                r = cx.api("GET", pad, {"limit": 100, "offset": off})
                if r.status_code >= 300:
                    break
                j = r.json()
                items = j.get("items", [])
                for g in items:
                    naam = g.get("scopeName") or g.get("siteName") or g.get("name")
                    doel[naam] = str(g.get("scopeId") or g.get("id"))
                off += 100
                if not items or off >= int(j.get("total") or 0):
                    break
        cache()["scopes"] = {"sites": sites, "groepen": groepen, "global": cx.global_params()["scope-id"]}
    return cache()["scopes"]


def toewijzingen(scope_id):
    if scope_id not in cache()["toewijzingen"]:
        r = cx.api("GET", f"{cx.PREFIX}/config-assignments", {"scope-id": scope_id})
        try:
            lst = r.json().get("config-assignment") or []
        except (ValueError, AttributeError):
            lst = []
        cache()["toewijzingen"][scope_id] = {(x.get("profile-type"), str(x.get("profile-instance")), x.get("device-function"))
                                           for x in lst}
    return cache()["toewijzingen"][scope_id]


def switches(vernieuw=False):
    if cache()["switches"] is None or vernieuw:
        uit, gezien = [], set()
        for serial, d in sorted(cx.switches().items(), key=lambda x: (x[1].get("siteName") or "", x[1].get("deviceName") or "")):
            sid = str(d.get("scopeId") or "")
            if not sid or sid in gezien:          # stackleden delen een scope
                continue
            gezien.add(sid)
            uit.append({"serial": serial, "naam": d.get("deviceName") or serial, "functie": cx.func_of(d) or "",
                        "functie_label": d.get("deviceFunction") or "", "site": d.get("siteName") or "",
                        "groep": d.get("deviceGroupName") or "", "scope": sid, "status": d.get("status") or "",
                        "model": d.get("model") or d.get("deviceModel") or ""})
        cache()["switches"] = uit
    return cache()["switches"]


def vervanging(sw, typ, inst):
    sc = scopes()
    kandidaten = [("device group " + sw["groep"], sc["groepen"].get(sw["groep"])),
                  ("site " + sw["site"], sc["sites"].get(sw["site"])),
                  ("Global", sc["global"])]
    for label, sid in kandidaten:
        if sid and (typ, str(inst), sw["functie"]) in toewijzingen(sid):
            return label
    return ""


def overrides(serial, types):
    sw = next((s for s in switches() if s["serial"] == serial), None)
    if not sw:
        return {"fout": "switch niet gevonden"}
    if not sw["functie"]:
        return {"fout": "switch heeft geen device function"}
    params = {"view-type": "LOCAL", "scope-id": sw["scope"], "device-function": sw["functie"]}
    uit, fouten = [], []
    for typ in types:
        cfg = TYPES[typ]
        r = cx.api("GET", f"{cx.PREFIX}/{typ}", params)
        if r.status_code >= 300:
            fouten.append(f"{typ}: {r.status_code} {r.text[:150]}")
            continue
        for it in lijst(r.json()):
            inst = str(it.get(cfg["sleutel"]) or it.get("name") or "")
            if not inst or ("filter" in cfg and not cfg["filter"](inst)):
                continue
            uit.append({"type": typ, "label": cfg["label"], "inst": inst,
                        "naam": it.get("name") if typ == "layer2-vlan" else "",
                        "vervanging": vervanging(sw, cfg["toewijzing"], inst)})
    uit.sort(key=lambda x: (x["type"], int(x["inst"]) if x["inst"].isdigit() else 99999, x["inst"]))
    return {"switch": sw, "overrides": uit, "fouten": fouten}


def wissen(serial, items, echt):
    sw = next((s for s in switches() if s["serial"] == serial), None)
    if not sw:
        return {"fout": "switch niet gevonden"}
    params = {"object-type": "LOCAL", "scope-id": sw["scope"], "device-function": sw["functie"]}
    res = []
    for it in items:
        pad = f"{cx.PREFIX}/{it['type']}/{quote(str(it['inst']), safe='')}"
        regel = {"versie": __version__, "tijd": datetime.datetime.now().isoformat(timespec="seconds"), "switch": sw["naam"], "serial": serial,
                 "type": it["type"], "inst": it["inst"], "echt": echt, "methode": "DELETE", "pad": pad, "params": params}
        if not echt:
            regel.update(status=None, resultaat="proefrun")
        else:
            r = cx.api("DELETE", pad, params)
            regel["status"] = r.status_code
            if r.status_code < 300:
                regel["resultaat"] = "gewist"
            elif "unexpected req_xpath" in r.text:
                regel["resultaat"] = "bestond niet meer"
            elif "referenced by" in r.text or "referred by" in r.text:
                try:
                    regel["resultaat"] = "in gebruik: " + r.json().get("message", "")[:200]
                except ValueError:
                    regel["resultaat"] = "in gebruik"
            else:
                regel["resultaat"] = f"fout {r.status_code}: {r.text[:200]}"
        res.append(regel)
        with SLOT:
            LOGBOEK.append(regel)
            with open(LOGPAD, "w", encoding="utf-8") as f:
                json.dump(LOGBOEK, f, indent=2)
    return {"resultaten": res, "log": LOGPAD}


def beschermd():
    """VLAN 1 en het beheer-VLAN uit klantconfig.json in de werkmap, als die er is."""
    vlans = ["1"]
    try:
        with open("klantconfig.json", encoding="utf-8") as f:
            v = json.load(f)["velden"]["sys_vlan_ip"].get("standaard_vlan")
        if v and str(v) != "1":
            vlans.append(str(v))
    except (OSError, ValueError, KeyError):
        pass
    return ",".join(vlans)


# ---------------------------------------------------------------- webserver

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, code=200):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _ok(self, q):
        return (q.get("t", [""])[0] == TOKEN) or (self.headers.get("X-Token") == TOKEN)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            b = PAGINA.replace("__TOKEN__", TOKEN).replace("__VERSIE__", __version__).replace("__BESCHERMD__", beschermd()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if not self._ok(q):
            return self._json({"fout": "geen toegang"}, 403)
        try:
            if u.path == "/api/status":
                return self._json({"aangemeld": "Authorization" in cx.S.headers, "base": cx.BASE,
                                   "env": bool(os.environ.get("CNX_CLIENT_ID"))})
            if u.path == "/api/switches":
                return self._json({"switches": switches(q.get("vernieuw", ["0"])[0] == "1")})
            if u.path == "/api/overrides":
                types = [t for t in q.get("types", ["layer2-vlan"])[0].split(",") if t in TYPES]
                return self._json(overrides(q["serial"][0], types))
        except SystemExit as e:
            return self._json({"fout": str(e)}, 500)
        except Exception as e:  # noqa: BLE001
            return self._json({"fout": f"{type(e).__name__}: {e}"}, 500)
        self._json({"fout": "onbekend"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if not self._ok({}):
            return self._json({"fout": "geen toegang"}, 403)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if u.path == "/api/aanmelden":
                ok, msg = aanmelden(body.get("base", ""), body.get("id", ""), body.get("secret", ""))
                return self._json({"ok": ok, "melding": msg})
            if u.path == "/api/wissen":
                return self._json(wissen(body["serial"], body["items"], bool(body.get("echt"))))
        except SystemExit as e:
            return self._json({"fout": str(e)}, 500)
        except Exception as e:  # noqa: BLE001
            return self._json({"fout": f"{type(e).__name__}: {e}"}, 500)
        self._json({"fout": "onbekend"}, 404)


PAGINA = r"""<!DOCTYPE html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CNX Overrides</title>
<script>try{if(window.top!==window.self)document.documentElement.classList.add('ingebed')}catch(e){document.documentElement.classList.add('ingebed')}</script>
<style>
:root{color-scheme:light;--paper:#f4f6f9;--panel:#fff;--panel2:#f8fafc;--ink:#122033;--ink2:#2b3a4f;--muted:#5f6c7f;--line:#e2e7ee;--line2:#cfd7e2;
--accent:#2457d6;--accent2:#1c46b0;--soft:#e6eefc;--onaccent:#fff;--bad:#c4312b;--badsoft:#fdeceb;--warn:#a35d06;--warnsoft:#fdf2e1;--ok:#1f7a4a;--oksoft:#e4f4ea;
--shadow:0 1px 2px rgba(18,32,51,.04),0 2px 6px rgba(18,32,51,.05);--ring:0 0 0 3px rgba(36,87,214,.18);
--mono:"Cascadia Mono",Consolas,ui-monospace,monospace;--body:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--paper:#0e131a;--panel:#161d27;--panel2:#1a2230;--ink:#e7ecf3;--ink2:#c9d2df;--muted:#93a0b4;--line:#253042;--line2:#334157;
--accent:#7aa2ff;--accent2:#9ab9ff;--soft:#1c2943;--onaccent:#0b1220;--bad:#ff7b72;--badsoft:#3b1f22;--warn:#f0b35a;--warnsoft:#3a2b16;--ok:#56d39a;--oksoft:#14322a;
--shadow:0 1px 2px rgba(0,0,0,.3);--ring:0 0 0 3px rgba(122,162,255,.25)}}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:var(--paper);color:var(--ink);font:14px/1.5 var(--body);display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}
button,input{font:inherit;color:inherit}input[type=checkbox]{accent-color:var(--accent);width:15px;height:15px}.mono{font-family:var(--mono);font-size:12.5px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
header{display:flex;gap:10px 16px;align-items:center;flex-wrap:wrap;padding:10px 18px;background:var(--panel);border-bottom:1px solid var(--line);min-height:54px}
h1{font-size:15px;margin:0;font-weight:650;letter-spacing:-.01em;display:flex;align-items:center;gap:10px}
h1::before{content:"CNX";width:30px;height:30px;border-radius:8px;display:grid;place-items:center;background:linear-gradient(135deg,#2457d6,#5b8cff);color:#fff;font-size:10.5px;font-weight:700;letter-spacing:.04em}
h3{margin:0 0 10px;font-size:15px;font-weight:650}
.sp{margin-left:auto}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:34px;border:1px solid var(--line2);background:var(--panel);padding:0 14px;border-radius:8px;cursor:pointer;font-weight:550;white-space:nowrap;transition:background .12s,border-color .12s}
.btn:hover{border-color:var(--accent);background:var(--panel2)}.btn.primary{background:var(--accent);color:var(--onaccent);border-color:var(--accent)}.btn.primary:hover{background:var(--accent2)}
.btn.danger{background:var(--bad);color:#fff;border-color:var(--bad)}.btn.danger:hover{filter:brightness(.93)}.btn:disabled{opacity:.45;cursor:not-allowed}
.pill{display:inline-flex;align-items:center;gap:5px;padding:1px 9px;border-radius:999px;font-size:11.5px;font-weight:650;white-space:nowrap;line-height:20px}
.ok{background:var(--oksoft);color:var(--ok)}.bad{background:var(--badsoft);color:var(--bad)}.warn{background:var(--warnsoft);color:var(--warn)}
.neu{background:var(--panel2);color:var(--muted);box-shadow:inset 0 0 0 1px var(--line)}
main{flex:1;min-height:0;display:flex}
aside{width:320px;flex:none;background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0}
.tools{padding:12px 14px;border-bottom:1px solid var(--line);display:grid;gap:9px}
.tools input[type=search],header input:not([type=checkbox]){min-height:34px;padding:5px 11px;border:1px solid var(--line2);border-radius:8px;background:var(--panel)}
.tools input[type=search]{width:100%}
input:focus{outline:none;border-color:var(--accent);box-shadow:var(--ring)}
.items{overflow-y:auto;flex:1;padding:4px 0}
.item{display:grid;grid-template-columns:1fr auto;align-items:start;gap:6px;margin:1px 8px;width:calc(100% - 16px);padding:8px 12px;border:0;border-radius:8px;background:transparent;text-align:left;cursor:pointer;color:var(--ink);position:relative}
.item:hover{background:var(--panel2)}.item[aria-current=true]{background:var(--soft)}
.item[aria-current=true]::before{content:"";position:absolute;left:-8px;top:8px;bottom:8px;width:3px;border-radius:0 3px 3px 0;background:var(--accent)}
.item .n{font-weight:600;font-family:var(--mono);font-size:12.5px}.item[aria-current=true] .n{color:var(--accent)}.item .s{color:var(--muted);font-size:12px}
section{flex:1;min-width:0;overflow:auto;padding:24px 28px 40px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:0 auto 16px;max-width:1180px;box-shadow:var(--shadow)}
table{border-collapse:separate;border-spacing:0;width:100%}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:11px;color:var(--muted);font-weight:650;text-transform:uppercase;letter-spacing:.05em;background:var(--panel2)}
tbody tr:hover td{background:var(--panel2)}tr.locked td{color:var(--muted)}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.field{display:grid;gap:6px}.field label{font-weight:600;font-size:13.5px}
.field input{min-height:36px;padding:6px 11px;border:1px solid var(--line2);border-radius:8px;background:var(--panel);min-width:260px}
.log{font-family:var(--mono);font-size:12.5px;line-height:1.55;white-space:pre-wrap;max-height:240px;overflow:auto;background:var(--panel2);border:1px solid var(--line);padding:12px 14px;border-radius:10px;margin-top:8px;color:var(--ink2)}
.echt{display:inline-flex;gap:8px;align-items:center;min-height:34px;padding:0 12px;border-radius:8px;border:1px solid var(--line2);cursor:pointer;background:var(--panel)}
.echt.aan{background:var(--badsoft);border-color:var(--bad);color:var(--bad);font-weight:650}
.muted{color:var(--muted)}
/* In de webapp toont de bovenbalk van cnx web al de titel en het aanmelden */
.ingebed h1,.ingebed header>.pill{display:none}
@media (max-width:820px){main{flex-direction:column}aside{width:auto;max-height:40vh;border-right:0;border-bottom:1px solid var(--line)}section{padding:16px}}
</style></head><body>
<header>
  <h1>CNX Overrides</h1><span class="pill neu">v__VERSIE__</span>
  <span class="pill neu" id="stat">niet aangemeld</span>
  <label class="echt" id="echtlbl"><input type="checkbox" id="echt"> Echt uitvoeren</label>
  <label class="row">Beschermde VLAN's <input id="besch" class="mono" value="__BESCHERMD__" size="10"></label>
  <label class="row"><input type="checkbox" id="t-alias"> ook VLAN-beschrijvingen (aliassen)</label>
  <span class="sp"></span>
  <button class="btn" id="scanall" disabled>Scan alle switches</button>
</header>
<main>
  <aside>
    <div class="tools"><input type="search" id="zoek" placeholder="Zoek op naam, site of groep">
      <div class="row"><button class="btn" id="vernieuw" disabled>Switches vernieuwen</button><span class="muted" id="telling"></span></div></div>
    <div class="items" id="items"></div>
  </aside>
  <section id="rechts"></section>
</main>
<script>
const T="__TOKEN__";let SW=[],SEL=null,DATA={},BUSY=false;
const $=id=>document.getElementById(id);
function el(t,a,...k){const e=document.createElement(t);for(const[x,v]of Object.entries(a||{})){if(v==null||v===false)continue;if(x=="class")e.className=v;else if(x.startsWith("on"))e.addEventListener(x.slice(2),v);else e.setAttribute(x,v===true?"":v)}for(const c of k.flat())if(c!=null&&c!==false)e.append(c.nodeType?c:document.createTextNode(c));return e}
async function get(p){const r=await fetch(p+(p.includes("?")?"&":"?")+"t="+T);return r.json()}
async function post(p,b){const r=await fetch(p,{method:"POST",headers:{"Content-Type":"application/json","X-Token":T},body:JSON.stringify(b)});return r.json()}
function types(){return "layer2-vlan"+($("t-alias").checked?",aliases":"")}
function beschermd(o){if(o.type!="layer2-vlan")return false;return $("besch").value.split(/[ ,;]+/).filter(Boolean).includes(o.inst)}
$("echt").onchange=()=>{$("echtlbl").classList.toggle("aan",$("echt").checked);render()};
$("besch").onchange=render;$("t-alias").onchange=()=>{DATA={};renderList();if(SEL)laad(SEL)};
$("zoek").oninput=renderList;$("vernieuw").onclick=()=>laadSwitches(true);
$("scanall").onclick=async()=>{if(BUSY)return;BUSY=true;let i=0;for(const s of zichtbaar()){i++;$("telling").textContent="scan "+i+"/"+zichtbaar().length;DATA[s.serial]=await get("/api/overrides?serial="+encodeURIComponent(s.serial)+"&types="+types());renderList();}BUSY=false;$("telling").textContent=SW.length+" switches";render()};
function zichtbaar(){const z=$("zoek").value.toLowerCase();return SW.filter(s=>!z||[s.naam,s.site,s.groep,s.serial].some(v=>(v||"").toLowerCase().includes(z)))}
function samenvatting(s){const d=DATA[s.serial];if(!d)return el("span",{class:"pill neu"},"niet gescand");if(d.fout)return el("span",{class:"pill bad"},"fout");const n=d.overrides.length;if(!n)return el("span",{class:"pill ok"},"0");const v=d.overrides.filter(o=>o.vervanging&&!beschermd(o)).length;return el("span",{class:"pill "+(v==n?"warn":"bad")},n+" ("+v+" veilig)")}
function renderList(){const b=$("items");b.replaceChildren();for(const s of zichtbaar())b.append(el("button",{class:"item","aria-current":SEL==s.serial?"true":"false",onclick:()=>{SEL=s.serial;renderList();laad(s.serial)}},el("div",{},el("div",{class:"n"},s.naam),el("div",{class:"s"},(s.functie_label||"geen functie")+" · "+(s.site||"geen site")+" · "+(s.groep||""))),samenvatting(s)))}
async function laad(serial){$("rechts").replaceChildren(el("p",{class:"muted"},"Overrides lezen..."));DATA[serial]=await get("/api/overrides?serial="+encodeURIComponent(serial)+"&types="+types());renderList();render()}
let LOG=[];
function render(){const r=$("rechts");if(!SEL){r.replaceChildren(el("div",{class:"card"},el("p",{},"Kies links een switch, of scan alle switches.")));return}
 const d=DATA[SEL];if(!d){return}if(d.fout){r.replaceChildren(el("div",{class:"card"},el("p",{class:"pill bad"},d.fout)));return}
 const s=d.switch,ov=d.overrides,echt=$("echt").checked;
 const tb=el("tbody");
 ov.forEach((o,i)=>{const lock=beschermd(o),veilig=!!o.vervanging&&!lock;
  tb.append(el("tr",{class:lock?"locked":""},el("td",{},el("input",{type:"checkbox",id:"c"+i,checked:veilig,disabled:lock})),
   el("td",{},o.label),el("td",{class:"mono"},o.inst),el("td",{},o.naam||""),
   el("td",{},lock?el("span",{class:"pill neu"},"beschermd"):o.vervanging?el("span",{class:"pill ok"},"erft van "+o.vervanging):el("span",{class:"pill bad"},"geen vervanging: VLAN verdwijnt"))))});
 const knop=el("button",{class:"btn "+(echt?"danger":"primary"),id:"wis",onclick:wis},echt?"Clear geselecteerde overrides":"Proefrun: toon wat gewist wordt");
 r.replaceChildren(
  el("div",{class:"card"},el("div",{class:"row"},el("strong",{class:"mono"},s.naam),el("span",{class:"muted"},s.serial+" · "+s.functie_label+" · "+s.site+" · "+s.groep+" · "+s.status),el("span",{class:"sp"}),el("button",{class:"btn",onclick:()=>laad(SEL)},"Opnieuw lezen"))),
  el("div",{class:"card"},el("div",{class:"row"},el("strong",{},ov.length+" lokale overrides"),el("span",{class:"sp"}),
     el("button",{class:"btn",onclick:()=>ov.forEach((o,i)=>{const c=$("c"+i);if(c&&!c.disabled)c.checked=!!o.vervanging})},"Selecteer veilige"),
     el("button",{class:"btn",onclick:()=>ov.forEach((o,i)=>{const c=$("c"+i);if(c)c.checked=false})},"Niets"),knop),
   ov.length?el("table",{},el("thead",{},el("tr",{},el("th",{},""),el("th",{},"Type"),el("th",{},"ID / naam"),el("th",{},"VLAN-naam"),el("th",{},"Na wissen"))),tb):el("p",{class:"muted"},"Geen lokale overrides voor dit type."),
   d.fouten&&d.fouten.length?el("p",{class:"pill bad"},d.fouten.join(" | ")):null),
  el("div",{class:"card"},el("strong",{},"Logboek"),el("div",{class:"log",id:"log"},LOG.join("\n")||"Nog niets uitgevoerd.")))}
async function wis(e){const d=DATA[SEL],echt=$("echt").checked,b=e.currentTarget;
 const items=d.overrides.filter((o,i)=>$("c"+i)&&$("c"+i).checked);if(!items.length){return}
 const zonder=items.filter(o=>!o.vervanging);
 if(echt&&b.dataset.zeker!="1"){b.dataset.zeker="1";b.textContent="Zeker? "+items.length+" wissen op "+d.switch.naam+(zonder.length?" ("+zonder.length+" ZONDER vervanging)":"");return}
 b.disabled=true;const r=await post("/api/wissen",{serial:SEL,items,echt});
 if(r.fout){LOG.unshift("FOUT "+r.fout)}else{for(const x of r.resultaten)LOG.unshift(x.tijd+"  "+x.switch+"  "+x.type+" "+x.inst+"  "+x.resultaat);LOG.unshift("logboek: "+r.log)}
 if(echt)await laad(SEL);else render()}
async function laadSwitches(v){$("telling").textContent="switches lezen...";const r=await get("/api/switches"+(v?"?vernieuw=1":""));if(r.fout){$("telling").textContent=r.fout;return}SW=r.switches;$("telling").textContent=SW.length+" switches";$("scanall").disabled=false;$("vernieuw").disabled=false;renderList();render()}
async function start(){const s=await get("/api/status");if(s.aangemeld){$("stat").textContent="aangemeld · "+s.base;$("stat").className="pill ok";laadSwitches(false);return}
 const f=el("div",{class:"card"},el("h3",{},"Aanmelden bij new Central"),el("div",{class:"row"},
  el("div",{class:"field"},el("label",{for:"b"},"API-URL"),el("input",{id:"b",value:"https://de1.api.central.arubanetworks.com"})),
  el("div",{class:"field"},el("label",{for:"i"},"Client ID"),el("input",{id:"i"})),
  el("div",{class:"field"},el("label",{for:"x"},"Client secret"),el("input",{id:"x",type:"password"}))),
  el("p",{class:"muted"},"Blijft enkel in het geheugen van dit programma op je pc."),
  el("button",{class:"btn primary",onclick:async()=>{const r=await post("/api/aanmelden",{base:$("b").value,id:$("i").value,secret:$("x").value});if(r.ok)start();else alertBox(r.melding)}},"Aanmelden"),el("p",{id:"am",class:"pill bad",style:"display:none"}));
 $("rechts").replaceChildren(f)}
function alertBox(m){const a=$("am");a.style.display="inline-block";a.textContent=m}
start();
</script></body></html>"""


def main():
    if os.environ.get("CNX_CLIENT_ID") and os.environ.get("CNX_CLIENT_SECRET") and os.environ.get("CNX_BASE_URL"):
        ok, msg = aanmelden(os.environ["CNX_BASE_URL"], os.environ["CNX_CLIENT_ID"], os.environ["CNX_CLIENT_SECRET"])
        print(msg)
    srv = ThreadingHTTPServer(("127.0.0.1", POORT), Handler)
    url = f"http://127.0.0.1:{POORT}/"
    print(f"CNX Overrides {__version__} draait op {url}  (Ctrl+C of dit venster sluiten om te stoppen)")
    print(f"Logboek: {LOGPAD}")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nGestopt.")
    finally:
        srv.server_close()  # poort vrijgeven, zodat het menu overrides opnieuw kan starten


if __name__ == "__main__":
    main()

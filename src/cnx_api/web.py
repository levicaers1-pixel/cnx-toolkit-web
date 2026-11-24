#!/usr/bin/env python3
"""CNX Toolkit in je browser: switches onboarden (importbestand voor new Central) en overrides controleren.

  cnx web                    start op http://127.0.0.1:8766 en opent de browser
  cnx web --poort 9000       andere poort (standaard 8766, of $env:CNX_WEB_POORT)
  cnx web --geen-browser     de browser niet zelf openen
  cnx web --map <map>        waar importbestanden en logboeken komen (standaard cnx-web in de huidige map)

De webapp draait enkel op deze computer (127.0.0.1). Overrides wissen gebeurt pas na een plan dat je eerst ziet.
Aanmelden: met CNX_BASE_URL, CNX_CLIENT_ID en CNX_CLIENT_SECRET, of in het scherm zelf
(de gegevens blijven enkel in het geheugen van dit programma).
"""
import argparse, base64, datetime, json, os, re, shutil, threading, webbrowser
from http.server import ThreadingHTTPServer
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote, urlparse

from . import __version__, resource
from . import alias_api as cx
from . import aliassen
from . import aos8
from . import migratieplan
from . import configapi
from . import monitor
from . import overrides as ov

POORT = int(os.environ.get("CNX_WEB_POORT", "8766"))
MAX_BODY = 50 * 1024 * 1024
WERKMAP = os.path.join(os.getcwd(), "cnx-web")


class Fout(Exception):
    pass


def veilige_naam(naam):
    naam = re.sub(r"[^A-Za-z0-9._ -]+", "_", os.path.basename(str(naam or "").replace("\\", "/"))).strip(" .")
    return naam or "bestand"


def veilig_pad(rel):
    """Pad binnen WERKMAP, of None. Beschermt tegen ../ en absolute paden."""
    basis = os.path.realpath(WERKMAP)
    p = os.path.realpath(os.path.join(basis, str(rel or "").replace("\\", "/").lstrip("/")))
    return p if p.startswith(basis + os.sep) else None


# ---------------------------------------------------------------- Switches onboarden: importbestand voor Central

ONBOARD_MAX_RIJEN = 5000


def onboard_bestand(groep, rijen):
    """Onboarding: rijen (zoals toestellen_uit_groep ze geeft, eventueel aangepast) naar het importbestand voor Central.
    Geen klantconfig nodig: VLAN, profiel en device function staan per switch. Schrijft het bestand ook in cnx-web/onboarding."""
    if not isinstance(rijen, list) or not rijen:
        raise Fout("kies minstens een switch")
    if len(rijen) > 5000:
        raise Fout("te veel switches")
    schoon = []
    for i, r in enumerate(rijen, start=2):
        if not isinstance(r, dict):
            raise Fout("ongeldige rij")
        x = {}
        for k in aliassen.TOESTEL_KOLOMMEN:
            w = r.get(k, "")
            w = "" if w is None else str(w)
            w = re.sub(r"\s+", "", w) if k in ("sys_vlan_ip", "beheer_vlan", "serial") else w.strip()
            if k == "opmerking":              # enkel uitleg, komt niet in het bestand: nooit een reden om te weigeren
                x[k] = re.sub(r"\s+", " ", w)[:1000]
                continue
            if len(w) > 200 or any(c in w for c in (chr(13), chr(10))):
                raise Fout(f"ongeldige waarde in {k}")
            x[k] = w
        x["_regel"] = i
        schoon.append(x)
    cfg = json.load(open(resource("klantconfig.json"), encoding="utf-8"))
    vlans = [x["beheer_vlan"] for x in schoon if x["beheer_vlan"].isdigit()]
    cfg["klant"] = "onboarding"
    cfg["velden"]["sys_vlan_ip"]["standaard_vlan"] = int(max(set(vlans), key=vlans.count)) if vlans else 1
    cfg["velden"]["hostname"]["instance"] = ""            # per switch het eigen System-info-profiel
    b = aliassen.controleer(schoon, cfg, None)
    bevindingen = [{"ernst": e, "regel": rg, "serial": sr, "veld": vd, "bevinding": bv} for e, rg, sr, vd, bv in b.lijst]
    if b.fouten:
        return {"fouten": len(b.fouten), "bevindingen": bevindingen, "bestanden": []}
    if not any(x["beheer_vlan"] for x in schoon if x.get("sys_vlan_ip")) and any(x.get("sys_vlan_ip") for x in schoon):
        bevindingen.append({"ernst": "LET OP", "regel": "", "serial": "", "veld": "beheer_vlan",
                            "bevinding": f"geen beheer-VLAN gevonden: alias sys_vlan_ipv4_{cfg['velden']['sys_vlan_ip']['standaard_vlan']}"})
    stacks = [x for x in schoon if aliassen.is_stack(x)]
    per_switch = [aliassen.rijen_voor_toestel(x, cfg) for x in schoon if not aliassen.is_stack(x)]
    per_switch = [r for r in per_switch if r]
    if not per_switch:
        return {"fouten": 0, "bevindingen": bevindingen, "bestanden": [], "melding": "niets om op te laden: geen IP en geen hostname"}
    delen, huidig, n = [], [], 0
    for r in per_switch:                     # een switch nooit over twee bestanden verdelen
        if huidig and n + len(r) > ONBOARD_MAX_RIJEN:
            delen.append(huidig)
            huidig, n = [], 0
        huidig += r
        n += len(r)
    delen.append(huidig)
    map_ = os.path.join(WERKMAP, "onboarding")
    os.makedirs(map_, exist_ok=True)
    stam = f"{veilige_naam(groep or 'switches').replace(' ', '_')}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    bestanden = []
    for i, deel in enumerate(delen, 1):
        naam = stam + (f"-deel{i}" if len(delen) > 1 else "") + ".csv"
        pad = os.path.join(map_, naam)
        aliassen.schrijf_bulk(pad, deel)
        with open(pad, encoding="utf-8") as f:
            inhoud = f.read()
        bestanden.append({"naam": naam, "pad": os.path.relpath(pad, WERKMAP).replace(os.sep, "/"), "inhoud": inhoud,
                          "rijen": len(deel), "switches": len({tuple(r[4]) for r in deel})})
    return {"fouten": 0, "bevindingen": bevindingen, "bestanden": bestanden, "stacks": [x["hostname"] or x["serial"] for x in stacks]}


# ---------------------------------------------------------------- klantconfig

def klantconfig_pad():
    """Dezelfde klantconfig.json die 'cnx alias' en 'cnx overrides' gebruiken (map waar cnx draait)."""
    return os.path.join(os.getcwd(), "klantconfig.json")


def _lees_json(pad):
    with open(pad, encoding="utf-8") as f:
        return json.load(f)


def klantconfig_info():
    pad = klantconfig_pad()
    bestaat = os.path.isfile(pad)
    try:
        cfg = _lees_json(pad if bestaat else resource("klantconfig.json"))
        if not isinstance(cfg, dict):
            raise ValueError("geen JSON-object")
    except (OSError, ValueError) as e:
        return {"pad": pad, "bestaat": bestaat, "config": _lees_json(resource("klantconfig.json")), "problemen": [],
                "leesfout": f"klantconfig.json is niet te lezen ({e}). Opslaan maakt een nieuwe; de oude blijft als .bak."}
    return {"pad": pad, "bestaat": bestaat, "config": cfg,
            "problemen": [{"veld": v, "tekst": t, "soort": s} for v, t, s in aliassen.controleer_config(cfg)]}


def klantconfig_opslaan(nieuw):
    """Neemt enkel de gekende velden over en bewaart de rest van het bestand (zoals _uitleg) zoals het was."""
    pad = klantconfig_pad()
    try:
        basis = _lees_json(pad) if os.path.isfile(pad) else _lees_json(resource("klantconfig.json"))
        if not isinstance(basis, dict):
            raise ValueError
    except (OSError, ValueError):
        basis = _lees_json(resource("klantconfig.json"))

    def deel(d, k):
        if not isinstance(d.get(k), dict):
            d[k] = {}
        return d[k]

    def tekst(x):
        return str(x if x is not None else "").strip()

    nv = nieuw.get("velden") if isinstance(nieuw.get("velden"), dict) else {}
    nk = lambda k: nv.get(k) if isinstance(nv.get(k), dict) else {}  # noqa: E731
    basis["klant"] = tekst(nieuw.get("klant"))
    basis["hostname_regex"] = tekst(nieuw.get("hostname_regex")) or aliassen.STANDAARD_REGEX
    basis["modified"] = "Yes"
    velden = deel(basis, "velden")
    deel(velden, "hostname")["instance"] = tekst(nk("hostname").get("instance"))
    sv = deel(velden, "sys_vlan_ip")
    sv["alias_patroon"] = tekst(nk("sys_vlan_ip").get("alias_patroon")) or "sys_vlan_ipv4_{vlan}"
    vlan = tekst(nk("sys_vlan_ip").get("standaard_vlan"))
    sv["standaard_vlan"] = int(vlan) if vlan.isdigit() else vlan
    deel(velden, "mgmt_ip")["instance"] = tekst(nk("mgmt_ip").get("instance"))
    fouten = [f"{v}: {t}" for v, t, s in aliassen.controleer_config(basis) if s == "fout"]
    if fouten:
        raise Fout("Niet opgeslagen. " + " ".join(fouten))
    if os.path.isfile(pad):
        shutil.copyfile(pad, pad + ".bak")
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    with open(pad, "w", encoding="utf-8") as f:
        json.dump(basis, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return klantconfig_info()


def klantconfig_voorstel(w):
    """Waarden voorstellen uit een opgeladen bulk-download. Schrijft niets weg."""
    if not (isinstance(w, dict) and "inhoud" in w):
        raise Fout("kies een bulk-download")
    try:
        inhoud = base64.b64decode(w["inhoud"], validate=True)
    except (ValueError, TypeError):
        raise Fout("bestand niet te lezen")
    os.makedirs(WERKMAP, exist_ok=True)
    tmp = os.path.join(WERKMAP, f".voorstel-{threading.get_ident()}.csv")
    try:
        with open(tmp, "wb") as f:
            f.write(inhoud)
        return aliassen.voorstel_uit_bulk(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------- webserver

def pagina(naam):
    with open(resource(naam), encoding="utf-8") as f:
        return f.read()


class Handler(ov.Handler):
    def _host_ok(self):
        """Enkel aanvragen voor 127.0.0.1 of localhost: beschermt tegen DNS-rebinding."""
        poort = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{poort}", f"localhost:{poort}")

    def _html(self, tekst):
        b = tekst.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _bestand(self, data, naam, soort="application/octet-stream"):
        self.send_response(200)
        self.send_header("Content-Type", soort)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(naam)}")
        self.end_headers()
        self.wfile.write(data)

    def _monitor(self, doe):
        """Aanvraag naar Central voor de tabbladen Switches en Overzicht: aanmelden nodig, fouten als JSON."""
        if "Authorization" not in cx.S.headers:
            return self._json({"fout": "Eerst aanmelden bij new Central (rechtsboven)."}, 401)
        try:
            return self._json(doe())
        except monitor.ApiFout as e:
            tekst = e.melding if e.status == 400 and isinstance(e, monitor.Invoer) else f"Central gaf {e.status}: {e.melding}"
            return self._json({"fout": tekst, "status": e.status}, 400 if isinstance(e, monitor.Invoer) else 502)
        except Exception as e:  # noqa: BLE001
            return self._json({"fout": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        if not self._host_ok():
            return self._json({"fout": "geen toegang"}, 403)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._html(pagina("web.html").replace("__TOKEN__", ov.TOKEN).replace("__VERSIE__", __version__))
        if u.path == "/hulp":
            return self._html(pagina("LEESMIJ.html"))
        if not u.path.startswith("/api/web/"):
            return super().do_GET()
        if not self._ok(q):
            return self._json({"fout": "geen toegang"}, 403)
        if u.path.startswith(("/api/web/sw/", "/api/web/ov/")):
            arg = lambda k, d="": q.get(k, [d])[0]  # noqa: E731
            if u.path == "/api/web/sw/overrides-lijst":
                return self._monitor(configapi.override_switches)
            if u.path == "/api/web/sw/afwijkingen":
                return self._monitor(lambda: configapi.afwijkingen(arg("serial"), arg("functie", "ACCESS_SWITCH")))
            if u.path == "/api/web/ov/groepswitches":
                return self._monitor(lambda: configapi.toestellen_uit_groep(arg("groep"), arg("prefix", "24"), arg("vlan", "")))
            if u.path == "/api/web/ov/keuzes":
                return self._monitor(configapi.keuzes)
            if u.path == "/api/web/ov/ophaling":
                o = OPHALINGEN.get(arg("id"))
                return self._json(o.info() if o else {"fout": "niet gevonden"}, 200 if o else 404)
            return self._json({"fout": "onbekend"}, 404)
        if u.path in ("/api/web/klantconfig", "/api/web/klantconfig/bestand"):
            if u.path == "/api/web/klantconfig":
                return self._json(klantconfig_info())
            if not os.path.isfile(klantconfig_pad()):
                return self._json({"fout": "nog geen klantconfig.json opgeslagen"}, 404)
            with open(klantconfig_pad(), "rb") as f:
                return self._bestand(f.read(), "klantconfig.json", "application/json")
        if u.path in ("/api/web/aos8/laatste", "/api/web/aos8/voortgang"):
            klant = q.get("klant", [""])[0]
            if u.path.endswith("voortgang"):
                return self._json({"voortgang": migratieplan.voortgang(WERKMAP, klant)})
            res = migratieplan.laad_inventaris(WERKMAP, klant)
            if not res:
                return self._json({"geen": True})
            res["rapport"] = aos8.rapport_html(res)
            return self._json(res)
        if u.path == "/api/web/bestand":
            p = veilig_pad(q.get("pad", [""])[0])
            if not p or not os.path.isfile(p):
                return self._json({"fout": "bestand niet gevonden"}, 404)
            with open(p, "rb") as f:
                return self._bestand(f.read(), os.path.basename(p))
        return self._json({"fout": "onbekend"}, 404)

    def do_POST(self):
        if not self._host_ok():
            return self._json({"fout": "geen toegang"}, 403)
        u = urlparse(self.path)
        if not u.path.startswith("/api/web/"):
            return super().do_POST()
        if not self._ok({}):
            return self._json({"fout": "geen toegang"}, 403)
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._json({"fout": "bestanden te groot (maximum 50 MB per taak)"}, 413)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json({"fout": "ongeldige aanvraag"}, 400)
        if u.path == "/api/web/onboard/bestand":
            try:
                return self._json(onboard_bestand(body.get("groep"), body.get("rijen")))
            except Fout as e:
                return self._json({"fout": str(e)}, 400)
        if u.path == "/api/web/aos8/gereedheid":
            try:
                res = aos8.analyseer(body.get("bestanden"), body.get("klant", ""))
                migratieplan.bewaar_inventaris(WERKMAP, res)
                return self._json(res)
            except aos8.Fout as e:
                return self._json({"fout": str(e)}, 400)
            except (ET.ParseError, KeyError, ValueError, AttributeError) as e:
                return self._json({"fout": f"bestand niet te lezen ({type(e).__name__}: {e})"}, 400)
        if u.path in ("/api/web/aos8/plan", "/api/web/aos8/voortgang"):
            klant = str(body.get("klant") or "")
            try:
                if u.path.endswith("voortgang"):
                    return self._json({"voortgang": migratieplan.zet_voortgang(WERKMAP, klant, body.get("cluster"), body.get("stap"), bool(body.get("gedaan")))})
                res = migratieplan.laad_inventaris(WERKMAP, klant)
                if not res:
                    return self._json({"fout": "Lees eerst de inventaris van deze klant in."}, 400)
                plan = migratieplan.maak_plan(res, body.get("clusters"))
                plan["html"] = migratieplan.plan_html(plan, migratieplan.voortgang(WERKMAP, klant))
                return self._json(plan)
            except ValueError as e:
                return self._json({"fout": str(e)}, 400)
        if u.path == "/api/web/ov/ophaal":
            return self._monitor(lambda: {"id": start_ophaling(body.get("soort", ""), body.get("opties") or {}).id})
        if u.path in ("/api/web/klantconfig", "/api/web/klantconfig/voorstel"):
            try:
                if u.path.endswith("voorstel"):
                    return self._json({"voorstel": klantconfig_voorstel(body.get("bestand"))})
                return self._json(klantconfig_opslaan(body.get("config") or {}))
            except Fout as e:
                return self._json({"fout": str(e)}, 400)
            except (OSError, ValueError) as e:
                return self._json({"fout": f"{type(e).__name__}: {e}"}, 500)
        if u.path == "/api/web/afmelden":
            cx.afmelden()
            ov.CACHE.update({"switches": None, "scopes": None, "toewijzingen": {}})
            return self._json({"ok": True})
        return self._json({"fout": "onbekend"}, 404)


# ---------------------------------------------------------------- switches: logboek van de acties


# ---------------------------------------------------------------- ophalingen: lang lezen uit Central, met voortgang

OPHALINGEN = {}
WISPLANNEN = {}


def logboek(naam, regels):
    """Wat er in Central gewijzigd is, in cnx-web/<naam>-<tijd>.json."""
    os.makedirs(WERKMAP, exist_ok=True)
    pad = os.path.join(WERKMAP, f"{naam}-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    with open(pad, "w", encoding="utf-8") as f:
        json.dump([dict(r, versie=__version__, tijd=datetime.datetime.now().isoformat(timespec="seconds")) for r in regels],
                  f, indent=2, ensure_ascii=False)
    return pad


class Ophaling:
    def __init__(self, soort):
        self.id = f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{soort}-{len(OPHALINGEN) + 1}"
        self.soort, self.status, self.gedaan, self.totaal, self.stap = soort, "bezig", 0, 0, "starten"
        self.resultaat, self.fout = None, None

    def voortgang(self, gedaan, totaal, stap):
        self.gedaan, self.totaal, self.stap = gedaan, totaal, stap

    def info(self):
        return {"id": self.id, "soort": self.soort, "status": self.status, "gedaan": self.gedaan, "totaal": self.totaal,
                "stap": self.stap, "fout": self.fout, "resultaat": self.resultaat if self.status == "klaar" else None}


def start_ophaling(soort, opties):
    if soort == "wisplan":
        def doe(v):
            plan = configapi.wis_plan(opties.get("items"), opties.get("device_function") or "ACCESS_SWITCH", v)
            pid = f"wis-{datetime.datetime.now():%Y%m%d%H%M%S}-{len(WISPLANNEN) + 1}"
            WISPLANNEN[pid] = (plan["acties"], plan["device_function"])
            return dict(plan, id=pid)
    elif soort == "wissen":
        gevonden = WISPLANNEN.pop(str(opties.get("plan") or ""), None)
        if gevonden is None:
            raise monitor.Invoer("Dit plan is verlopen of al uitgevoerd. Maak een nieuw plan.")
        acties, df = gevonden

        def doe(v):
            res = configapi.wis_uitvoeren(acties, df, v)
            logboek("overrides-wissen-log", res)
            return {"resultaten": res}
    elif soort == "afwijkingen":
        serials = [str(x) for x in (opties.get("serials") or []) if isinstance(x, (str, int))][:2000] or None
        doe = lambda v: configapi.afwijkingen_scan(serials, opties.get("device_function") or "ACCESS_SWITCH", v)  # noqa: E731
    else:
        raise monitor.Invoer("onbekende ophaling")
    o = Ophaling(soort)
    OPHALINGEN[o.id] = o

    def draai_ophaling():
        try:
            o.resultaat = doe(o.voortgang)
            o.status = "klaar"
        except monitor.ApiFout as e:
            o.fout, o.status = (e.melding if isinstance(e, monitor.Invoer) else f"Central gaf {e.status}: {e.melding}"), "fout"
        except Exception as e:  # noqa: BLE001
            o.fout, o.status = f"{type(e).__name__}: {e}", "fout"

    threading.Thread(target=draai_ophaling, daemon=True).start()
    return o


def maak_server(poort):
    """Probeert de poort en de negen volgende, voor als er al iets draait."""
    laatste = None
    for p in ([poort] if poort == 0 else range(poort, poort + 10)):
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), Handler)
        except OSError as e:
            laatste = e
    raise SystemExit(f"Geen vrije poort gevonden vanaf {poort}: {laatste}")


def main():
    global WERKMAP
    p = argparse.ArgumentParser(prog="cnx web", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--poort", type=int, default=POORT)
    p.add_argument("--geen-browser", action="store_true", help="de browser niet zelf openen")
    p.add_argument("--map", default=WERKMAP, help="map voor importbestanden en logboeken")
    a = p.parse_args()
    WERKMAP = os.path.abspath(a.map)
    os.makedirs(WERKMAP, exist_ok=True)
    if os.environ.get("CNX_CLIENT_ID") and os.environ.get("CNX_CLIENT_SECRET") and os.environ.get("CNX_BASE_URL"):
        ok, msg = ov.aanmelden(os.environ["CNX_BASE_URL"], os.environ["CNX_CLIENT_ID"], os.environ["CNX_CLIENT_SECRET"])
        print(msg)
    srv = maak_server(a.poort)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"CNX Toolkit {__version__} draait op {url}  (Ctrl+C of dit venster sluiten om te stoppen)")
    print(f"Importbestanden en logboeken: {WERKMAP}")
    if not a.geen_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nGestopt.")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()

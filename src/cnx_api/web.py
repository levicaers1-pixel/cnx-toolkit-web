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
import argparse, base64, datetime, hmac, http.cookies, json, os, re, secrets, shutil, sys, threading, time, webbrowser
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
OPSLAG = True               # False (--zonder-opslag, servermodus): niets op schijf; bestanden en logboeken gaan naar de browser


class Fout(Exception):
    pass


def veilige_naam(naam):
    naam = re.sub(r"[^A-Za-z0-9._ -]+", "_", os.path.basename(str(naam or "").replace("\\", "/"))).strip(" .")
    return naam or "bestand"


# ---------------------------------------------------------------- Switches onboarden: importbestand voor Central

ONBOARD_MAX_RIJEN = 5000


def onboard_bestand(groep, rijen):
    """Onboarding: rijen (zoals toestellen_uit_groep ze geeft, eventueel aangepast) naar het importbestand voor Central.
    Geen klantconfig nodig: VLAN, profiel en device function staan per switch. De browser krijgt de inhoud; met opslag
    komt er ook een kopie in cnx-web/onboarding."""
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
    if OPSLAG:
        os.makedirs(map_, exist_ok=True)
    stam = f"{veilige_naam(groep or 'switches').replace(' ', '_')}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    bestanden = []
    for i, deel in enumerate(delen, 1):
        naam = stam + (f"-deel{i}" if len(delen) > 1 else "") + ".csv"
        inhoud = aliassen.bulk_tekst(deel)
        rel = None
        if OPSLAG:
            pad = os.path.join(map_, naam)
            with open(pad, "w", newline="", encoding="utf-8") as f:
                f.write(inhoud)
            rel = os.path.relpath(pad, WERKMAP).replace(os.sep, "/")
        bestanden.append({"naam": naam, "pad": rel, "inhoud": inhoud,
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


# ---------------------------------------------------------------- sessies

class Sessie:
    """Wat bij een gebruiker hoort: de verbinding met Central, een eigen CSRF-token en de lopende ophalingen en
    wisplannen."""

    def __init__(self, verbinding):
        self.id = secrets.token_urlsafe(24)
        self.csrf = secrets.token_urlsafe(24)
        self.verbinding = verbinding
        self.ophalingen = {}
        self.wisplannen = {}
        self.laatst = time.time()

    def wis(self):
        self.verbinding.wis()
        self.ophalingen.clear()
        self.wisplannen.clear()


SERVER = False              # servermodus (--server): achter een reverse proxy, voor meerdere gebruikers
PER_SESSIE = False          # True: elke browser een eigen verbinding met Central. False: een gebruiker op deze pc
TOEGELATEN_HOSTS = set()    # servermodus: hostnamen (zonder poort) die in de Host-kop mogen staan; "*" = alles
CENTRAL_DOMEINEN = [d.strip().lower().lstrip(".") for d in os.environ.get("CNX_CENTRAL_DOMEINEN", "arubanetworks.com").split(",") if d.strip()]
SESSIE_DUUR = 30 * 60       # seconden zonder activiteit, daarna zijn sessie en secret weg
MAX_SESSIES = 500
MAX_BODY_SERVER = 20 * 1024 * 1024
WEGGOOI_GRENS = 64 * 1024 * 1024   # te grote body tot hier lezen en weggooien; daarboven de verbinding sluiten
MAX_TAKEN = 3               # lopende ophalingen per sessie
COOKIE = "cnx_sessie"
LOKAAL = Sessie(cx.verbinding())      # de standaardverbinding, ook die van de commandolijn
LOKAAL.csrf = ov.TOKEN
SESSIES = {}
_SESSIE_SLOT = threading.Lock()


def _opruimen(nu):
    """Sessies zonder activiteit sinds SESSIE_DUUR: verbinding (token en secret) en taken wissen. Onder _SESSIE_SLOT."""
    for sid in [k for k, v in SESSIES.items() if nu - v.laatst > SESSIE_DUUR]:
        SESSIES.pop(sid).wis()


def sessie_van(cookie, mag_maken=False):
    """Zoekt de sessie bij de cookie van de browser. Geeft (sessie of None, id van een nieuwe sessie of None).
    Een nieuwe sessie komt er enkel bij het openen van de pagina (mag_maken), niet bij elke losse aanvraag.
    Geeft (None, "vol") als er al MAX_SESSIES zijn."""
    if not PER_SESSIE:
        return LOKAAL, None
    sid = None
    try:
        c = http.cookies.SimpleCookie(cookie or "")
        sid = c[COOKIE].value if COOKIE in c else None
    except http.cookies.CookieError:
        pass
    nu = time.time()
    with _SESSIE_SLOT:
        _opruimen(nu)
        sessie = SESSIES.get(sid) if sid else None
        if sessie is not None:
            sessie.laatst = nu
            return sessie, None
        if not mag_maken:
            return None, None
        if len(SESSIES) >= MAX_SESSIES:
            return None, "vol"
        sessie = Sessie(cx.Verbinding())
        SESSIES[sessie.id] = sessie
        return sessie, sessie.id


def nieuwe_sessie_id(sessie):
    """Na aanmelden een nieuw sessie-id (tegen session fixation). Geeft het nieuwe id."""
    with _SESSIE_SLOT:
        SESSIES.pop(sessie.id, None)
        sessie.id = secrets.token_urlsafe(24)
        SESSIES[sessie.id] = sessie
    return sessie.id


def central_url_ok(base):
    """Servermodus: enkel https naar een domein van Central, zodat niemand de server naar een intern adres laat praten."""
    try:
        u = urlparse(str(base or "").strip())
        host = (u.hostname or "").lower()
        poort = u.port
    except ValueError:
        return False
    if u.scheme != "https" or not host or u.username or u.password or poort not in (None, 443):
        return False
    return any(host == d or host.endswith("." + d) for d in CENTRAL_DOMEINEN)


class Handler(ov.Handler):
    def parse_request(self):
        """Na het lezen van de kop: de sessie van deze browser zoeken en haar verbinding gebruiken voor de aanvraag."""
        self._start = time.monotonic()
        if not super().parse_request():
            return False
        pad = urlparse(self.path).path
        self.sessie, self._nieuwe_sessie = sessie_van(self.headers.get("Cookie"), mag_maken=self.command == "GET" and pad == "/")
        if self._nieuwe_sessie == "vol":
            self._nieuwe_sessie = None
            self._vol = True
        # Zonder sessie een lege verbinding, nooit de standaardverbinding of die van een vorige aanvraag op dezelfde draad.
        cx._HUIDIG.set(self.sessie.verbinding if self.sessie else cx.Verbinding())
        return True

    def end_headers(self):
        if getattr(self, "_nieuwe_sessie", None):
            self.send_header("Set-Cookie", f"{COOKIE}={self._nieuwe_sessie}; Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if SERVER else ""))
            self._nieuwe_sessie = None
        if SERVER:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def log_request(self, code="-", size="-"):
        """Servermodus: een regel per aanvraag, met methode, pad zonder parameters, status en duur. Nooit IP-adressen,
        parameters (serials, groepen, het token) of inhoud."""
        if SERVER:
            ms = int((time.monotonic() - getattr(self, "_start", time.monotonic())) * 1000)
            sys.stderr.write(f"{self.log_date_time_string()} {self.command} {urlparse(self.path).path} {code} {ms}ms\n")

    def _json(self, data, code=200):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _host_ok(self):
        """Lokaal enkel 127.0.0.1 of localhost (tegen DNS-rebinding); in servermodus de toegelaten hostnamen."""
        host = self.headers.get("Host", "")
        if SERVER:
            naam = host.rsplit(":", 1)[0] if not host.endswith("]") else host
            return "*" in TOEGELATEN_HOSTS or naam.strip("[]").lower() in TOEGELATEN_HOSTS
        poort = self.server.server_address[1]
        return host in (f"127.0.0.1:{poort}", f"localhost:{poort}")

    def _ok(self, q):
        """Het CSRF-token van de pagina, als kop X-Token of parameter t. In servermodus het token van deze sessie."""
        verwacht = self.sessie.csrf if self.sessie else None
        gegeven = self.headers.get("X-Token") or (q.get("t", [""])[0] if q else "")
        return bool(verwacht and gegeven) and hmac.compare_digest(str(gegeven), str(verwacht))

    def _voor_alles(self, pad):
        """Gezondheidscheck, Host-kop en sessie. Geeft True als de aanvraag al beantwoord is."""
        if pad == "/gezond":
            self._json({"ok": True})
            return True
        if pad == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return True
        if not self._host_ok():
            self._json({"fout": "geen toegang"}, 403)
            return True
        if getattr(self, "_vol", False):
            self._json({"fout": "Te veel gebruikers tegelijk. Probeer later opnieuw."}, 503)
            return True
        if self.sessie is None and pad not in ("/", "/hulp"):
            self._json({"fout": "Je sessie is verlopen. Herlaad de pagina."}, 401)
            return True
        return False

    def do_HEAD(self):
        """Voor gezondheidschecks die HEAD gebruiken: enkel /gezond, zonder inhoud."""
        ok = urlparse(self.path).path == "/gezond"
        self.send_response(200 if ok else 405)
        if not ok:
            self.send_header("Allow", "GET, POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _status(self):
        v = cx.verbinding()
        return {"aangemeld": v.aangemeld, "base": v.base, "env": bool(os.environ.get("CNX_CLIENT_ID")) and not SERVER}

    def _aanmelden(self, body):
        base = str(body.get("base") or "")
        if SERVER and not central_url_ok(base):
            return {"ok": False, "melding": "Geef de API-URL van new Central, bv. https://de1.api.central.arubanetworks.com. Een ander domein moet de beheerder eerst toelaten (CNX_CENTRAL_DOMEINEN)."}
        ok, msg = cx.aanmelden(base, str(body.get("id") or ""), str(body.get("secret") or ""))
        if ok and PER_SESSIE:
            self._nieuwe_sessie = nieuwe_sessie_id(self.sessie)
        return {"ok": ok, "melding": msg}

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
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if self._voor_alles(u.path):
            return
        if u.path == "/":
            return self._html(pagina("web.html").replace("__TOKEN__", self.sessie.csrf).replace("__VERSIE__", __version__)
                              .replace("__OPSLAG__", "true" if OPSLAG else "false"))
        if u.path == "/hulp":
            return self._html(pagina("LEESMIJ.html"))
        if not self._ok(q):
            return self._json({"fout": "geen toegang"}, 403)
        if u.path == "/api/status":
            return self._json(self._status())
        if not u.path.startswith("/api/web/"):
            return self._json({"fout": "onbekend"}, 404)      # de routes van de oude overrides-app horen hier niet
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
                o = self.sessie.ophalingen.get(arg("id"))
                return self._json(o.info() if o else {"fout": "niet gevonden"}, 200 if o else 404)
            return self._json({"fout": "onbekend"}, 404)
        if not OPSLAG and u.path in ("/api/web/klantconfig", "/api/web/klantconfig/bestand"):
            return self._json({"fout": "niet beschikbaar zonder opslag"}, 404)
        if u.path in ("/api/web/klantconfig", "/api/web/klantconfig/bestand"):
            if u.path == "/api/web/klantconfig":
                return self._json(klantconfig_info())
            if not os.path.isfile(klantconfig_pad()):
                return self._json({"fout": "nog geen klantconfig.json opgeslagen"}, 404)
            with open(klantconfig_pad(), "rb") as f:
                return self._bestand(f.read(), "klantconfig.json", "application/json")
        return self._json({"fout": "onbekend"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        # Eerst de body lezen (binnen de grens), ook als de aanvraag straks geweigerd wordt: anders breekt de
        # verbinding af voor de browser het antwoord leest.
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        grens = MAX_BODY_SERVER if SERVER else MAX_BODY
        if n < 0:
            self.close_connection = True
            return self._json({"fout": "ongeldige aanvraag"}, 400)
        if n > grens:
            if n <= WEGGOOI_GRENS:                # lezen en weggooien, zodat de browser de melding netjes krijgt
                rest = n
                while rest > 0:
                    blok = self.rfile.read(min(rest, 1 << 20))
                    if not blok:
                        break
                    rest -= len(blok)
            else:
                self.close_connection = True
            if not self._voor_alles(u.path):
                self._json({"fout": f"bestanden te groot (maximum {grens // (1024 * 1024)} MB per taak)"}, 413)
            return
        ruw = self.rfile.read(n) if n else b""
        if self._voor_alles(u.path):
            return
        if not self._ok({}):
            return self._json({"fout": "geen toegang"}, 403)
        try:
            body = json.loads(ruw or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._json({"fout": "ongeldige aanvraag"}, 400)
        if u.path == "/api/aanmelden":
            return self._json(self._aanmelden(body))
        if not u.path.startswith("/api/web/"):
            return self._json({"fout": "onbekend"}, 404)
        if u.path == "/api/web/onboard/bestand":
            try:
                return self._json(onboard_bestand(body.get("groep"), body.get("rijen")))
            except Fout as e:
                return self._json({"fout": str(e)}, 400)
        if u.path == "/api/web/aos8/gereedheid":
            try:
                return self._json(aos8.analyseer(body.get("bestanden"), body.get("klant", "")))   # de browser bewaart het
            except aos8.Fout as e:
                return self._json({"fout": str(e)}, 400)
            except (ET.ParseError, KeyError, ValueError, AttributeError) as e:
                return self._json({"fout": f"bestand niet te lezen ({type(e).__name__}: {e})"}, 400)
        if u.path in ("/api/web/aos8/plan", "/api/web/aos8/rapport"):
            # De inventaris en de voortgang komen van de browser; de server bewaart niets.
            try:
                res = migratieplan.inventaris_uit(body.get("inventaris"))
                if u.path.endswith("rapport"):
                    return self._json({"rapport": aos8.rapport_html(res)})
                plan = migratieplan.maak_plan(res, body.get("clusters"))
                plan["html"] = migratieplan.plan_html(plan, migratieplan.voortgang_uit(body.get("voortgang")))
                return self._json(plan)
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                return self._json({"fout": str(e) or "ongeldige inventaris"}, 400)
        if u.path == "/api/web/ov/ophaal":
            return self._monitor(lambda: {"id": start_ophaling(self.sessie, body.get("soort", ""), body.get("opties") or {}).id})
        if not OPSLAG and u.path.startswith("/api/web/klantconfig"):
            return self._json({"fout": "niet beschikbaar zonder opslag"}, 404)
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
            self.sessie.wis()                    # token, secret, cache, ophalingen en wisplannen
            return self._json({"ok": True})
        return self._json({"fout": "onbekend"}, 404)


# ---------------------------------------------------------------- switches: logboek van de acties


# ---------------------------------------------------------------- ophalingen: lang lezen uit Central, met voortgang


def logboek(naam, regels):
    """Wat er in Central gewijzigd is, in cnx-web/<naam>-<tijd>.json. Zonder opslag niets (None): de browser biedt het
    logboek dan als download aan."""
    if not OPSLAG:
        return None
    os.makedirs(WERKMAP, exist_ok=True)
    pad = os.path.join(WERKMAP, f"{naam}-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    with open(pad, "w", encoding="utf-8") as f:
        json.dump([dict(r, versie=__version__, tijd=datetime.datetime.now().isoformat(timespec="seconds")) for r in regels],
                  f, indent=2, ensure_ascii=False)
    return pad


class Ophaling:
    def __init__(self, soort):
        self.id = f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{soort}-{secrets.token_hex(4)}"
        self.soort, self.status, self.gedaan, self.totaal, self.stap = soort, "bezig", 0, 0, "starten"
        self.resultaat, self.fout = None, None

    def voortgang(self, gedaan, totaal, stap):
        self.gedaan, self.totaal, self.stap = gedaan, totaal, stap

    def info(self):
        return {"id": self.id, "soort": self.soort, "status": self.status, "gedaan": self.gedaan, "totaal": self.totaal,
                "stap": self.stap, "fout": self.fout, "resultaat": self.resultaat if self.status == "klaar" else None}


def start_ophaling(sessie, soort, opties):
    """Start een lange taak op de achtergrond, met de verbinding van deze sessie. Enkel deze sessie ziet ze."""
    if soort == "wisplan":
        def doe(v):
            plan = configapi.wis_plan(opties.get("items"), opties.get("device_function") or "ACCESS_SWITCH", v)
            pid = f"wis-{datetime.datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(4)}"
            sessie.wisplannen[pid] = (plan["acties"], plan["device_function"])
            return dict(plan, id=pid)
    elif soort == "wissen":
        gevonden = sessie.wisplannen.pop(str(opties.get("plan") or ""), None)
        if gevonden is None:
            raise monitor.Invoer("Dit plan is verlopen of al uitgevoerd. Maak een nieuw plan.")
        acties, df = gevonden

        def doe(v):
            res = configapi.wis_uitvoeren(acties, df, v)
            pad = logboek("overrides-wissen-log", res)
            return {"resultaten": res, "logboek": os.path.relpath(pad, WERKMAP).replace(os.sep, "/") if pad else None,
                    "versie": __version__}
    elif soort == "afwijkingen":
        serials = [str(x) for x in (opties.get("serials") or []) if isinstance(x, (str, int))][:2000] or None
        doe = lambda v: configapi.afwijkingen_scan(serials, opties.get("device_function") or "ACCESS_SWITCH", v)  # noqa: E731
    else:
        raise monitor.Invoer("onbekende ophaling")
    if sum(x.status == "bezig" for x in sessie.ophalingen.values()) >= MAX_TAKEN:
        raise monitor.Invoer(f"Er lopen al {MAX_TAKEN} taken. Wacht tot er een klaar is.")
    klaar = [k for k, x in sessie.ophalingen.items() if x.status != "bezig"]
    for k in klaar[:max(0, len(sessie.ophalingen) - 20)]:      # oude resultaten niet eindeloos bijhouden
        sessie.ophalingen.pop(k, None)
    o = Ophaling(soort)
    sessie.ophalingen[o.id] = o

    def draai_ophaling():
        try:
            with cx.gebruik(sessie.verbinding):
                o.resultaat = doe(o.voortgang)
            o.status = "klaar"
        except monitor.ApiFout as e:
            o.fout, o.status = (e.melding if isinstance(e, monitor.Invoer) else f"Central gaf {e.status}: {e.melding}"), "fout"
        except Exception as e:  # noqa: BLE001
            o.fout, o.status = f"{type(e).__name__}: {e}", "fout"

    threading.Thread(target=draai_ophaling, daemon=True).start()
    return o


def maak_server(poort, adres="127.0.0.1"):
    """Probeert de poort en de negen volgende, voor als er al iets draait (in servermodus enkel de gevraagde poort)."""
    laatste = None
    for p in ([poort] if poort == 0 or SERVER else range(poort, poort + 10)):
        try:
            return ThreadingHTTPServer((adres, p), Handler)
        except OSError as e:
            laatste = e
    raise SystemExit(f"Geen vrije poort gevonden vanaf {poort}: {laatste}")


def main():
    global WERKMAP
    p = argparse.ArgumentParser(prog="cnx web", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--poort", type=int, default=POORT)
    p.add_argument("--geen-browser", action="store_true", help="de browser niet zelf openen")
    p.add_argument("--map", default=WERKMAP, help="map voor importbestanden en logboeken")
    p.add_argument("--zonder-opslag", action="store_true",
                   help="niets op schijf: importbestanden en logboeken enkel als download in de browser")
    p.add_argument("--server", action="store_true",
                   help="servermodus achter een reverse proxy: per gebruiker een sessie, niets op schijf, geen browser")
    p.add_argument("--adres", default=None, help="servermodus: adres om op te luisteren (standaard 0.0.0.0)")
    p.add_argument("--host-naam", action="append", default=[],
                   help="servermodus: hostnaam waarop de app bereikbaar is (meermaals; of CNX_HOSTS, komma's). '*' = elke")
    a = p.parse_args()
    global OPSLAG, SERVER, PER_SESSIE
    OPSLAG = not a.zonder_opslag
    if a.server:
        SERVER, PER_SESSIE, OPSLAG = True, True, False
        TOEGELATEN_HOSTS.update(h.strip().lower() for h in a.host_naam + os.environ.get("CNX_HOSTS", "").split(",") if h.strip())
        if not TOEGELATEN_HOSTS:
            raise SystemExit("Servermodus: geef de hostnaam van de app met --host-naam (of CNX_HOSTS), bv. cnx.voorbeeld.be.")
        if os.environ.get("CNX_CLIENT_ID") or os.environ.get("CNX_CLIENT_SECRET"):
            print("Let op: CNX_CLIENT_ID/CNX_CLIENT_SECRET worden in servermodus niet gebruikt; elke gebruiker meldt zelf aan.")
        poort = a.poort if a.poort != POORT else int(os.environ.get("PORT", "8080"))
        srv = maak_server(poort, a.adres or "0.0.0.0")
        print(f"CNX Toolkit {__version__} servermodus op {srv.server_address[0]}:{srv.server_address[1]}, "
              f"hosts: {', '.join(sorted(TOEGELATEN_HOSTS))}. Er wordt niets op schijf bewaard.")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nGestopt.")
        finally:
            srv.server_close()
        return
    WERKMAP = os.path.abspath(a.map)
    if OPSLAG:
        os.makedirs(WERKMAP, exist_ok=True)
    if os.environ.get("CNX_CLIENT_ID") and os.environ.get("CNX_CLIENT_SECRET") and os.environ.get("CNX_BASE_URL"):
        ok, msg = ov.aanmelden(os.environ["CNX_BASE_URL"], os.environ["CNX_CLIENT_ID"], os.environ["CNX_CLIENT_SECRET"])
        print(msg)
    srv = maak_server(a.poort)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"CNX Toolkit {__version__} draait op {url}  (Ctrl+C of dit venster sluiten om te stoppen)")
    print(f"Importbestanden en logboeken: {WERKMAP}" if OPSLAG else "Zonder opslag: er wordt niets op schijf bewaard.")
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

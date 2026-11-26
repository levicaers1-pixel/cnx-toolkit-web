"""GreenLake Onboarding: nieuwe toestellen in GreenLake zetten, aan new Central en een subscription toewijzen, en
daarna in Central aan een site, device group en device function. Eerst een plan (leest enkel), dan uitvoeren.

Het zijn aparte stappen met wachttijd ertussen, via twee API's:
  GreenLake (https://global.api.greenlake.hpe.com, eigen API-client "GreenLake platform"):
    GET   /devices/v1/devices                    filter=serialNumber in 'A', 'B'
    POST  /devices/v1/devices                    {"network": [{serialNumber, macAddress}], "compute": [], "storage": []}, 5 per keer
    PATCH /devices/v1/devices?id=..&id=..         {"application": {"id"}, "region"} of {"subscription": [{"id"}]}, 5 per keer
    GET   /devices/v1/async-operations/{id}      de POST en PATCH zijn asynchroon (202 + Location)
    GET   /service-catalog/v1/service-manager-provisions, /service-catalog/v1/service-managers
    GET   /subscriptions/v1/subscriptions
  new Central (de gewone aanmelding rechtsboven):
    GET   /network-monitoring/v1/device-inventory
    POST  /network-config/v1/site-add-devices, /network-config/v1/device-groups-add-devices
    POST  /network-config/v1alpha1/persona-assignment/{device-function}

Volgens developer.greenlake.hpe.com en developer.arubanetworks.com (november 2026). Te bevestigen in een lab: welk id
GreenLake als application.id verwacht (hier: het id van de service manager, met de regio apart) en de vorm van het
resultaat van een asynchrone bewerking. Daarom is er een proef: GreenLake's dry-run, die niets wijzigt.
"""
import base64
import csv
import io
import re
import time

from . import alias_api as cx
from . import aos8, monitor
from .apafwerking import _scopes
from .monitor import ApiFout, Invoer
from .taal import _

GLP = "https://global.api.greenlake.hpe.com"
MON = "/network-monitoring/v1"
SCOPE = "/network-config/v1"
CFG = "/network-config/v1alpha1"
MAX_RIJEN = 2000
PER_KEER = 5                     # GreenLake: hoogstens vijf toestellen per POST of PATCH
PAUZE_POST = 1.3                 # 50 per minuut per workspace
PAUZE_PATCH = 1.6                # 40 per minuut per workspace
WACHT_ASYNC = 300                # seconden per asynchrone bewerking
WACHT_CENTRAL = 600              # zo lang wachten tot nieuwe toestellen in Central verschijnen
SERIAL = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
WORKSPACE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
FUNCTIES = {"ACCESS_SWITCH": "SWITCH", "AGG_SWITCH": "SWITCH", "CORE_SWITCH": "SWITCH", "CAMPUS_AP": "AP",
            "MICROBRANCH_AP": "AP", "MOBILITY_GW": "GATEWAY", "BRANCH_GW": "GATEWAY"}
SOORTEN = ("AP", "SWITCH", "GATEWAY")
slaap = time.sleep               # vervangbaar in de tests


# ---------------------------------------------------------------- invoer: CSV, geplakte tabel of xlsx

KOP = {"serial": ("serial", "serialnumber", "serienummer", "serialno", "sn"),
       "mac": ("mac", "macaddress", "macadres", "wiredmacaddress", "ethmac"),
       "soort": ("soort", "type", "devicetype", "toesteltype"),
       "site": ("site", "sitename"),
       "groep": ("devicegroup", "devicegroupname", "groep", "group"),
       "functie": ("functie", "function", "devicefunction", "persona"),
       "subscription": ("subscription", "subscriptionkey", "licentie", "license", "licence", "key"),
       "naam": ("naam", "name", "hostname", "devicename")}


def _kop(t):
    t = re.sub(r"[\s_#\-.]", "", str(t or "").lower())
    return next((k for k, namen in KOP.items() if t in namen), None)


def _functie(t):
    n = re.sub(r"[\s_-]+", "_", str(t or "").strip().upper())
    if not n:
        return ""
    if n in FUNCTIES:
        return n
    for begin, f in (("ACCESS", "ACCESS_SWITCH"), ("AGG", "AGG_SWITCH"), ("CORE", "CORE_SWITCH"), ("MOBILITY", "MOBILITY_GW"),
                     ("BRANCH", "BRANCH_GW"), ("MICROBRANCH", "MICROBRANCH_AP"), ("CAMPUS", "CAMPUS_AP"), ("AP", "CAMPUS_AP")):
        if n.startswith(begin):
            return f
    return None


def _soort(t):
    n = str(t or "").strip().upper()
    if not n:
        return ""
    if n in ("AP", "ACCESS_POINT", "ACCESS POINT", "IAP") or n.startswith("AP-"):
        return "AP"
    if "SWITCH" in n or n in ("CX", "SW"):
        return "SWITCH"
    if "GATEWAY" in n or n in ("GW", "CONTROLLER"):
        return "GATEWAY"
    return None


def mac(t):
    h = re.sub(r"[^0-9a-f]", "", str(t or "").lower())
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)) if len(h) == 12 else ""


def _tabel(rijen):
    """De eerste rij met een kolom serienummer is de kop; daarna de toestellen."""
    for i, rij in enumerate(rijen[:20]):
        kol = [_kop(c) for c in rij]
        if "serial" in kol:
            return kol, rijen[i + 1:]
    raise Invoer(_("Geen kolom met het serienummer gevonden (Serial, Serienummer)."))


def lees(bestand=None, tekst=None):
    """Toestellen uit een CSV-, tekst- of xlsx-bestand of uit geplakte tekst, nagekeken. Bewaart niets."""
    if bestand:
        if not isinstance(bestand, dict):
            raise Invoer(_("ongeldig bestand"))
        try:
            data = base64.b64decode(str(bestand.get("inhoud") or ""), validate=False)
        except ValueError:
            raise Invoer(_("ongeldig bestand"))
        if str(bestand.get("naam") or "").lower().endswith(".xlsx"):
            try:
                bladen = aos8.lees_xlsx(data)
            except aos8.Fout as e:
                raise Invoer(str(e))
            rijen = next((r for r in bladen.values() if any("serial" in [_kop(c) for c in rij] for rij in r[:20])), None)
            if rijen is None:
                raise Invoer(_("Geen kolom met het serienummer gevonden (Serial, Serienummer)."))
        else:
            tekst = data.decode("utf-8-sig", errors="replace")
    if not bestand:
        tekst = str(tekst or "")
        if len(tekst) > 2_000_000:
            raise Invoer(_("te veel tekst"))
        eerste = tekst.strip().splitlines()[0] if tekst.strip() else ""
        scheid = "\t" if "\t" in eerste else ";" if eerste.count(";") > eerste.count(",") else ","
        rijen = list(csv.reader(io.StringIO(tekst), delimiter=scheid))
    kol, data_rijen = _tabel(rijen)
    uit, fouten, gezien_s, gezien_m = [], [], {}, {}
    for nr, rij in enumerate(data_rijen, 1):
        if not any(str(c).strip() for c in rij):
            continue
        if len(uit) >= MAX_RIJEN:
            fouten.append(_("Meer dan {n} toestellen: de rest is niet ingelezen.", n=MAX_RIJEN))
            break
        r = {k: "" for k in KOP}
        for k, c in zip(kol, rij):
            if k and str(c).strip():
                r[k] = str(c).strip()
        r["serial"] = r["serial"].upper()
        f = []
        if not SERIAL.match(r["serial"]):
            f.append(_("ongeldig serienummer"))
        r["mac"] = mac(r["mac"])
        if not r["mac"]:
            f.append(_("MAC-adres ontbreekt of is ongeldig"))
        functie = _functie(r["functie"])
        if functie is None:
            f.append(_("onbekende device function '{f}'", f=r["functie"]))
            functie = ""
        soort = _soort(r["soort"])
        if soort is None:
            f.append(_("onbekende soort '{s}' (AP, switch of gateway)", s=r["soort"]))
            soort = ""
        soort = soort or FUNCTIES.get(functie, "")
        if functie and soort and FUNCTIES[functie] != soort:
            f.append(_("device function {f} past niet bij soort {s}", f=functie, s=soort))
        if soort == "AP" and not functie:
            functie = "CAMPUS_AP"
        if not soort:
            f.append(_("soort onbekend: vul de kolom soort of device function in"))
        r.update(functie=functie, soort=soort)
        for sleutel, gezien, wat in (("serial", gezien_s, _("serienummer")), ("mac", gezien_m, "MAC")):
            if r[sleutel] and r[sleutel] in gezien:
                f.append(_("{wat} staat ook op rij {rij}", wat=wat, rij=gezien[r[sleutel]]))
            elif r[sleutel]:
                gezien[r[sleutel]] = nr
        r["rij"], r["fouten"] = nr, f
        uit.append(r)
    if not uit:
        raise Invoer(_("Geen toestellen gevonden onder de kop."))
    return {"rijen": uit, "fouten": fouten}


# ---------------------------------------------------------------- GreenLake: verzoeken

def _verzend(v, method, url, params, body, kop):
    return v.s.request(method, url, params=params, json=body, headers=kop, timeout=60)


def glp(method, pad, params=None, body=None, kop=None):
    """Een verzoek aan GreenLake met de GreenLake-verbinding (cx.gebruik). 401: token vernieuwen; 429 en 5xx: opnieuw."""
    v = cx.verbinding()
    url = pad if pad.startswith("https://") else GLP + pad
    if not url.startswith(GLP + "/"):
        raise Invoer(_("onverwacht adres van GreenLake"))
    for poging in range(6):
        r = _verzend(v, method, url, params, body, kop)
        if r.status_code == 401 and v.gegevens and poging == 0:
            with v.slot:
                fout = cx._token(v, v.gegevens["id"], v.gegevens["secret"])
            if fout:
                return r
            continue
        if (r.status_code == 429 or r.status_code >= 500) and poging < 5:
            slaap(min(2 ** poging, 30))
            continue
        return r
    return r


def _json(r):
    try:
        return r.json()
    except ValueError:
        return None


def _melding(r):
    j = _json(r)
    if isinstance(j, dict):
        return str(j.get("message") or j.get("errorCode") or r.text[:200])
    return r.text[:200]


def _lees(pad, params=None):
    r = glp("GET", pad, params)
    if r.status_code >= 300:
        raise ApiFout(r.status_code, _melding(r))
    return _json(r) or {}


def _alles(pad, params=None, limit=200):
    items, off = [], 0
    for _pagina in range(100):
        j = _lees(pad, dict(params or {}, limit=limit, offset=off))
        nieuw = j.get("items") or [] if isinstance(j, dict) else []
        items += [x for x in nieuw if isinstance(x, dict)]
        total = j.get("total") if isinstance(j, dict) else None
        if not nieuw or (total is not None and len(items) >= int(total)) or len(nieuw) < limit:
            break
        off += len(nieuw)
    return items


def token_url(workspace):
    """De token-URL voor een API-client van het GreenLake-platform met workspace-ID (developer.arubanetworks.com,
    Generating and managing access tokens), of None voor de gewone (sso.common.cloud.hpe.com)."""
    workspace = str(workspace or "").strip()
    if not workspace:
        return None
    if not WORKSPACE.match(workspace):
        raise Invoer(_("ongeldige workspace-ID"))
    return f"{GLP}/authorization/v2/oauth2/{workspace}/token"


def aanmelden(v, cid, secret, workspace=""):
    """Meldt aan bij GreenLake met een API-client van het GreenLake-platform en kijkt na dat hij toestellen mag lezen."""
    url = token_url(workspace)
    v.base = GLP
    v.gegevens.clear()
    v.gedeeld = False
    fout = cx._token(v, str(cid or ""), str(secret or ""), url)
    if fout:
        return False, fout
    v.gegevens.update(id=str(cid), secret=str(secret))
    if url:
        v.gegevens["token_url"] = url
    with cx.gebruik(v):
        r = glp("GET", "/devices/v1/devices", {"limit": 1})
    if r.status_code >= 300:
        v.wis()
        return False, _("Aangemeld, maar deze API-client mag geen toestellen lezen in GreenLake ({status}: {melding}). Maak een API-client voor de dienst GreenLake platform.",
                        status=r.status_code, melding=_melding(r))
    return True, _("aangemeld")


def aanmelden_met_workspace(v, cid, secret, workspace):
    """Een API-client van het GreenLake-platform, rechtsboven aangemeld met workspace-ID: dezelfde client krijgt ook
    een token voor de GreenLake-API. Eerst via het gewone aanmeldadres (sso.common.cloud.hpe.com), anders via de
    workspace. Geeft (ok, melding)."""
    ok, melding = aanmelden(v, cid, secret, "")
    if not ok:
        ok, tweede = aanmelden(v, cid, secret, workspace)
        if not ok:
            return False, melding
    v.gedeeld = True
    return True, _("aangemeld")


def gebruik_central(v, central):
    """Mag de aanmelding bij Central ook in GreenLake? Dat kan met een API-client van het GreenLake-platform (volgens
    HPE kan die ook de Central-API aanroepen). Zo ja: de GreenLake-verbinding krijgt hetzelfde token en dezelfde
    gegevens, en er is geen tweede aanmelding nodig. Leest enkel."""
    if not central.aangemeld:
        return False
    proef = cx.Verbinding(GLP)
    proef.s.headers.update({k: w for k, w in central.s.headers.items() if k in ("Authorization", "Content-Type")})
    proef.gegevens.update(central.gegevens)
    with cx.gebruik(proef):
        r = glp("GET", "/devices/v1/devices", {"limit": 1})
    if r.status_code >= 300:
        return False
    v.base = GLP
    v.s.headers.update({k: w for k, w in proef.s.headers.items() if k in ("Authorization", "Content-Type")})
    v.gegevens.clear()
    v.gegevens.update(proef.gegevens)
    v.gedeeld = True
    return True


def keuzes(v):
    """De applicaties (Central per regio) en de lopende subscriptions in GreenLake."""
    with cx.gebruik(v):
        namen = {str(x.get("id")): str(x.get("name") or "") for x in _alles("/service-catalog/v1/service-managers")}
        apps = []
        for p in _alles("/service-catalog/v1/service-manager-provisions"):
            sm = p.get("serviceManager") or {}
            if str(p.get("provisionStatus") or "") not in ("", "PROVISIONED"):
                continue
            apps.append({"id": str(sm.get("id") or ""), "naam": namen.get(str(sm.get("id")), "") or str(sm.get("id") or ""),
                         "regio": str(p.get("region") or "")})
        apps = [a for a in apps if a["id"] and a["regio"]]
        apps.sort(key=lambda a: ("central" not in a["naam"].lower(), a["naam"], a["regio"]))
        subs = []
        for s in _alles("/subscriptions/v1/subscriptions", {"filter": "subscriptionStatus eq 'STARTED'"}):
            try:
                vrij = int(float(s.get("availableQuantity") or 0))
            except (TypeError, ValueError):
                vrij = 0
            subs.append({"id": str(s.get("id") or ""), "key": str(s.get("key") or ""), "type": str(s.get("subscriptionType") or ""),
                         "tier": str(s.get("tier") or ""), "vrij": vrij, "totaal": str(s.get("quantity") or ""),
                         "einde": str(s.get("endTime") or "")[:10], "eval": bool(s.get("isEval"))})
        subs.sort(key=lambda s: (s["type"], s["tier"], s["einde"]))
    return {"applicaties": apps, "subscriptions": [s for s in subs if s["id"]]}


def _glp_toestellen(serials):
    """{serial: toestel} uit GreenLake, per twintig."""
    uit = {}
    for i in range(0, len(serials), 20):
        deel = serials[i:i + 20]
        f = "serialNumber in " + ", ".join(f"'{s}'" for s in deel)
        for d in _alles("/devices/v1/devices", {"filter": f}):
            if d.get("serialNumber"):
                uit[str(d["serialNumber"]).upper()] = d
    return uit


def _app_id(d):
    a = d.get("application")
    return str(a.get("id") or "") if isinstance(a, dict) else ""


def _subs(d):
    return [s for s in (d.get("subscription") or []) if isinstance(s, dict)] if isinstance(d.get("subscription"), list) else []


# ---------------------------------------------------------------- plan

def plan(v, rijen, keuze, centraal_aangemeld, voortgang=lambda *a: None):
    """Wat er per toestel moet gebeuren. Leest enkel, in GreenLake en (als je aangemeld bent) in Central."""
    rijen = [r for r in (rijen if isinstance(rijen, list) else []) if isinstance(r, dict)][:MAX_RIJEN]
    rijen = [r for r in rijen if SERIAL.match(str(r.get("serial") or "")) and mac(r.get("mac")) and r.get("soort") in SOORTEN]
    if not rijen:
        raise Invoer(_("Lees eerst een lijst met toestellen in."))
    keuze = keuze if isinstance(keuze, dict) else {}
    app = str(keuze.get("applicatie") or "")
    app_id, _sep, regio = app.partition("|")
    sub_per_soort = {s: str((keuze.get("subscriptions") or {}).get(s) or "") for s in SOORTEN}
    voortgang(0, 4, _("toestellen zoeken in GreenLake"))
    with cx.gebruik(v):
        in_glp = _glp_toestellen([str(r["serial"]).upper() for r in rijen])
        voortgang(1, 4, _("subscriptions lezen"))
        alle_subs = {s["id"]: s for s in keuzes(v)["subscriptions"]}
    op_key = {s["key"]: s for s in alle_subs.values() if s["key"]}
    inv, sites, groepen = {}, {}, {}
    if centraal_aangemeld:
        voortgang(2, 4, _("toestellen, sites en device groups lezen in Central"))
        for d in monitor.alles_next(MON + "/device-inventory", {"limit": 1000})["items"]:
            if isinstance(d, dict) and d.get("serialNumber"):
                inv[str(d["serialNumber"]).upper()] = d
        sites, groepen = _scopes("/sites"), _scopes("/device-groups")
    voortgang(3, 4, _("plan maken"))
    acties, geweigerd, gelijk, nodig = [], [], 0, {}
    for r in rijen:
        s = str(r["serial"]).upper()
        d, c = in_glp.get(s), inv.get(s)
        x = {"serial": s, "mac": mac(r["mac"]), "soort": r["soort"], "naam": str(r.get("naam") or ""),
             "glp_id": str((d or {}).get("id") or ""), "in_glp": d is not None, "in_central": c is not None,
             "toevoegen": d is None, "app_id": "", "regio": "", "sub_id": "", "sub_key": "",
             "site_nu": str((c or {}).get("siteName") or ""), "site": "", "site_id": "",
             "groep_nu": str((c or {}).get("deviceGroupName") or ""), "dg": "", "dg_id": "",
             "functie_nu": str((c or {}).get("deviceFunction") or ""), "functie": ""}
        if d is not None and mac(d.get("macAddress")) and mac(d.get("macAddress")) != x["mac"]:
            geweigerd.append(_("{s}: staat in GreenLake met een ander MAC-adres ({mac})", s=s, mac=d.get("macAddress")))
            continue
        # applicatie (Central in een regio)
        nu = _app_id(d or {})
        if app_id and nu and nu != app_id:
            geweigerd.append(_("{s}: is in GreenLake al aan een andere applicatie toegewezen; de toolkit verhuist geen toestellen", s=s))
        elif app_id and not nu:
            x["app_id"], x["regio"] = app_id, regio
        # subscription: de key uit de lijst, anders de keuze voor deze soort
        if not _subs(d or {}):
            sub = op_key.get(str(r.get("subscription") or "")) if r.get("subscription") else alle_subs.get(sub_per_soort[r["soort"]])
            if r.get("subscription") and sub is None:
                geweigerd.append(_("{s}: subscription {key} niet gevonden of niet actief", s=s, key=r["subscription"]))
            elif sub is not None:
                x["sub_id"], x["sub_key"] = sub["id"], sub["key"]
                nodig[sub["id"]] = nodig.get(sub["id"], 0) + 1
        # Central: site, device group, device function
        for veld, bron, lijst, nu_veld, id_veld in (("site", "site", sites, "site_nu", "site_id"), ("dg", "groep", groepen, "groep_nu", "dg_id")):
            doel = str(r.get(bron) or "").strip()
            if not doel or doel == x[nu_veld]:
                continue
            if not centraal_aangemeld:
                geweigerd.append(_("{s}: meld aan bij Central om site en device group na te kijken", s=s))
                break
            if doel not in lijst:
                geweigerd.append(_("{s}: '{doel}' bestaat niet in Central", s=s, doel=doel))
            else:
                x[veld], x[id_veld] = doel, lijst[doel]
        if r.get("functie") and r["functie"] != x["functie_nu"] and not (r["soort"] == "AP" and r["functie"] == "CAMPUS_AP"):
            x["functie"] = r["functie"]               # APs krijgen hun functie vanzelf
        if x["toevoegen"] or x["app_id"] or x["sub_id"] or x["site"] or x["dg"] or x["functie"]:
            acties.append(x)
        else:
            gelijk += 1
    for sid, n in nodig.items():
        s = alle_subs[sid]
        if n > s["vrij"]:
            geweigerd.append(_("subscription {key}: {n} nodig, {vrij} vrij", key=s["key"] or sid, n=n, vrij=s["vrij"]))
    voortgang(4, 4, _("klaar"))
    return {"acties": acties, "geweigerd": geweigerd, "gelijk": gelijk, "toestellen": len(rijen),
            "in_glp": sum(1 for r in rijen if str(r["serial"]).upper() in in_glp), "centraal": centraal_aangemeld,
            "subscriptions": [dict(alle_subs[s], nodig=n) for s, n in nodig.items()]}


# ---------------------------------------------------------------- uitvoeren

def _wacht_async(r):
    """Wacht op een asynchrone bewerking van GreenLake (202 + Location). Geeft (status, resultaat)."""
    loc = r.headers.get("Location") or r.headers.get("location") or ""
    if not loc:
        j = _json(r) or {}
        tid = j.get("transactionId") if isinstance(j, dict) else None
        loc = f"/devices/v1/async-operations/{tid}" if tid else ""
    if not loc:
        return "SUCCEEDED", None
    if not loc.startswith("/") and not loc.startswith(GLP + "/"):
        return "FAILED", _("onverwacht adres van GreenLake")
    einde = time.time() + WACHT_ASYNC
    while True:
        a = glp("GET", loc)
        j = _json(a) if a.status_code < 300 else None
        status = str((j or {}).get("status") or "").upper()
        if status in ("SUCCEEDED", "FAILED", "TIMEOUT", "TIMEDOUT"):
            return status, j.get("result")
        if a.status_code >= 300 and a.status_code != 429:
            return "FAILED", _melding(a)
        if time.time() > einde:
            return "TIMEOUT", None
        try:
            pauze = int((j or {}).get("suggestedPollingIntervalSeconds") or 3)
        except (TypeError, ValueError):
            pauze = 3
        slaap(max(2, min(pauze, 10)))


def _fout_serials(result, serials):
    """Welke serienummers in het resultaat onder een mislukking staan. De vorm van het resultaat staat niet vast in de
    documentatie: zoek de serienummers onder sleutels met fail/error."""
    fout = {}

    def zoek(o, slecht, melding):
        if isinstance(o, dict):
            m = str(o.get("message") or o.get("reason") or o.get("errorMessage") or melding or "")
            for k, w in o.items():
                zoek(w, slecht or bool(re.search(r"fail|error|unsuccess", str(k), re.I)), m)
        elif isinstance(o, list):
            for w in o:
                zoek(w, slecht, melding)
        elif isinstance(o, str) and slecht and o.upper() in serials:
            fout[o.upper()] = melding
    zoek(result, False, "")
    return fout


def _stap_glp(methode, pad, params, body, kop, serials, pauze):
    """Een POST of PATCH naar GreenLake en wachten op het resultaat. Geeft {serial: uitslag}."""
    r = glp(methode, pad, params, body, kop)
    slaap(pauze)
    if r.status_code >= 300:
        t = _("fout {code}: {melding}", code=r.status_code, melding=_melding(r))
        return {s: t for s in serials}
    status, result = _wacht_async(r) if r.status_code == 202 else ("SUCCEEDED", None)
    fout = _fout_serials(result, set(serials))
    if status == "SUCCEEDED":
        return {s: (_("fout: {m}", m=fout[s]) if s in fout else "ok") for s in serials}
    t = _("GreenLake: {status}", status=status) + (f" ({result})" if isinstance(result, str) else "")
    return {s: (_("fout: {m}", m=fout[s]) if s in fout else t) for s in serials}


def uitvoeren(v, acties, proef=True, voortgang=lambda *a: None):
    """Voert een plan uit. Proef: GreenLake doet een dry-run (wijzigt niets) en Central wordt overgeslagen."""
    acties = [dict(a) for a in acties if isinstance(a, dict) and a.get("serial")]
    for a in acties:
        a.update(toevoegen_uit="", app_uit="", sub_uit="", site_uit="", dg_uit="", functie_uit="")
    op = {a["serial"]: a for a in acties}
    dry = {"dry-run": "true"} if proef else None
    totaal = len(acties) * 3 + 2
    with cx.gebruik(v):
        # 1. toevoegen aan de inventaris van GreenLake
        nieuw = [a for a in acties if a["toevoegen"]]
        for i in range(0, len(nieuw), PER_KEER):
            deel = nieuw[i:i + PER_KEER]
            voortgang(i, totaal, _("{n} toestellen toevoegen in GreenLake", n=len(deel)))
            body = {"network": [{"serialNumber": a["serial"], "macAddress": a["mac"]} for a in deel], "compute": [], "storage": []}
            for s, u in _stap_glp("POST", "/devices/v1/devices", dry, body, None, [a["serial"] for a in deel], PAUZE_POST).items():
                op[s]["toevoegen_uit"] = u
        # de id's van de nieuwe toestellen (GreenLake heeft even nodig)
        zonder_id = [a["serial"] for a in acties if not a["glp_id"] and a["toevoegen_uit"] == "ok" and not proef]
        einde = time.time() + 120
        while zonder_id and time.time() < einde:
            voortgang(len(nieuw), totaal, _("wachten tot GreenLake de nieuwe toestellen toont"))
            for s, d in _glp_toestellen(zonder_id).items():
                if s in op and d.get("id"):
                    op[s]["glp_id"] = str(d["id"])
            zonder_id = [s for s in zonder_id if not op[s]["glp_id"]]
            if zonder_id:
                slaap(5)
        # 2. applicatie en regio, 3. subscription: aparte bewerkingen (GreenLake doet er een per keer)
        kop = {"Content-Type": "application/merge-patch+json"}
        for veld, uit, body_van in (("app_id", "app_uit", lambda a: {"application": {"id": a["app_id"]}, "region": a["regio"]}),
                                    ("sub_id", "sub_uit", lambda a: {"subscription": [{"id": a["sub_id"]}]})):
            groepen = {}
            for a in acties:
                if not a[veld]:
                    continue
                if a["toevoegen"] and a["toevoegen_uit"] != "ok":
                    a[uit] = _("niet gedaan: toevoegen mislukte")
                elif not a["glp_id"]:
                    a[uit] = _("proef: kan pas na het toevoegen") if proef else _("niet gedaan: geen id in GreenLake")
                else:
                    groepen.setdefault(str(body_van(a)), (body_van(a), []))[1].append(a)
            for body, lijst in groepen.values():
                for i in range(0, len(lijst), PER_KEER):
                    deel = lijst[i:i + PER_KEER]
                    voortgang(len(nieuw), totaal, _("{n} toestellen bijwerken in GreenLake", n=len(deel)))
                    params = dict(dry or {}, id=[a["glp_id"] for a in deel])
                    for s, u in _stap_glp("PATCH", "/devices/v1/devices", params, body, kop, [a["serial"] for a in deel], PAUZE_PATCH).items():
                        op[s][uit] = u
    # 4. Central: wachten tot de toestellen er zijn, dan site, device group en device function
    central = [a for a in acties if a["site"] or a["dg"] or a["functie"]]
    if proef:
        for a in central:
            for veld, uit in (("site", "site_uit"), ("dg", "dg_uit"), ("functie", "functie_uit")):
                if a[veld]:
                    a[uit] = _("proef: niet gedaan in Central")
        return acties
    inv, einde = {}, time.time() + WACHT_CENTRAL
    while central:
        voortgang(len(acties) * 2, totaal, _("wachten tot de toestellen in Central staan"))
        inv = {str(d.get("serialNumber") or "").upper(): d for d in monitor.alles_next(MON + "/device-inventory", {"limit": 1000})["items"] if isinstance(d, dict)}
        if all(a["serial"] in inv for a in central) or time.time() > einde:
            break
        slaap(20)
    klaar = [a for a in central if a["serial"] in inv]
    for a in central:
        if a["serial"] not in inv:
            for veld, uit in (("site", "site_uit"), ("dg", "dg_uit"), ("functie", "functie_uit")):
                if a[veld]:
                    a[uit] = _("niet gedaan: staat na {min} minuten nog niet in Central; maak later een nieuw plan", min=WACHT_CENTRAL // 60)
    for uit, veld, pad in (("site_uit", "site_id", SCOPE + "/site-add-devices"), ("dg_uit", "dg_id", SCOPE + "/device-groups-add-devices")):
        per = {}
        for a in klaar:
            if a[veld]:
                per.setdefault(a[veld], []).append(a)
        for scope_id, lijst in per.items():
            for i in range(0, len(lijst), 50):
                deel = lijst[i:i + 50]
                voortgang(len(acties) * 2, totaal, _("{n} toestellen toewijzen in Central", n=len(deel)))
                r = cx.api("POST", pad, None, {"desScopeId": scope_id, "devices": [a["serial"] for a in deel]})
                t = "ok" if r.status_code < 300 else _("fout {code}: {melding}", code=r.status_code, melding=_melding(r))
                for a in deel:
                    a[uit] = t
    per = {}
    for a in klaar:
        if a["functie"]:
            per.setdefault(a["functie"], []).append(a)
    for f, lijst in per.items():
        for i in range(0, len(lijst), 50):
            deel = lijst[i:i + 50]
            voortgang(len(acties) * 2, totaal, _("device function {f} toewijzen", f=f))
            r = cx.api("POST", f"{CFG}/persona-assignment/{f}", None, {"device-function": f, "device-id": [a["serial"] for a in deel]})
            t = "ok" if r.status_code < 300 else _("fout {code}: {melding}", code=r.status_code, melding=_melding(r))
            for a in deel:
                a["functie_uit"] = t
    # 5. nakijken in Central
    if klaar:
        voortgang(totaal - 1, totaal, _("nakijken in Central"))
        inv = {str(d.get("serialNumber") or "").upper(): d for d in monitor.alles_next(MON + "/device-inventory", {"limit": 1000})["items"] if isinstance(d, dict)}
        for a in klaar:
            d = inv.get(a["serial"]) or {}
            for veld, uit, centraal in (("site", "site_uit", "siteName"), ("dg", "dg_uit", "deviceGroupName"), ("functie", "functie_uit", "deviceFunction")):
                if a[veld] and a[uit] == "ok" and str(d.get(centraal) or "") != a[veld]:
                    a[uit] = _("Central meldde ok, maar toont nog {nu}", nu=d.get(centraal) or "-")
    voortgang(totaal, totaal, _("klaar"))
    return acties

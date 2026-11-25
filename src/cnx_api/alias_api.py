#!/usr/bin/env python3
"""Aliassen aanmaken en opkuisen via de API van new Central. De bulk-upload kan dat niet.

Standaard een dry-run: niets wordt geschreven zonder --apply. Staat op zichzelf, enkel de module requests is nodig.

  export CNX_BASE_URL=https://de1.api.central.arubanetworks.com
  export CNX_CLIENT_ID=...  CNX_CLIENT_SECRET=...

Vastgesteld op 12 november 2026 (labtest): een alias is een LOCAL object op een scope, met zijn waarde in
default-value. Een alias "op Global" is een LOCAL object op de scope Global. Er is geen toewijzing nodig.

Stap 0, alleen-lezen: hoe ziet een alias eruit
  cnx api lees --naam sys_vlan_2006_description --serial <SERIAL>
  cnx api lees --naam TEST_VLAN_DESCR --global

Library (gedeeld) in plaats van lokaal op Global:
  cnx api toewijzingen                              alleen-lezen: hoe ziet een toewijzing aan Global eruit
  cnx api aanmaken --waarden ... --library [--alleen ...] [--apply]
  cnx api toewijzen --waarden ... [--alleen ...] [--apply]          toewijzing aan Global nakijken en zetten
  cnx api global-lokaal-weg --waarden ... [--alleen ...] [--apply]   lokale kopie op Global opruimen
  cnx api naar-library --waarden ... --serial <SERIAL> [--alleen ...] [--apply]
        voor switches die de lokale kopie op Global gebruiken: tijdelijk lokaal op de switch, kopie op Global weg,
        lokale waarde op de switch weer weg. De switch erft daarna de library-alias.

VLAN-profielen op Global ook voor andere device functions:
  cnx api vlans-doorzetten [--naar AGG_SWITCH --naar CORE_SWITCH] [--ook-beschrijvingen] [--apply]
  cnx api vlans-terugdraaien --log alias-api-log-<tijd>.json [--apply]

Stap 1: aliassen aanmaken op Global
  cnx api aanmaken --waarden 06-globaal/2-global-waarden.csv [--alleen sys_vlan_2006_description] [--apply]

Stap 2: lokale waarden op de switches verwijderen, zodat ze Global erven
  cnx api opkuisen --lijst 06-globaal/3-opkuis-per-switch.csv [--serial <SERIAL>] [--apply]

Gekende structuur: ALIAS_VLAN_DESCRIPTION. Voor een ander type met een waarde: --sjabloon <alias die al op Global staat>
en --sjabloon-waarde <de waarde erin>. Types met meerdere rijen per alias (ALIAS_DNS_RESOLVER) slaat het script over:
zet de DNS-servers beter in een gewoon DNS-profiel op Global.
"""
import argparse, contextlib, contextvars, copy, csv, datetime, json, os, sys, threading, time
from urllib.parse import quote

try:
    import requests
except ImportError:
    sys.exit("De module 'requests' ontbreekt. Installeer ze met:  python -m pip install requests")

# ---------------------------------------------------------------- API (zelfde werking als cx_push.py)

PREFIX = "/network-config/v1alpha1"
TOKEN_URL = os.environ.get("CNX_TOKEN_URL", "https://sso.common.cloud.hpe.com/as/token.oauth2")
FUNC = {"ACCESS SWITCH": "ACCESS_SWITCH", "AGGREGATION SWITCH": "AGG_SWITCH", "CORE SWITCH": "CORE_SWITCH",
        "MOBILITY GATEWAY": "MOBILITY_GW", "MOBILITY GW": "MOBILITY_GW"}
LOG = []


class Verbinding:
    """Een aanmelding bij new Central: URL, HTTP-sessie met token, en de gegevens om een verlopen token te vernieuwen.
    De gegevens (client-ID en secret) staan enkel in het geheugen. Elke gebruiker van de webapp kan een eigen
    verbinding hebben; de commandolijn en de lokale webapp gebruiken de standaardverbinding."""

    def __init__(self, base=""):
        self.base = (base or "").rstrip("/")
        self.s = requests.Session()
        self.gegevens = {}
        self.slot = threading.Lock()          # een token tegelijk vernieuwen
        self.cache = {}                       # leesgegevens uit Central, per verbinding (zie configapi)

    @property
    def aangemeld(self):
        return "Authorization" in self.s.headers

    def wis(self):
        self.s.headers.pop("Authorization", None)
        self.gegevens.clear()
        self.cache.clear()


_STANDAARD = Verbinding(os.environ.get("CNX_BASE_URL", ""))
_HUIDIG = contextvars.ContextVar("cnx_verbinding", default=None)


def verbinding():
    """De verbinding van de lopende aanvraag, anders de standaardverbinding."""
    return _HUIDIG.get() or _STANDAARD


@contextlib.contextmanager
def gebruik(v):
    """Alles binnen dit blok (ook cx.api in andere modules) gaat via verbinding v."""
    t = _HUIDIG.set(v)
    try:
        yield v
    finally:
        _HUIDIG.reset(t)


def __getattr__(naam):
    """cx.S en cx.BASE blijven werken: ze geven de sessie en de URL van de huidige verbinding."""
    if naam == "S":
        return verbinding().s
    if naam == "BASE":
        return verbinding().base
    raise AttributeError(f"module {__name__!r} has no attribute {naam!r}")


def _token(v, cid, secret):
    """Haalt een token en zet het op de sessie van verbinding v. Geeft None, of de foutmelding."""
    r = requests.post(TOKEN_URL, timeout=30, data={"grant_type": "client_credentials",
                                                   "client_id": cid, "client_secret": secret})
    if r.status_code >= 300:
        return f"Aanmelden mislukt ({r.status_code}): {r.text[:300]}"
    v.s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}", "Content-Type": "application/json"})
    return None


def aanmelden(base, cid, secret):
    v = verbinding()
    v.base = base.rstrip("/")
    fout = _token(v, cid, secret)
    if fout:
        return False, fout
    v.gegevens.clear()
    v.gegevens.update(id=cid, secret=secret)
    v.cache.clear()
    return True, "aangemeld"


def afmelden():
    verbinding().wis()


def login():
    ontbreekt = [k for k in ("CNX_BASE_URL", "CNX_CLIENT_ID", "CNX_CLIENT_SECRET") if not os.environ.get(k)]
    if ontbreekt:
        sys.exit("Zet eerst: " + ", ".join(ontbreekt) + ". Zie LEESMIJ.md of 'cnx hulp'.")
    ok, melding = aanmelden(os.environ["CNX_BASE_URL"], os.environ["CNX_CLIENT_ID"], os.environ["CNX_CLIENT_SECRET"])
    if not ok:
        sys.exit(melding)


def api(method, path, params=None, body=None):
    """Een 401 (token verlopen) vernieuwt het token een keer en probeert opnieuw. Central weigert een aanvraag met
    een verlopen token voor ze iets doet, dus opnieuw sturen is veilig, ook voor POST en DELETE."""
    v = verbinding()
    r = _api(method, path, params, body)
    if r.status_code == 401 and v.gegevens:
        print("      401: token verlopen, opnieuw aanmelden")
        with v.slot:
            fout = _token(v, v.gegevens["id"], v.gegevens["secret"])
        if fout:
            print(f"      {fout}")
            return r
        r = _api(method, path, params, body)
    return r


def _api(method, path, params=None, body=None):
    """429 en 5xx: opnieuw proberen (DELETE maximaal 2 keer). Geeft altijd het laatste antwoord terug."""
    pogingen = 3 if method == "DELETE" else 6
    v = verbinding()
    for attempt in range(pogingen):
        r = v.s.request(method, v.base + path, params=params, json=body, timeout=60)
        if (r.status_code == 429 or r.status_code >= 500) and attempt < pogingen - 1:
            print(f"      {r.status_code}, opnieuw over {2 ** attempt}s")
            time.sleep(2 ** attempt)
            continue
        return r
    return r


def _subset(want, have):
    if isinstance(want, dict):
        return isinstance(have, dict) and all(k in have and _subset(v, have[k]) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(have, list) and all(any(_subset(w, h) for h in have) for w in want)
    return str(want).lower() == str(have).lower()


def verify(path, params, body):
    gp = dict(params or {})
    if gp.get("object-type") == "LOCAL":
        gp = {"view-type": "LOCAL", "scope-id": gp["scope-id"], "device-function": gp["device-function"]}
    r = api("GET", path, gp or None)
    if r.status_code >= 300:
        print(f"      verificatie: GET gaf {r.status_code}, controleer in de UI")
        return f"niet te lezen ({r.status_code})"
    try:
        have = r.json()
    except ValueError:
        return "niet te lezen (geen JSON)"
    if isinstance(have, dict) and len(have) == 1 and isinstance(next(iter(have.values())), list):
        lst = next(iter(have.values()))
        have = lst[0] if len(lst) == 1 else have
    body = dict(body or {})
    besch = body.pop("description", None)       # de beschrijving telt niet mee: een afwijking is geen fout
    if besch is not None and not (isinstance(have, dict) and have.get("description") == besch):
        print(f"      let op: beschrijving '{besch}' staat niet op het object in Central")
    if _subset(body, have):
        return "identiek"
    diff = [k for k in body if not (isinstance(have, dict) and k in have and _subset(body[k], have[k]))]
    print(f"      VERSCHILT van het plan in: {', '.join(diff) or 'structuur'}")
    return f"VERSCHILT: {', '.join(diff) or 'structuur'}"


def call(apply, method, path, params=None, body=None, what=""):
    entry = {"tijd": datetime.datetime.now().isoformat(timespec="seconds"), "wat": what, "methode": method,
             "pad": path, "params": params, "body": body, "apply": apply}
    print(f"{'APPLY' if apply else 'DRY  '} {method} {path}" + (f" {params}" if params else "") + (f"   # {what}" if what else ""))
    if not apply:
        entry["resultaat"] = "dry-run"
        LOG.append(entry)
        return True
    r = api(method, path, params, body)
    entry["status"] = r.status_code
    verifiable = method in ("POST", "PATCH") and "config-assignments" not in path
    if r.status_code < 300:
        entry["resultaat"] = "ok"
        print(f"      ok ({r.status_code})")
        if verifiable:
            entry["verificatie"] = verify(path, params, body)
    elif method == "DELETE" and r.status_code == 400 and "unexpected req_xpath" in r.text:
        entry["resultaat"] = "bestaat niet"
        print("      bestaat niet (meer) op deze scope, niets te doen")
    elif method == "DELETE" and ("referenced by" in r.text or "referred by" in r.text):
        entry["resultaat"] = "in gebruik"
        print(f"      in gebruik, niet verwijderd: {r.json().get('message', r.text[:200])}")
    elif r.status_code in (400, 409) and "exist" in r.text.lower():
        entry["resultaat"] = "bestaat al"
        entry["verificatie"] = verify(path, params, body) if verifiable else None
        print("      bestaat al, niet overschreven")
    else:
        entry["resultaat"] = f"fout: {r.text[:500]}"
        print(f"      FOUT {r.status_code}: {r.text[:500]}")
        if r.headers.get("x-request-id") or r.headers.get("debugId"):
            print(f"      request-id: {r.headers.get('x-request-id') or r.headers.get('debugId')}")
    LOG.append(entry)
    if str(entry.get("verificatie") or "").startswith("VERSCHILT"):
        return False
    return entry["resultaat"] in ("ok", "bestaat al", "bestaat niet")


def switches():
    out, nxt = {}, None
    while True:
        p = {"limit": 1000, "filter": "deviceType eq 'SWITCH'"}
        if nxt:
            p["next"] = nxt
        j = api("GET", "/network-monitoring/v1/device-inventory", p).json()
        for d in j.get("items", []):
            out[d["serialNumber"]] = d
        nxt = j.get("next")
        if not nxt:
            return out


def func_of(dev):
    return FUNC.get((dev.get("deviceFunction") or "").upper().replace("_", " ")) or ((dev.get("deviceFunction") or "").upper() if (dev.get("deviceFunction") or "").upper() in FUNC.values() else None)


def write_log(naast):
    if not LOG:
        return
    basis = os.path.join(os.path.dirname(os.path.abspath(naast)), f"alias-api-log-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    p, i = basis + ".json", 1
    while os.path.exists(p):              # nooit een bestaand logboek overschrijven
        i += 1
        p = f"{basis}-{i}.json"
    from . import __version__
    for e in LOG:
        e.setdefault("versie", __version__)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(LOG, f, indent=2)
    print(f"\nLogboek: {p}")


cp = sys.modules[__name__]

# ---------------------------------------------------------------- aliassen

PAD = PREFIX + "/aliases"
BESCHRIJVING = "Alias aangemaakt via CNX API Tool"     # description van elke alias die de tool aanmaakt
WEG = {"id", "etag", "created-at", "updated-at", "createdAt", "updatedAt", "last-modified", "lastModified"}


def lees_alias(naam, params=None):
    r = cp.api("GET", f"{PAD}/{quote(naam, safe='')}", params)
    try:
        data = r.json()
    except ValueError:
        data = r.text
    return r.status_code, data


STRUCTUUR = {
    # alias-type -> functie die default-value bouwt uit de waarde (vastgesteld via lees)
    "ALIAS_VLAN_DESCRIPTION": lambda w: {"vlan-description-value": {"description": w}},
}


def global_params():
    gid = os.environ.get("CNX_GLOBAL_SCOPE_ID") or global_scope_id()
    if not gid:
        sys.exit("Scope-ID van Global niet gevonden. Zet het met $env:CNX_GLOBAL_SCOPE_ID (zie 'lees --global').")
    return {"scope-id": gid, "device-function": "ACCESS_SWITCH"}


def lokaal(serial):
    d = cp.switches().get(serial)
    if not d or not d.get("scopeId"):
        sys.exit(f"{serial} staat niet in new Central.")
    fn = cp.func_of(d)
    if not fn:
        sys.exit(f"{serial} heeft geen device function.")
    return {"scope-id": str(d["scopeId"]), "device-function": fn}, d


def cmd_lees(a):
    varianten = [("library", {"view-type": "LIBRARY"}), ("zonder parameters", None)]
    if a.global_:
        r = api("GET", "/network-config/v1/global")
        print(f"== GET /network-config/v1/global -> {r.status_code}")
        print(r.text[:1500])
        gp = global_params()
        print(f"Scope-ID van Global: {gp['scope-id']}")
        varianten.insert(0, ("lokaal op Global", {"view-type": "LOCAL", **gp}))
    if a.serial:
        p, d = lokaal(a.serial)
        varianten.insert(0, (f"lokaal op {d.get('deviceName')} ({a.serial})", {"view-type": "LOCAL", **p}))
    for label, params in varianten:
        status, data = lees_alias(a.naam, params)
        print(f"\n== GET {PAD}/{a.naam} [{label}] -> {status}")
        print(json.dumps(data, indent=2) if not isinstance(data, str) else data[:2000])
    print("\nStuur deze uitvoer door: daaruit volgt de juiste body voor aanmaken en opkuisen.")


def vervang(obj, oud, nieuw):
    if isinstance(obj, dict):
        return {k: vervang(v, oud, nieuw) for k, v in obj.items() if k not in WEG}
    if isinstance(obj, list):
        return [vervang(v, oud, nieuw) for v in obj]
    return nieuw if obj == oud else obj


def kern(data):
    """Haal het aliasobject uit een antwoord dat een lijst of een omhulsel kan zijn."""
    if isinstance(data, dict) and len(data) == 1 and isinstance(next(iter(data.values())), list):
        lst = next(iter(data.values()))
        return lst[0] if lst else {}
    if isinstance(data, list):
        return data[0] if data else {}
    return data


def lees_waarden(pad):
    """Rijen op Global uit 2-global-waarden.csv (bulkformaat): {alias: (type, [waarden...])}."""
    uit, kop = {}, None
    with open(pad, newline="", encoding="utf-8-sig") as f:
        for c in csv.reader(f):
            if not c or not any(c):
                kop = None
                continue
            if c[0].startswith("#"):
                continue
            if c[0] == "Alias Name":
                kop = c
                continue
            if kop and len(c) >= 10 and c[3] == "Global":
                uit.setdefault(c[0], (c[1], []))[1].append(c[9:len(kop)])
    return uit


def global_scope_id():
    r = cp.api("GET", "/network-config/v1/global")
    try:
        j = r.json()
    except ValueError:
        return None
    for k in ("scopeId", "scope-id", "id"):
        if isinstance(j, dict) and j.get(k):
            return str(j[k])
    items = j.get("items") if isinstance(j, dict) else None
    if items:
        return str(items[0].get("scopeId") or items[0].get("id"))
    return None


def cmd_aanmaken(a):
    gp = global_params()
    print(f"Global scope-ID {gp['scope-id']}, device function {gp['device-function']}")
    sjabloon, s_type = None, None
    if a.sjabloon:
        status, data = lees_alias(a.sjabloon, {"view-type": "LOCAL", **gp})
        sjabloon = kern(data) if status < 300 else None
        if not sjabloon or a.sjabloon_waarde not in json.dumps(sjabloon):
            sys.exit(f"Sjabloon {a.sjabloon} niet gevonden op Global, of '{a.sjabloon_waarde}' staat er niet in.")
        s_type = sjabloon.get("type")
        print(f"Sjabloon {a.sjabloon}, type {s_type}")

    waarden = lees_waarden(a.waarden)
    ok, overgeslagen, n = True, [], 0
    params = None if a.library else {"object-type": "LOCAL", **gp}
    bestaand = toewijzingen_global(gp) if a.library else set()
    for naam, (typ, rijen) in sorted(waarden.items()):
        if a.alleen and naam not in a.alleen:
            continue
        if len(rijen) != 1 or len([x for x in rijen[0] if x]) != 1:
            overgeslagen.append((naam, "meer dan een waarde per alias: niet ondersteund"))
            continue
        waarde = next(x for x in rijen[0] if x)
        if typ in STRUCTUUR:
            body = {"name": naam, "type": typ, "default-value": STRUCTUUR[typ](waarde)}
        elif sjabloon and typ == s_type:
            body = vervang(vervang(copy.deepcopy(sjabloon), a.sjabloon, naam), a.sjabloon_waarde, waarde)
            body["name"] = naam
        else:
            overgeslagen.append((naam, f"type {typ}: structuur onbekend, gebruik --sjabloon"))
            continue
        body["description"] = BESCHRIJVING
        if a.library:
            gemaakt = cp.call(a.apply, "POST", f"{PAD}/{quote(naam, safe='')}", body=body,
                              what=f"library: {naam} = {waarde}")
            ok &= gemaakt
            if gemaakt:
                ok &= toewijzen(a.apply, naam, gp, bestaand)
        else:
            ok &= cp.call(a.apply, "POST", f"{PAD}/{quote(naam, safe='')}", params=params, body=body,
                          what=f"{naam} = {waarde} lokaal op Global")
        n += 1
    if overgeslagen:
        print("\nOvergeslagen:")
        for nm, why in overgeslagen:
            print(f"  - {nm}: {why}")
    print(f"\n{n} aliassen." + ("" if a.apply else " Dry-run: voeg --apply toe."))
    cp.write_log(a.waarden)
    return 0 if ok else 1


def toewijzingen_global(gp):
    """Set van (profile-type, profile-instance, device-function) op Global."""
    r = api("GET", f"{PREFIX}/config-assignments", {"scope-id": gp["scope-id"]})
    try:
        lst = r.json().get("config-assignment") or []
    except (ValueError, AttributeError):
        lst = []
    return {(x.get("profile-type"), x.get("profile-instance"), x.get("device-function")) for x in lst}


def toewijzen(apply, naam, gp, bestaand):
    if ("aliases", naam, gp["device-function"]) in bestaand:
        print(f"  {naam}: al toegewezen aan Global ({gp['device-function']})")
        return True
    return call(apply, "POST", f"{PREFIX}/config-assignments", body={"config-assignment": [{
        "scope-id": gp["scope-id"], "device-function": gp["device-function"],
        "profile-type": "aliases", "profile-instance": naam}]},
        what=f"{naam} toewijzen aan Global ({gp['device-function']})")


def cmd_toewijzen(a):
    """Library-aliassen toewijzen aan Global, enkel waar de toewijzing ontbreekt."""
    gp = global_params()
    bestaand = toewijzingen_global(gp)
    ok, n = True, 0
    for naam in sorted(lees_waarden(a.waarden)):
        if a.alleen and naam not in a.alleen:
            continue
        s, d = lees_alias(naam, {"view-type": "LIBRARY"})
        if s >= 300 or not kern(d):
            print(f"  ! {naam}: niet in de library, eerst aanmaken --library")
            ok = False
            continue
        ok &= toewijzen(a.apply, naam, gp, bestaand)
        n += 1
    if a.apply:
        na = toewijzingen_global(gp)
        mist = [nm for nm in sorted(lees_waarden(a.waarden)) if (not a.alleen or nm in a.alleen)
                and ("aliases", nm, gp["device-function"]) not in na]
        print("\nControle: " + ("alles toegewezen." if not mist else "ontbreekt nog: " + ", ".join(mist)))
        ok &= not mist
    print(f"{n} aliassen." + ("" if a.apply else " Dry-run: voeg --apply toe."))
    write_log(a.waarden)
    return 0 if ok else 1


def alle_toewijzingen_global(gp):
    r = api("GET", f"{PREFIX}/config-assignments", {"scope-id": gp["scope-id"]})
    try:
        return r.json().get("config-assignment") or []
    except (ValueError, AttributeError):
        sys.exit(f"Toewijzingen op Global niet te lezen ({r.status_code}): {r.text[:300]}")


def vlan_id(instance):
    try:
        return int(str(instance))
    except ValueError:
        return None


def cmd_vlans_doorzetten(a):
    """Elke layer2-vlan die op Global aan ACCESS_SWITCH hangt, ook toewijzen aan de andere device functions."""
    gp = global_params()
    lst = alle_toewijzingen_global(gp)
    bestaand = {(x.get("profile-type"), str(x.get("profile-instance")), x.get("device-function")) for x in lst}
    vlans = sorted({str(x["profile-instance"]) for x in lst
                    if x.get("profile-type") == "layer2-vlan" and x.get("device-function") == a.van},
                   key=lambda v: (vlan_id(v) is None, vlan_id(v) or 0, v))
    if not vlans:
        sys.exit(f"Geen layer2-vlan op Global voor {a.van}.")
    todo = [("layer2-vlan", v) for v in vlans]
    if a.ook_beschrijvingen:
        for v in vlans:
            naam = f"sys_vlan_{v}_description"
            if ("aliases", naam, a.van) in bestaand:
                todo.append(("aliases", naam))

    devs = switches()
    per_functie = {}
    for d in devs.values():
        fn = func_of(d)
        if fn in a.naar:
            per_functie.setdefault(fn, []).append(d.get("deviceName") or d.get("serialNumber"))
    print(f"{len(vlans)} VLAN's op Global voor {a.van}: {', '.join(vlans)}")
    for fn in a.naar:
        namen = sorted(per_functie.get(fn, []))
        print(f"  {fn}: {len(namen)} switches in new Central krijgen deze VLAN's" + (f" ({', '.join(namen[:10])}"
              + (", ..." if len(namen) > 10 else "") + ")" if namen else ""))
    print("  Let op: een VLAN dat op een switch al lokaal bestaat (geimporteerd), blijft de lokale versie houden.\n")

    ok, nieuw = True, 0
    for fn in a.naar:
        for typ, inst in todo:
            if (typ, inst, fn) in bestaand:
                continue
            ok &= call(a.apply, "POST", f"{PREFIX}/config-assignments", body={"config-assignment": [{
                "scope-id": gp["scope-id"], "device-function": fn, "profile-type": typ, "profile-instance": inst}]},
                what=f"{typ} {inst} -> Global {fn}")
            nieuw += 1
    if a.apply:
        na = {(x.get("profile-type"), str(x.get("profile-instance")), x.get("device-function"))
              for x in alle_toewijzingen_global(gp)}
        mist = [f"{typ} {inst} ({fn})" for fn in a.naar for typ, inst in todo if (typ, inst, fn) not in na]
        print("\nControle: " + ("alles toegewezen." if not mist else f"{len(mist)} ontbreken nog: " + ", ".join(mist[:20])))
        ok &= not mist
    print(f"{nieuw} nieuwe toewijzingen." + ("" if a.apply else " Dry-run: voeg --apply toe."))
    write_log(os.path.join(getattr(a, "werkmap", None) or os.getcwd(), "x"))
    return 0 if ok else 1


def cmd_vlans_terugdraaien(a):
    """Toewijzingen uit een logboek van vlans-doorzetten weer verwijderen."""
    with open(a.log, encoding="utf-8") as f:
        log = json.load(f)
    items = [e["body"]["config-assignment"][0] for e in log
             if e.get("apply") and e.get("resultaat") == "ok" and "config-assignments" in e.get("pad", "")
             and e.get("methode") == "POST"]
    if not items:
        sys.exit("Geen geslaagde toewijzingen in dit logboek.")
    ok = True
    for it in items:
        ok &= call(a.apply, "DELETE", f"{PREFIX}/config-assignments", body={"config-assignment": [it]},
                   what=f"terug: {it['profile-type']} {it['profile-instance']} van Global {it['device-function']}")
    print(f"\n{len(items)} toewijzingen." + ("" if a.apply else " Dry-run: voeg --apply toe."))
    write_log(a.log)
    return 0 if ok else 1


def cmd_toewijzingen(a):
    """Alleen-lezen: toon bestaande toewijzingen op Global, om profile-type voor aliassen te kennen."""
    gp = global_params()
    varianten = [
        {"scope-id": gp["scope-id"]},
        {"scope-id": gp["scope-id"], "device-function": gp["device-function"]},
        None,
    ]
    for params in varianten:
        r = api("GET", f"{PREFIX}/config-assignments", params)
        print(f"\n== GET {PREFIX}/config-assignments {params or ''} -> {r.status_code}")
        try:
            data = r.json()
        except ValueError:
            print(r.text[:1500])
            continue
        tekst = json.dumps(data, indent=2)
        types = sorted({x.get("profile-type") for x in (data.get("config-assignment") or data.get("items") or [])
                        if isinstance(x, dict)}) if isinstance(data, dict) else []
        if types:
            print("profile-types gevonden: " + ", ".join(str(x) for x in types))
        print(tekst[:4000] + ("\n... (ingekort)" if len(tekst) > 4000 else ""))
        if r.status_code < 300:
            break
    print("\nTip: wijs in de UI een alias uit de Library toe aan Global en draai dit opnieuw. Dan zie je het juiste profile-type.")


def cmd_global_lokaal_weg(a):
    """Verwijder de lokale kopie op Global, nadat de library-versie toegewezen is."""
    gp = global_params()
    params = {"object-type": "LOCAL", **gp}
    ok, n = True, 0
    for naam in sorted(lees_waarden(a.waarden)):
        if a.alleen and naam not in a.alleen:
            continue
        if not a.forceer:
            s, d = lees_alias(naam, {"view-type": "LIBRARY"})
            if s >= 300 or not kern(d):
                print(f"  ! {naam}: niet gevonden in de library, lokale versie op Global blijft staan (--forceer om toch)")
                ok = False
                continue
        ok &= cp.call(a.apply, "DELETE", f"{PAD}/{quote(naam, safe='')}", params=params,
                      what=f"lokale kopie van {naam} op Global verwijderen")
        n += 1
    print(f"\n{n} aliassen." + ("" if a.apply else " Dry-run: voeg --apply toe."))
    cp.write_log(a.waarden)
    return 0 if ok else 1


def cmd_naar_library(a):
    """Lokale kopie op Global vervangen door de library-alias, zonder dat een switch zonder waarde valt."""
    gp = global_params()
    devs = switches()
    doelen = []
    for s in a.serial:
        d = devs.get(s)
        if not d or not d.get("scopeId") or not func_of(d):
            sys.exit(f"{s}: niet in new Central of zonder device function.")
        doelen.append((s, d.get("deviceName"), {"object-type": "LOCAL", "scope-id": str(d["scopeId"]), "device-function": func_of(d)}))
    gparams = {"object-type": "LOCAL", **gp}
    ok, klaar, fout = True, 0, []
    for naam, (typ, rijen) in sorted(lees_waarden(a.waarden).items()):
        if a.alleen and naam not in a.alleen:
            continue
        if typ not in STRUCTUUR or len(rijen) != 1:
            continue
        s_lib, d_lib = lees_alias(naam, {"view-type": "LIBRARY"})
        lib = kern(d_lib) if s_lib < 300 else None
        if not lib:
            print(f"  ! {naam}: nog niet in de library. Eerst: aanmaken --library --alleen {naam}")
            fout.append(naam)
            continue
        s_glob, d_glob = lees_alias(naam, {"view-type": "LOCAL", **gp})
        if s_glob >= 300 or not kern(d_glob):
            print(f"  {naam}: geen lokale kopie op Global meer, enkel de toewijzing nakijken")
            ok &= toewijzen(a.apply, naam, gp, toewijzingen_global(gp))
            continue
        body = {"name": naam, "type": typ, "default-value": lib["default-value"], "description": lib.get("description") or BESCHRIJVING}
        print(f"\n{naam}")
        stap = True
        for serial, host, params in doelen:                     # 1. tijdelijk lokaal op de switch
            stap &= call(a.apply, "POST", f"{PAD}/{quote(naam, safe='')}", params=params, body=body,
                         what=f"1. tijdelijk lokaal op {host}")
        # (2b hieronder: toewijzing van de library-alias aan Global)
        if not stap:
            fout.append(naam)
            ok = False
            continue
        if not call(a.apply, "DELETE", f"{PAD}/{quote(naam, safe='')}", params=gparams,
                    what="2. lokale kopie op Global verwijderen"):
            print("      stap 2 mislukt: de tijdelijke waarde op de switch blijft staan (zelfde waarde, geen impact)")
            fout.append(naam)
            ok = False
            continue
        if a.apply:
            s_chk, d_chk = lees_alias(naam, {"view-type": "LOCAL", **gp})
            if s_chk < 300 and kern(d_chk):
                print("      stap 2 gaf ok, maar de kopie op Global bestaat nog. Gestopt voor deze alias.")
                fout.append(naam)
                ok = False
                continue
        # 2b. nu de lokale kopie weg is, telt enkel nog de toewijzing van de library-alias
        if not toewijzen(a.apply, naam, gp, toewijzingen_global(gp) if a.apply else set()):
            print("      toewijzen mislukt: de tijdelijke waarde op de switch blijft staan")
            fout.append(naam)
            ok = False
            continue
        if a.apply and ("aliases", naam, gp["device-function"]) not in toewijzingen_global(gp):
            print("      toewijzing niet terug te vinden: de tijdelijke waarde op de switch blijft staan")
            fout.append(naam)
            ok = False
            continue
        for serial, host, params in doelen:                     # 3. lokale waarde op de switch weer weg
            ok &= call(a.apply, "DELETE", f"{PAD}/{quote(naam, safe='')}", params=params,
                       what=f"3. lokale waarde op {host} weer weg: erft de library-alias")
        print("      klaar: library-alias, toegewezen aan Global")
        klaar += 1
    print(f"\n{klaar} aliassen omgezet naar de library." + (f" Niet gelukt: {', '.join(fout)}" if fout else "")
          + ("" if a.apply else " Dry-run: voeg --apply toe."))
    write_log(a.waarden)
    return 0 if ok else 1


def cmd_opkuisen(a):
    with open(a.lijst, newline="", encoding="utf-8-sig") as f:
        rijen = list(csv.DictReader(f))
    if a.serial:
        rijen = [r for r in rijen if r["serial"] in a.serial]
    if a.alleen:
        rijen = [r for r in rijen if r["alias"] in a.alleen]
    if not rijen:
        sys.exit("Niets te doen voor deze selectie.")
    devs = cp.switches()
    gp = global_params()
    toegewezen = toewijzingen_global(gp)
    zonder = sorted({r["alias"] for r in rijen if ("aliases", r["alias"], gp["device-function"]) not in toegewezen})
    if zonder and not a.forceer:
        print("Niet toegewezen aan Global, de switch zou zonder waarde vallen. Overgeslagen: " + ", ".join(zonder))
        print("Eerst: toewijzen. Of --forceer als de waarde op een andere hogere scope staat.")
        rijen = [r for r in rijen if r["alias"] not in zonder]
    ok, per = True, {}
    if not a.ook_in_gebruik:
        rijen = [r for r in rijen if r.get("type") != "ALIAS_DNS_RESOLVER"]
    for r in rijen:
        d = devs.get(r["serial"])
        if not d or not d.get("scopeId") or not cp.func_of(d):
            print(f"  ! {r['serial']}: niet in new Central of zonder device function, overgeslagen")
            ok = False
            continue
        params = {"object-type": "LOCAL", "scope-id": str(d["scopeId"]), "device-function": cp.func_of(d)}
        res = cp.call(a.apply, "DELETE", f"{PAD}/{quote(r['alias'], safe='')}", params=params,
                      what=f"{d.get('deviceName')}: lokale waarde van {r['alias']} verwijderen")
        ok &= res
        per[r["serial"]] = per.get(r["serial"], 0) + 1
    print(f"\n{sum(per.values())} aliassen op {len(per)} switches." + ("" if a.apply else " Dry-run: voeg --apply toe."))
    print("Controle: haal daarna een bulk-download op. De alias mag op de switch niet meer voorkomen, of enkel de waarde van Global tonen.")
    cp.write_log(a.lijst)
    return 0 if ok else 1


def bouw_parser():
    p = argparse.ArgumentParser(prog="cnx api", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("lees", help="alleen-lezen: toon hoe een alias er in de API uitziet")
    l.add_argument("--naam", required=True)
    l.add_argument("--serial", help="ook de lokale waarde op deze switch lezen")
    l.add_argument("--global", dest="global_", action="store_true", help="ook de waarde op Global lezen")
    m = sub.add_parser("aanmaken", help="aliassen aanmaken op Global")
    m.add_argument("--waarden", required=True, help="2-global-waarden.csv van cnx alias globaliseer")
    m.add_argument("--sjabloon", help="enkel voor onbekende types: een alias van dat type die al op Global staat")
    m.add_argument("--sjabloon-waarde", help="de waarde in dat sjabloon")
    m.add_argument("--alleen", action="append", help="enkel deze alias (herhaalbaar)")
    m.add_argument("--library", action="store_true", help="gedeeld in de library aanmaken en toewijzen aan Global")
    m.add_argument("--apply", action="store_true")
    tw = sub.add_parser("toewijzingen", help="alleen-lezen: toewijzingen op Global tonen")
    vd = sub.add_parser("vlans-doorzetten", help="VLAN's op Global ook voor aggregation en core")
    vd.add_argument("--van", default="ACCESS_SWITCH")
    vd.add_argument("--naar", action="append", help="device function (herhaalbaar), standaard AGG_SWITCH en CORE_SWITCH")
    vd.add_argument("--ook-beschrijvingen", action="store_true", help="ook de aliassen sys_vlan_<id>_description")
    vd.add_argument("--apply", action="store_true")
    vt = sub.add_parser("vlans-terugdraaien", help="toewijzingen uit een logboek van vlans-doorzetten verwijderen")
    vt.add_argument("--log", required=True)
    vt.add_argument("--apply", action="store_true")
    tz = sub.add_parser("toewijzen", help="library-aliassen toewijzen aan Global waar dat ontbreekt")
    tz.add_argument("--waarden", required=True)
    tz.add_argument("--alleen", action="append")
    tz.add_argument("--apply", action="store_true")
    nl = sub.add_parser("naar-library", help="lokale kopie op Global vervangen door de library-alias")
    nl.add_argument("--waarden", required=True)
    nl.add_argument("--serial", action="append", required=True, help="switch die de kopie op Global gebruikt (herhaalbaar)")
    nl.add_argument("--alleen", action="append")
    nl.add_argument("--apply", action="store_true")
    gw = sub.add_parser("global-lokaal-weg", help="lokale kopie op Global verwijderen (na --library)")
    gw.add_argument("--waarden", required=True)
    gw.add_argument("--alleen", action="append")
    gw.add_argument("--forceer", action="store_true", help="ook als de library-versie niet gevonden wordt")
    gw.add_argument("--apply", action="store_true")
    o = sub.add_parser("opkuisen", help="lokale waarden op switches verwijderen")
    o.add_argument("--lijst", required=True, help="3-opkuis-per-switch.csv van cnx alias globaliseer")
    o.add_argument("--serial", action="append", help="enkel deze switch (herhaalbaar)")
    o.add_argument("--alleen", action="append", help="enkel deze alias (herhaalbaar)")
    o.add_argument("--forceer", action="store_true", help="ook aliassen die niet aan Global toegewezen zijn")
    o.add_argument("--ook-in-gebruik", action="store_true",
                   help="ook ALIAS_DNS_RESOLVER proberen (Central weigert zolang het DNS-profiel op de switch ernaar verwijst)")
    o.add_argument("--apply", action="store_true")
    return p


COMMANDOS = {"lees": cmd_lees, "aanmaken": cmd_aanmaken, "opkuisen": cmd_opkuisen, "toewijzingen": cmd_toewijzingen,
             "global-lokaal-weg": cmd_global_lokaal_weg, "naar-library": cmd_naar_library,
             "toewijzen": cmd_toewijzen, "vlans-doorzetten": cmd_vlans_doorzetten,
             "vlans-terugdraaien": cmd_vlans_terugdraaien}


def parse(argv=None):
    a = bouw_parser().parse_args(argv)
    if a.cmd == "vlans-doorzetten" and not a.naar:
        a.naar = ["AGG_SWITCH", "CORE_SWITCH"]
    return a


def main():
    a = parse()
    cp.login()
    return COMMANDOS[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

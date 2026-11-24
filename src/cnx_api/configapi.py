"""De configuratie van new Central lezen, en lokale overrides wissen:

  - toestellen_uit_groep   de switches van een device group, met IP, VLAN en profiel, voor Switches onboarden
  - afwijkingen(_scan)     wat lokaal op een switch staat tegenover wat hij erft (Overrides controleren)
  - wis_plan/wis_uitvoeren overrides wissen: eerst een plan, dan uitvoeren

Paden volgens developer.arubanetworks.com/new-central-config/reference (november 2026).
"""
import datetime, re
from urllib.parse import quote

from . import alias_api as cx
from . import monitor
from .aliassen import FUNCTIE_LABELS
from .monitor import ApiFout, Invoer, haal

CFG = "/network-config/v1alpha1"
SCOPE = "/network-config/v1"
MON = "/network-monitoring/v1"
FUNCTIES = ["ACCESS_SWITCH", "AGG_SWITCH", "CORE_SWITCH", "CAMPUS_AP", "MOBILITY_GW", "BRANCH_GW", "ALL"]


def _haal_of_leeg(pad, params=None):
    """404 betekent bij de configuratie-API meestal: niets ingesteld op deze scope."""
    try:
        return haal(pad, params)
    except ApiFout as e:
        if e.status == 404:
            return None
        raise


def _offset_lijst(pad, params=None, limit=100):
    items, off = [], 0
    for _ in range(500):
        j = haal(pad, dict(params or {}, limit=limit, offset=off)) or {}
        nieuw = (j.get("items") or j.get("devices") or []) if isinstance(j, dict) else []
        items += nieuw
        total = j.get("total") if isinstance(j, dict) else None
        if not nieuw or len(nieuw) < limit or (total is not None and len(items) >= int(total)):
            break
        off += len(nieuw)
    return items


def _sid(x):
    return str(x.get("scopeId") or x.get("id") or "")


def scopes(met_switches=False):
    """Alle scopes: Global, site collections, sites, device groups en optioneel elke switch (een keer per stack)."""
    g = haal(SCOPE + "/global") or {}
    uit = [{"id": _sid(g), "naam": "Global", "type": "Global"}]
    uit += [{"id": _sid(x), "naam": x.get("scopeName") or _sid(x), "type": "Site collection"} for x in _offset_lijst(SCOPE + "/site-collections")]
    uit += [{"id": _sid(x), "naam": x.get("scopeName") or _sid(x), "type": "Site", "collectie": x.get("collectionName") or ""}
            for x in _offset_lijst(SCOPE + "/sites")]
    uit += [{"id": _sid(x), "naam": x.get("scopeName") or _sid(x), "type": "Device group"} for x in _offset_lijst(SCOPE + "/device-groups")]
    if met_switches:
        gezien = set()
        for d in monitor.alles_next(MON + "/device-inventory", {"limit": 1000, "filter": "deviceType eq 'SWITCH'"})["items"]:
            sid = str(d.get("scopeId") or "")
            if sid and sid not in gezien:
                gezien.add(sid)
                uit.append({"id": sid, "naam": d.get("deviceName") or d.get("serialNumber"), "type": "Switch",
                            "serial": d.get("serialNumber"), "site": d.get("siteName") or "", "functie": d.get("deviceFunction") or ""})
    return [s for s in uit if s["id"]]


# ---------------------------------------------------------------- keuzes voor de assistent

MGMT_NAAM = re.compile(r"mgmt|manage|beheer|oob", re.I)


def _namen(pad, lijst, sleutel, gid):
    """Objecten van een profieltype uit de library en (effectief) op Global, op naam."""
    uit = {}
    for params in ({"view-type": "LIBRARY"},
                   {"view-type": "LOCAL", "scope-id": gid, "device-function": "ACCESS_SWITCH", "effective": "true"}):
        try:
            items = _lijst_uit(_haal_of_leeg(f"{CFG}/{pad}", params), lijst)
        except ApiFout:
            continue
        for x in items:
            if isinstance(x, dict) and x.get(sleutel) not in (None, ""):
                uit.setdefault(str(x[sleutel]), x)
    return uit


def keuzes():
    """Alles wat de assistent als keuzelijst toont: scopes, System-info-profielen, beheerinterfaces en VLAN's,
    met een aanbeveling (wat aan Global hangt voor ACCESS_SWITCH, of wat naar beheer klinkt)."""
    alle = scopes()
    gid = next((s["id"] for s in alle if s["type"] == "Global"), "")
    toegewezen = set()
    try:
        for x in (_haal_of_leeg(f"{CFG}/config-assignments", {"scope-id": gid}) or {}).get("config-assignment") or []:
            if x.get("device-function") in ("ACCESS_SWITCH", "ALL", None):
                toegewezen.add((str(x.get("profile-type") or ""), str(x.get("profile-instance") or "")))
    except ApiFout:
        pass

    def aan_global(soort, naam):
        return any(naam == inst and soort in typ for typ, inst in toegewezen)

    sysinfo = [{"naam": n, "hostname": x.get("hostname") or "", "toegewezen": aan_global("system", n)}
               for n, x in sorted(_namen("system-info", "profile", "name", gid).items())]
    mgmt = [{"naam": n, "toegewezen": aan_global("mgmt", n)} for n, x in sorted(_namen("mgmt-interfaces", "profile", "name", gid).items())]
    vlans = []
    for n, x in _namen("layer2-vlan", "l2-vlan", "vlan", gid).items():
        try:
            vid = int(n)
        except ValueError:
            continue
        vlans.append({"id": vid, "naam": x.get("name") or "", "omschrijving": x.get("description") or "",
                      "beheer": bool(MGMT_NAAM.search(f"{x.get('name') or ''} {x.get('description') or ''}"))})
    vlans.sort(key=lambda v: v["id"])

    def aanbevolen(lijst, sleutel="naam"):
        kies = [x for x in lijst if x.get("toegewezen")] or (lijst if len(lijst) == 1 else [])
        return kies[0][sleutel] if kies else ""

    beheer_vlans = [v for v in vlans if v["beheer"]]
    return {"sites": [{"naam": s["naam"], "collectie": s.get("collectie") or ""} for s in alle if s["type"] == "Site"],
            "collecties": [s["naam"] for s in alle if s["type"] == "Site collection"],
            "groepen": [s["naam"] for s in alle if s["type"] == "Device group"],
            "systeeminfo": sysinfo, "mgmt": mgmt, "vlans": vlans,
            "aanbevolen": {"systeeminfo": aanbevolen(sysinfo),
                           "mgmt": aanbevolen(mgmt) or next((m["naam"] for m in mgmt if m["naam"].lower() == "mgmt"), ""),
                           "vlan": beheer_vlans[0]["id"] if len(beheer_vlans) == 1 else ""}}


# ---------------------------------------------------------------- aliassen

def _tekst(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ", ".join(_tekst(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}={_tekst(x)}" for k, x in v.items())
    return str(v)


def waarde_tekst(dv):
    """default-value is een object met een deelobject per aliastype; toon enkel de waarde als dat kan."""
    if not isinstance(dv, dict):
        return _tekst(dv)
    blad = plat(dv)
    if len(blad) == 1:
        return _tekst(next(iter(blad.values())))
    return "; ".join(f"{k.split('.')[-1]}={_tekst(v)}" for k, v in blad.items())


# ---------------------------------------------------------------- gereedheid voor migratie


# ---------------------------------------------------------------- oplossen: site, device function, device group


# ---------------------------------------------------------------- snapshots

# (naam, pad, lijstsleutel, itemsleutel, enkel per toestel)
PROFIELEN = [
    ("VLAN's", "layer2-vlan", "l2-vlan", "vlan", False),
    ("VLAN-interfaces (SVI)", "vlan-interfaces", "interface", "id", False),
    ("Systeeminfo (hostname)", "system-info", "profile", "name", False),
    ("Switch-systeem", "switch-system", "profile", "name", False),
    ("DNS", "dns", "profile", "name", False),
    ("NTP", "ntp", "profile", "name", False),
    ("Logging", "logging", "profile", "name", False),
    ("SNMP", "snmp", "profile", "name", False),
    ("Poortprofielen", "sw-port-profiles", "profile", "profileName", False),
    ("Interfaceprofielen", "interface-profiles", "interface-profile", "name", False),
    ("Beheerinterface", "mgmt-interfaces", "profile", "name", False),
    ("Lokaal beheer", "local-management", "profile", "name", False),
    ("AAA-servers", "auth-servers", "auth-server", "name", False),
    ("Servergroepen", "server-groups", "server-group", "name", False),
    ("STP", "stp", "profile", "name", False),
    ("LLDP", "lldp", "profile", "name", False),
    ("Aliassen", "aliases", "alias", "name", False),
    ("VSF-templates", "vsf-templates", "template", "name", False),
    ("Firmwarebeleid", "firmware-compliance", None, None, False),
    ("Ethernet-interfaces", "ethernet-interfaces", None, None, True),
]
SLEUTELS = ("name", "profileName", "profile-name", "vlan", "id", "interface-name")


def _lijst_uit(j, sleutel):
    if isinstance(j, list):
        return j
    if not isinstance(j, dict) or not j:
        return []
    if sleutel and isinstance(j.get(sleutel), list):
        return j[sleutel]
    lijsten = [v for v in j.values() if isinstance(v, list)]
    if len(lijsten) == 1:
        return lijsten[0]
    return [j]  # een enkel object, zoals het firmwarebeleid


def _id(item, sleutel, i):
    if isinstance(item, dict):
        for k in ([sleutel] if sleutel else []) + list(SLEUTELS):
            if k and item.get(k) not in (None, ""):
                return str(item[k])
    return f"#{i + 1}"


# ---------------------------------------------------------------- afwijkingen: lokaal op de switch tegenover geerfd

# Profielen waar een lokale waarde per switch normaal is.
PER_SWITCH = {"Systeeminfo (hostname)", "Beheerinterface", "Lokaal beheer"}
PER_SWITCH_ALIAS = re.compile(r"^sys_vlan_ipv4_\d+$")
OUDERS = ["Device group", "Site", "Site collection", "Global"]      # van dichtstbij naar verst


def _objecten(pad, lijst, sleutel, scope_id, df, cache, profiel=""):
    """{sleutel: object} van een profiel zoals het op die scope zelf is vastgelegd.
    Zelfde aanvraag als het oude overrides-scherm: view-type LOCAL, scope-id en de device function."""
    k = (pad, scope_id, df or "")
    if k not in cache:
        params = {"view-type": "LOCAL", "scope-id": scope_id}
        if df and df != "ALL":
            params["device-function"] = df
        diag = {"profiel": profiel, "pad": pad, "params": "&".join(f"{a}={b}" for a, b in params.items())}
        try:
            j = _haal_of_leeg(f"{CFG}/{pad}", params)
            items = _lijst_uit(j, lijst)
            cache[k] = {_id(x, sleutel, i): x for i, x in enumerate(items)}
            diag.update(antwoord="404 (niets ingesteld)" if j is None else "200", aantal=len(items))
            if j is not None and not items:
                diag["sleutels"] = ", ".join(list(j)[:12]) if isinstance(j, dict) else type(j).__name__
        except ApiFout as e:
            cache[k] = {"__fout__": f"{e.status} {e.melding}"}
            diag.update(antwoord=f"{e.status} {e.melding}"[:200], aantal=0)
        cache[("__diag__",) + k] = diag
    return cache[k]


def _switch_scopes(cache):
    """Inventaris van de switches en de scope-ID's van hun site, site collection en device group."""
    if "__scopes__" not in cache:
        alle = scopes()
        per_type = {}
        for s in alle:
            per_type.setdefault(s["type"], {})[s["naam"]] = s
        inv = monitor.alles_next(MON + "/device-inventory", {"limit": 1000, "filter": "deviceType eq 'SWITCH'"})["items"]
        cache["__scopes__"] = (per_type, {d.get("serialNumber"): d for d in inv})
    return cache["__scopes__"]


def afwijkingen(serial, device_function=None, cache=None):
    """Alles wat lokaal op een switch staat, per object vergeleken met wat de switch erft. Leest enkel."""
    cache = {} if cache is None else cache
    monitor.serial(serial)
    per_type, inv = _switch_scopes(cache)
    d = inv.get(serial)
    if not d or not d.get("scopeId"):
        raise Invoer(f"{serial} staat niet in de inventaris van Central")
    # De device function van de switch zelf, zoals het oude overrides-scherm. Enkel als die ontbreekt
    # de gevraagde (standaard ACCESS_SWITCH).
    eigen = cx.func_of(d)
    df = eigen or (device_function if device_function in FUNCTIES and device_function != "ALL" else "ACCESS_SWITCH")
    site = per_type.get("Site", {}).get(d.get("siteName") or "")
    ouders = {"Device group": per_type.get("Device group", {}).get(d.get("deviceGroupName") or ""), "Site": site,
              "Site collection": per_type.get("Site collection", {}).get((site or {}).get("collectie") or ""),
              "Global": next(iter(per_type.get("Global", {}).values()), None)}
    sw = {"serial": serial, "naam": d.get("deviceName") or serial, "site": d.get("siteName") or "", "groep": d.get("deviceGroupName") or "",
          "scope": str(d["scopeId"]), "functie": df, "functie_central": d.get("deviceFunction") or ""}
    rijen, fouten = [], []
    if not eigen:
        fouten.append(f"de switch heeft geen device function in Central ({d.get('deviceFunction') or '-'}); gelezen als {df}")
    for naam, pad, lijst, sleutel, enkel_toestel in PROFIELEN:
        if enkel_toestel:
            continue
        lokaal = _objecten(pad, lijst, sleutel, str(d["scopeId"]), df, cache, naam)
        if "__fout__" in lokaal:
            fouten.append(f"{naam}: {lokaal['__fout__']}")
            continue
        for obj, waarde in lokaal.items():
            basis = dict(sw, profiel=naam, object=obj)
            geerfd, van = None, ""
            for t in OUDERS:
                s = ouders.get(t)
                if not s:
                    continue
                o = _objecten(pad, lijst, sleutel, s["id"], df, cache, naam)
                if obj in o:
                    geerfd, van = o[obj], f"{t} {s['naam']}"
                    break
            normaal = naam in PER_SWITCH or (naam == "Aliassen" and PER_SWITCH_ALIAS.match(obj))
            if geerfd is None:
                rijen.append(dict(basis, status="per switch" if normaal else "enkel lokaal", van="", veld="",
                                  lokaal=waarde_samenvatting(waarde), geerfd=""))
                continue
            fl, fg = plat(waarde), plat(geerfd)
            verschil = [v for v in sorted(set(fl) | set(fg)) if _tekst(fl.get(v)) != _tekst(fg.get(v))]
            if not verschil:
                rijen.append(dict(basis, status="gelijk", van=van, veld="", lokaal=waarde_samenvatting(waarde), geerfd="(zelfde)"))
            for v in verschil:
                kort = v.split(".")[-1] if naam == "Aliassen" else v          # default-value.<type>.description -> description
                rijen.append(dict(basis, status="verschilt", van=van, veld=kort, lokaal=_tekst(fl.get(v)), geerfd=_tekst(fg.get(v))))
    diagnose = [cache[("__diag__", p[1], sw["scope"], df)] for p in PROFIELEN
                if not p[4] and ("__diag__", p[1], sw["scope"], df) in cache]
    return {"switch": sw, "rijen": rijen, "fouten": fouten, "device_function": df, "diagnose": diagnose}


def override_switches():
    """Switches voor het tabblad Overrides: een per scope (stackleden samen), met site, device group en status."""
    inv = monitor.alles_next(MON + "/device-inventory", {"limit": 1000, "filter": "deviceType eq 'SWITCH'"})["items"]
    try:
        mon = {s.get("serialNumber"): s for s in monitor.lijst("switches")["items"] if s.get("serialNumber")}
    except ApiFout:
        mon = {}
    per_scope = {}
    for d in sorted(inv, key=lambda d: d.get("serialNumber") not in mon):
        per_scope.setdefault(str(d.get("scopeId") or d.get("serialNumber")), d)
    uit = []
    for d in per_scope.values():
        m = mon.get(d.get("serialNumber"), {})
        uit.append({"serialNumber": d.get("serialNumber") or "", "deviceName": d.get("deviceName") or m.get("deviceName") or "",
                    "siteName": d.get("siteName") or m.get("siteName") or "", "deviceGroupName": d.get("deviceGroupName") or "",
                    "deviceFunction": d.get("deviceFunction") or "", "status": m.get("status") or d.get("status") or "",
                    "stack": (m.get("deployment") or "").lower() == "stack"})
    return {"items": sorted(uit, key=lambda x: (x["deviceName"] or x["serialNumber"]).lower())}


def afwijkingen_scan(serials=None, device_function=None, voortgang=lambda *a: None):
    """afwijkingen voor meerdere switches (of alle), met een gedeelde cache voor de hogere scopes."""
    cache = {}
    voortgang(0, 1, "switches en scopes lezen")
    _, inv = _switch_scopes(cache)
    lijst = [s for s in (serials or sorted(inv, key=lambda x: inv[x].get("deviceName") or x)) if s in inv]
    rijen, fouten, diagnose = [], [], []
    for i, s in enumerate(lijst, 1):
        voortgang(i - 1, len(lijst), inv[s].get("deviceName") or s)
        try:
            r = afwijkingen(s, device_function, cache)
            rijen += r["rijen"]
            fouten += [f"{r['switch']['naam']}: {f}" for f in r["fouten"]]
            diagnose += [dict(x, switch=r["switch"]["naam"]) for x in r["diagnose"]]
        except ApiFout as e:
            fouten.append(f"{s}: {e.melding}")
    voortgang(len(lijst), len(lijst), "klaar")
    return {"rijen": rijen, "fouten": fouten, "diagnose": diagnose, "switches": len(lijst),
            "tijd": datetime.datetime.now().isoformat(timespec="seconds")}


# ---------------------------------------------------------------- toestellen.csv uit een device group in new Central

IMPORT_PROFIEL = "sys-system-info-profile"      # System-info-profiel dat de import uit Classic per switch maakt


def _toegewezen_sysinfo(scope_id, functie, cache):
    """Naam van het System-info-profiel dat op precies deze scope toegewezen is (voor deze device function), of leeg."""
    if scope_id not in cache:
        try:
            lst = (_haal_of_leeg(f"{CFG}/config-assignments", {"scope-id": scope_id}) or {}).get("config-assignment") or []
        except ApiFout:
            lst = []
        cache[scope_id] = [x for x in lst if isinstance(x, dict)]
    namen = []
    for x in cache[scope_id]:
        if "system-info" not in str(x.get("profile-type") or "") or not x.get("profile-instance"):
            continue
        if x.get("scope-id") not in (None, "", scope_id):
            continue
        if x.get("device-function") not in (None, "", "ALL", functie):
            continue
        namen.append(str(x["profile-instance"]))
    return namen[0] if len(set(namen)) == 1 else ""


def systeemprofiel_van(d, keten=(), cache=None):
    """Het System-info-profiel waar de hostname van deze switch in moet: het profiel dat Central de switch echt
    geeft. Eerst de toewijzingen van onder naar boven (switch, device group, site, site collection, Global; `keten`
    zijn de scope-id's boven de switch), zoals Central's eigen bulk-download het toont. Pas als daar niets staat:
    wat lokaal op de switch staat (het profiel van de Classic-import, het enige, of dat met de hostname)."""
    if not d.get("scopeId"):
        return ""
    cache = {} if cache is None else cache
    functie = cx.func_of(d) or "ACCESS_SWITCH"
    for sid in (str(d["scopeId"]), *[k for k in keten if k]):
        naam = _toegewezen_sysinfo(sid, functie, cache)
        if naam:
            return naam
    params = {"view-type": "LOCAL", "scope-id": str(d["scopeId"])}
    if cx.func_of(d):
        params["device-function"] = cx.func_of(d)
    try:
        items = [x for x in _lijst_uit(_haal_of_leeg(f"{CFG}/system-info", params), "profile") if isinstance(x, dict) and x.get("name")]
    except ApiFout:
        return ""
    namen = [str(x["name"]) for x in items]
    if IMPORT_PROFIEL in namen:
        return IMPORT_PROFIEL
    if len(namen) == 1:
        return namen[0]
    zelfde = [str(x["name"]) for x in items if d.get("deviceName") and str(x.get("hostname") or "").lower() == str(d["deviceName"]).lower()]
    return zelfde[0] if len(zelfde) == 1 else ""


SYS_VLAN_ALIAS = re.compile(r"^sys_vlan_ipv4_(\d{1,4})$")


def sys_vlan_van(d):
    """(vlan, ip/prefix) uit de alias sys_vlan_ipv4_<vlan> die lokaal op de switch staat, of (None, None).
    Switches uit Classic hebben die alias na de import: daar staat het beheer-IP met de juiste prefix."""
    if not d.get("scopeId"):
        return None, None
    params = {"view-type": "LOCAL", "scope-id": str(d["scopeId"])}
    if cx.func_of(d):
        params["device-function"] = cx.func_of(d)
    try:
        items = _lijst_uit(_haal_of_leeg(f"{CFG}/aliases", params), "alias")
    except ApiFout:
        return None, None
    gevonden = []
    for a in items:
        m = SYS_VLAN_ALIAS.match(str(a.get("name") or "")) if isinstance(a, dict) else None
        if m:
            ip = waarde_tekst(a.get("default-value")).strip()
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?$", ip):
                gevonden.append((m.group(1), ip))
    return gevonden[0] if len(gevonden) == 1 else (None, None)


def toestellen_uit_groep(groep, prefix="24", beheer_vlan="", serials=None):
    """Alle switches van een device group in new Central als rijen voor toestellen.csv. Leest enkel.
    Hostname, site, site collection en device group komen uit Central; het IP uit de monitoring, met de prefix erbij."""
    groep = str(groep or "").strip()
    if not groep:
        raise Invoer("kies een device group")
    prefix = str(prefix or "").strip().lstrip("/") or "24"
    if not prefix.isdigit() or not 8 <= int(prefix) <= 32:
        raise Invoer("prefix moet tussen 8 en 32 liggen")
    beheer_vlan = str(beheer_vlan or "").strip()
    if beheer_vlan and not (beheer_vlan.isdigit() and 1 <= int(beheer_vlan) <= 4094):
        raise Invoer("beheer-VLAN moet tussen 1 en 4094 liggen")
    alle = scopes()
    collectie = {s["naam"]: s.get("collectie") or "" for s in alle if s["type"] == "Site"}
    scope_id = {(s["type"], s["naam"]): s["id"] for s in alle}
    global_id = next((s["id"] for s in alle if s["type"] == "Global"), "")
    toewijzing_cache = {}
    inv = monitor.alles_next(MON + "/device-inventory", {"limit": 1000, "filter": "deviceType eq 'SWITCH'"})["items"]
    try:          # gateways (Mobility Gateway) in dezelfde device group: zelfde aliassen (beheer-IP, hostname)
        inv += [dict(d, _gateway=True) for d in
                monitor.alles_next(MON + "/device-inventory", {"limit": 1000, "filter": "deviceType eq 'GATEWAY'"})["items"]]
    except ApiFout:
        pass
    try:
        mon = {s.get("serialNumber"): s for s in monitor.lijst("switches")["items"] if s.get("serialNumber")}
    except ApiFout:
        mon = {}
    if any(d.get("_gateway") for d in inv):
        try:
            for s in monitor.lijst("devices", "deviceType eq 'GATEWAY'")["items"]:
                if s.get("serialNumber"):
                    mon.setdefault(s["serialNumber"], s)
        except ApiFout:
            pass
    leden = [d for d in inv if str(d.get("deviceGroupName") or "").strip().lower() == groep.lower()]
    # Stackleden delen een scope: een rij per scope, bij voorkeur de conductor (die staat in de switchlijst).
    per_scope = {}
    for d in sorted(leden, key=lambda d: d.get("serialNumber") not in mon):
        per_scope.setdefault(str(d.get("scopeId") or d.get("serialNumber")), d)
    if serials is not None:
        gekozen = {str(x).strip().upper() for x in serials if isinstance(x, (str, int))} if isinstance(serials, list) else set()
        per_scope = {k: d for k, d in per_scope.items() if str(d.get("serialNumber") or "").upper() in gekozen}
        if not per_scope:
            raise Invoer("kies minstens een toestel")
    rijen, meldingen = [], []
    for d in sorted(per_scope.values(), key=lambda d: (d.get("siteName") or "", d.get("deviceName") or "")):
        m = mon.get(d.get("serialNumber"), {})
        ser = d.get("serialNumber") or ""
        gateway = bool(d.get("_gateway"))
        opm = ["uit new Central, device group " + (d.get("deviceGroupName") or groep)]
        if gateway and cx.func_of(d) != "MOBILITY_GW":
            opm.append(f"gateway met device function {d.get('deviceFunction') or '-'}: gaat als Mobility Gateway in het aliasbestand")
            d = dict(d, deviceFunction="MOBILITY_GW")
        alias_vlan, alias_ip = sys_vlan_van(d)
        # Bij een gateway is het IP in de monitoring meestal dat van de uplink (bv. DHCP op VLAN 4094), niet het beheer-IP.
        ip = "" if gateway else str(m.get("ipv4") or d.get("ipv4") or d.get("ipAddress") or "").strip()
        if ip in ("-", "None"):
            ip = ""
        if ip and "/" not in ip:
            ip = f"{ip}/{prefix}"
        bron_ip = "monitoring" if ip else ""
        if alias_ip:
            ip, bron_ip = (alias_ip if "/" in alias_ip else f"{alias_ip}/{prefix}"), "alias"
        stack = not gateway and ((m.get("deployment") or d.get("deployment") or "").lower() == "stack" or bool(m.get("stackId") or d.get("stackId")))
        if bron_ip == "alias":
            opm.append(f"IP uit de alias sys_vlan_ipv4_{alias_vlan} op de {'gateway' if gateway else 'switch'}")
        elif ip:
            opm.append("IP uit de monitoring van Central. Beheerd via OOBM? Verplaats het dan naar mgmt_ip")
        elif gateway:
            opm.append("gateway zonder beheer-IP in Central: vul sys_vlan_ip in (bv. het IP van de controller in AOS-8)")
        else:
            opm.append("geen IP in Central: vul sys_vlan_ip aan")
        if stack:
            opm.append("VSF-stack: gaat niet via de bulk-upload")
        fc = cx.func_of(d) or ""
        if not fc:
            opm.append(f"geen device function in Central ({d.get('deviceFunction') or '-'}): gaat als Access Switch in het aliasbestand")
        site = d.get("siteName") or ""
        keten = (scope_id.get(("Device group", d.get("deviceGroupName") or groep)), scope_id.get(("Site", site)),
                 scope_id.get(("Site collection", collectie.get(site, ""))), global_id)
        profiel = systeemprofiel_van(d, keten, toewijzing_cache)
        if not profiel:
            opm.append("geen System-info-profiel gevonden in Central: vul systeemprofiel aan, anders gaat enkel het IP mee")
        rijen.append({"serial": ser, "hostname": d.get("deviceName") or "", "stack": "ja" if stack else "",
                      "site_collection": collectie.get(site, ""), "site": site, "device_group": d.get("deviceGroupName") or groep,
                      "device_function": FUNCTIE_LABELS.get(fc, ""), "golf": site or groep, "sys_vlan_ip": ip, "beheer_vlan": beheer_vlan or alias_vlan or "",
                      "bron_ip": bron_ip, "mgmt_ip": "", "systeemprofiel": profiel,
                      "soort": "gateway" if gateway else "switch", "opmerking": ". ".join(opm)})
    if not rijen:
        raise Invoer(f"geen switches of gateways gevonden in device group {groep}")
    zonder_ip = sum(1 for r in rijen if not r["sys_vlan_ip"])
    if zonder_ip:
        meldingen.append(f"{zonder_ip} toestellen zonder beheer-IP in Central: vul sys_vlan_ip aan")
    if sum(1 for r in rijen if r["stack"]):
        meldingen.append(f"{sum(1 for r in rijen if r['stack'])} VSF-stacks: gemarkeerd, ze gaan niet via de bulk-upload")
    zonder_sc = sorted({r["site"] or "(geen site)" for r in rijen if not r["site_collection"]})
    if zonder_sc:
        meldingen.append("geen site collection voor " + ", ".join(zonder_sc[:10]))
    return {"rijen": rijen, "meldingen": meldingen, "groep": groep, "prefix": prefix}


# ---------------------------------------------------------------- overrides wissen

# Nooit gewist, ook niet als ze gelijk zijn: daar staan hostname, beheer-IP en het firmwarebeleid.
NIET_WISSEN = PER_SWITCH | {"Firmwarebeleid"}
WISBAAR = {naam: (pad, lijst, sleutel) for naam, pad, lijst, sleutel, enkel_toestel in PROFIELEN
           if not enkel_toestel and naam not in NIET_WISSEN}
# Wat er met de switch gebeurt na het wissen, per status van de override.
WIS_GEVOLG = {"gelijk": "erft dezelfde waarde van {van}: verandert niets",
              "verschilt": "neemt de waarde van {van} over: de switch verandert",
              "enkel lokaal": "verdwijnt van de switch: staat nergens hoger"}


def wis_plan(items, device_function=None, voortgang=lambda *a: None):
    """Kijkt in Central opnieuw na of elk gekozen object nog altijd de status heeft die je zag (standaard: gelijk).
    Enkel die komen in het plan. Leest enkel."""
    df = device_function if device_function in FUNCTIES and device_function != "ALL" else None
    gekozen, verwacht = {}, {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and it.get("serial") and it.get("profiel") and it.get("object") is not None:
            k = (str(it["profiel"]), str(it["object"]))
            gekozen.setdefault(str(it["serial"]), set()).add(k)
            verwacht[(str(it["serial"]),) + k] = str(it.get("status") or "gelijk")
    cache, acties, geweigerd = {}, [], []
    for i, (serial, objecten) in enumerate(sorted(gekozen.items()), 1):
        voortgang(i - 1, len(gekozen), serial)
        try:
            r = afwijkingen(serial, df, cache)
        except ApiFout as e:
            geweigerd += [f"{serial} {p} {o}: {e.melding}" for p, o in sorted(objecten)]
            continue
        status = {}
        for x in r["rijen"]:
            k = (x["profiel"], x["object"])
            status[k] = "verschilt" if x["status"] == "verschilt" or status.get(k) == "verschilt" else x["status"]
        van = {(x["profiel"], x["object"]): x["van"] for x in r["rijen"]}
        velden = {}
        for x in r["rijen"]:
            if x["status"] == "verschilt":
                velden.setdefault((x["profiel"], x["object"]), []).append(f"{x['veld']}: {x['lokaal']} -> {x['geerfd']}")
        for p, o in sorted(objecten):
            naam, wil, nu = r["switch"]["naam"], verwacht[(serial, p, o)], status.get((p, o))
            if p not in WISBAAR:
                geweigerd.append(f"{naam} {p} {o}: dit profiel wist de toolkit niet")
            elif wil not in WIS_GEVOLG:
                geweigerd.append(f"{naam} {p} {o}: status '{wil}' wist de toolkit niet")
            elif nu != wil:
                geweigerd.append(f"{naam} {p} {o}: is niet (meer) {wil} ({nu or 'niet gevonden'})")
            else:
                acties.append({"serial": serial, "naam": naam, "scope": r["switch"]["scope"], "functie": r["switch"]["functie"],
                               "profiel": p, "object": o, "status": nu, "van": van.get((p, o), ""),
                               "gevolg": WIS_GEVOLG[nu].format(van=van.get((p, o)) or "hoger"),
                               "velden": velden.get((p, o), [])[:20]})
    voortgang(len(gekozen), len(gekozen), "klaar")
    return {"acties": acties, "geweigerd": geweigerd, "device_function": df or "ACCESS_SWITCH"}


def wis_uitvoeren(acties, device_function="ACCESS_SWITCH", voortgang=lambda *a: None):
    """Wist de lokale objecten uit een plan en kijkt daarna na dat ze weg zijn. De switch erft dan de waarde van hoger."""
    df = device_function if device_function in FUNCTIES and device_function != "ALL" else "ACCESS_SWITCH"
    uit = []
    for i, a in enumerate(acties, 1):
        voortgang(i - 1, len(acties), f"{a['naam']}: {a['profiel']} {a['object']}")
        if a.get("profiel") not in WISBAAR or not str(a.get("scope", "")).strip():
            uit.append(dict(a, resultaat="fout: niet toegelaten"))
            continue
        monitor.serial(a["scope"])
        pad, lijst, sleutel = WISBAAR[a["profiel"]]
        f = a.get("functie") if a.get("functie") in FUNCTIES and a.get("functie") != "ALL" else df
        params = {"object-type": "LOCAL", "scope-id": a["scope"], "device-function": f}
        r = cx.api("DELETE", f"{CFG}/{pad}/{quote(str(a['object']), safe='')}", params)
        if r.status_code < 300:
            resultaat = "gewist"
        elif "unexpected req_xpath" in r.text:
            resultaat = "bestond niet meer"
        elif "referenced by" in r.text or "referred by" in r.text:
            resultaat = "in gebruik, niet gewist"
        else:
            resultaat = f"fout {r.status_code}: {r.text[:200]}"
        if resultaat == "gewist":
            nog = _objecten(pad, lijst, sleutel, a["scope"], f, {})
            if str(a["object"]) in nog:
                resultaat = "Central meldde ok, maar het object staat er nog"
        uit.append(dict(a, resultaat=resultaat, code=r.status_code))
    voortgang(len(acties), len(acties), "klaar")
    return uit


def plat(o, pre=""):
    """Geneste configuratie naar {pad: waarde}, met lijsten van objecten op naam of id als dat kan."""
    uit = {}
    if isinstance(o, dict):
        for k, v in o.items():
            uit.update(plat(v, f"{pre}.{k}" if pre else str(k)))
    elif isinstance(o, list):
        if all(not isinstance(x, (dict, list)) for x in o):
            uit[pre] = ", ".join(sorted(_tekst(x) for x in o))
        else:
            for i, x in enumerate(o):
                uit.update(plat(x, f"{pre}[{_id(x, None, i)}]"))
    else:
        uit[pre] = o
    return uit


def waarde_samenvatting(item, maximum=300):
    t = "; ".join(f"{k}={_tekst(v)}" for k, v in plat(item).items())
    return t if len(t) <= maximum else t[:maximum] + " ..."

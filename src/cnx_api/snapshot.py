"""Voor/na-controle: de stand van een netwerk vastleggen (snapshot) en twee snapshots vergelijken.

Een snapshot leest enkel. Hij bevat per toestel de status en firmware, per switchpoort de status en de buur, en
het aantal clients per SSID en per toestel (tellingen, geen namen of MAC-adressen van clients). De server bewaart
hem niet: de browser krijgt hem terug en bewaart hem zelf.

Paden en velden volgens developer.arubanetworks.com/new-central/reference (november 2026):
  GET /network-monitoring/v1/devices                          toestellen (status, firmware, site)
  GET /network-monitoring/v1/switches/{serial}/interfaces     poorten (status, neighbour, neighbourPort)
  GET /network-monitoring/v1/clients                          verbonden clients (wlanName, connectedDeviceSerial)
"""
import datetime
import re
from collections import Counter
from urllib.parse import quote

from . import monitor
from .monitor import ApiFout, Invoer, haal
from .taal import _

MON = "/network-monitoring/v1"
SOORT = "cnx-snapshot"
MAX_SWITCHES = 300               # zoveel switches leest een snapshot hoogstens poort per poort
MAX_POORTEN = 1000               # per switch (een stack van tien switches met 52 poorten past)
SITE = re.compile(r"^[^'\"\\\n]{1,128}$")
DALING = 0.2                     # zoveel minder clients op een SSID is een waarschuwing
MIN_CLIENTS = 5                  # kleinere aantallen schommelen te veel om iets te betekenen


def _site_filter(site):
    site = str(site or "").strip()
    if site and not SITE.match(site):
        raise Invoer(_("ongeldige sitenaam"))
    return site


def _poorten(serial):
    uit, off = [], 0
    while len(uit) < MAX_POORTEN:
        j = haal(f"{MON}/switches/{quote(serial, safe='')}/interfaces", {"limit": 1000, "offset": off}) or {}
        nieuw = monitor._items(j)
        uit += nieuw
        total = j.get("total") if isinstance(j, dict) else None
        if not nieuw or total is None or len(uit) >= int(total):
            break
        off += len(nieuw)
    return [{"poort": str(p.get("name") or p.get("id") or ""), "status": str(p.get("operStatus") or p.get("status") or ""),
             "admin": str(p.get("adminStatus") or ""), "snelheid": p.get("speed"),
             "buur": str(p.get("neighbour") or ""), "buurpoort": str(p.get("neighbourPort") or "")}
            for p in uit[:MAX_POORTEN] if isinstance(p, dict) and (p.get("name") or p.get("id"))]


def maak(site="", tijd=None, voortgang=lambda *a: None):
    """Leest de stand van alle toestellen (of die van een site) uit Central."""
    site = _site_filter(site)
    filt = {"filter": f"siteName eq '{site}'"} if site else {}
    voortgang(0, 0, _("toestellen lezen"))
    devs = monitor.alles_next(MON + "/devices", dict({"limit": 1000}, **filt))
    toestellen = []
    for d in devs["items"]:
        if isinstance(d, dict) and d.get("serialNumber"):
            toestellen.append({"serial": str(d["serialNumber"]), "naam": str(d.get("deviceName") or ""), "type": str(d.get("deviceType") or ""),
                               "model": str(d.get("model") or ""), "status": str(d.get("status") or ""), "firmware": str(d.get("firmwareVersion") or ""),
                               "site": str(d.get("siteName") or ""), "ip": str(d.get("ipv4") or "")})
    switches = [d for d in toestellen if d["type"] == "SWITCH" and d["status"].upper() == "ONLINE"]
    fouten = []
    if len(switches) > MAX_SWITCHES:
        fouten.append(_("{n} switches online: de poorten van de eerste {max} zijn gelezen. Kies een site voor een volledige snapshot.",
                        n=len(switches), max=MAX_SWITCHES))
        switches = switches[:MAX_SWITCHES]
    poorten = {}
    for i, d in enumerate(switches, 1):
        voortgang(i - 1, len(switches), _("poorten van {naam}", naam=d["naam"] or d["serial"]))
        try:
            poorten[d["serial"]] = _poorten(d["serial"])
        except ApiFout as e:
            fouten.append(_("{naam}: poorten niet gelezen ({melding})", naam=d["naam"] or d["serial"], melding=e.melding))
    voortgang(len(switches), len(switches), _("clients tellen"))
    clients = {"totaal": 0, "bedraad": 0, "draadloos": 0, "per_ssid": {}, "per_toestel": {}}
    try:
        cl = monitor.alles_next(MON + "/clients", dict({"limit": 1000}, **({"site-name": site} if site else {})))["items"]
        ssid, toestel, soort = Counter(), Counter(), Counter()
        for c in cl:
            if not isinstance(c, dict):
                continue
            soort[str(c.get("clientConnectionType") or "").lower()] += 1
            if c.get("wlanName"):
                ssid[str(c["wlanName"])] += 1
            if c.get("connectedDeviceSerial"):
                toestel[str(c["connectedDeviceSerial"])] += 1
        clients = {"totaal": sum(soort.values()), "bedraad": soort["wired"], "draadloos": soort["wireless"],
                   "per_ssid": dict(ssid), "per_toestel": dict(toestel)}
    except ApiFout as e:
        fouten.append(_("clients niet gelezen ({melding})", melding=e.melding))
    voortgang(len(switches), len(switches), _("klaar"))
    return {"soort": SOORT, "versie": 1, "tijd": tijd or datetime.datetime.now().isoformat(timespec="seconds"), "site": site,
            "toestellen": toestellen, "poorten": poorten, "clients": clients, "fouten": fouten,
            "afgekapt": bool(devs.get("afgekapt"))}


# ---------------------------------------------------------------- vergelijken

def _controleer(s, wat):
    if not isinstance(s, dict) or s.get("soort") != SOORT or not isinstance(s.get("toestellen"), list):
        raise ValueError(_("{wat}: geen snapshot van de toolkit", wat=wat))
    if not isinstance(s.get("poorten") or {}, dict) or not isinstance(s.get("clients") or {}, dict):
        raise ValueError(_("{wat}: geen snapshot van de toolkit", wat=wat))
    return s


def _is_up(s):
    return str(s or "").lower() in ("up", "online")


def vergelijk(voor, na):
    """Wat er veranderd is tussen twee snapshots, als rijen met een ernst: bad (iets is weg of down), warn
    (nakijken), ok (hersteld) of info (gewijzigd, nieuw)."""
    voor, na = _controleer(voor, _("Voor")), _controleer(na, _("Na"))
    rijen = []

    def rij(ernst, soort, wat, detail):
        rijen.append({"ernst": ernst, "soort": soort, "wat": wat, "detail": detail})

    tv = {d["serial"]: d for d in voor["toestellen"] if isinstance(d, dict) and d.get("serial")}
    tn = {d["serial"]: d for d in na["toestellen"] if isinstance(d, dict) and d.get("serial")}
    naam = lambda s: (tn.get(s) or tv.get(s) or {}).get("naam") or s  # noqa: E731
    for s, d in tv.items():
        n = tn.get(s)
        if n is None:
            rij("bad", _("Toestel"), naam(s), _("niet meer in Central (was {status})", status=d.get("status") or "?"))
            continue
        if _is_up(d.get("status")) and not _is_up(n.get("status")):
            rij("bad", _("Toestel"), naam(s), _("{voor} naar {na}", voor=d.get("status"), na=n.get("status") or "?"))
        elif not _is_up(d.get("status")) and _is_up(n.get("status")):
            rij("ok", _("Toestel"), naam(s), _("{voor} naar {na}", voor=d.get("status") or "?", na=n.get("status")))
        if d.get("firmware") and n.get("firmware") and d["firmware"] != n["firmware"]:
            rij("info", _("Toestel"), naam(s), _("firmware {voor} naar {na}", voor=d["firmware"], na=n["firmware"]))
        if d.get("naam") and n.get("naam") and d["naam"] != n["naam"]:
            rij("info", _("Toestel"), n["naam"], _("hernoemd (was {naam})", naam=d["naam"]))
        if d.get("site") != n.get("site"):
            rij("info", _("Toestel"), naam(s), _("site {voor} naar {na}", voor=d.get("site") or "-", na=n.get("site") or "-"))
    for s, n in tn.items():
        if s not in tv:
            rij("info", _("Toestel"), naam(s), _("nieuw in Central ({status})", status=n.get("status") or "?"))

    pv, pn = voor.get("poorten") or {}, na.get("poorten") or {}
    for s, lijst in pv.items():
        if s not in pn:
            if s in tn and _is_up(tn[s].get("status")):
                rij("warn", _("Poort"), naam(s), _("poorten niet gelezen in de tweede snapshot"))
            continue
        nu = {p.get("poort"): p for p in pn[s] if isinstance(p, dict)}
        for p in lijst if isinstance(lijst, list) else []:
            if not isinstance(p, dict):
                continue
            wat, q = f"{naam(s)} {p.get('poort')}", nu.get(p.get("poort"))
            if q is None:
                if _is_up(p.get("status")):
                    rij("bad", _("Poort"), wat, _("poort niet meer gezien (was up)"))
                continue
            if _is_up(p.get("status")) and not _is_up(q.get("status")):
                rij("bad", _("Poort"), wat, _("up naar {na}", na=q.get("status") or "?") + (f" ({p['buur']})" if p.get("buur") else ""))
            elif not _is_up(p.get("status")) and _is_up(q.get("status")):
                rij("info", _("Poort"), wat, _("{voor} naar up", voor=p.get("status") or "?") + (f" ({q['buur']})" if q.get("buur") else ""))
            if p.get("buur") and _is_up(q.get("status")):
                if not q.get("buur"):
                    rij("warn", _("Poort"), wat, _("buur {buur} niet meer gezien", buur=p["buur"]))
                elif q["buur"] != p["buur"] or (p.get("buurpoort") and q.get("buurpoort") and q["buurpoort"] != p["buurpoort"]):
                    rij("warn", _("Poort"), wat, _("andere buur: {voor} naar {na}", voor=" ".join(x for x in (p["buur"], p.get("buurpoort")) if x),
                                                    na=" ".join(x for x in (q["buur"], q.get("buurpoort")) if x)))
            if _is_up(p.get("status")) and _is_up(q.get("status")) and p.get("snelheid") and q.get("snelheid") and q["snelheid"] < p["snelheid"]:
                rij("warn", _("Poort"), wat, _("snelheid {voor} naar {na} Mbps", voor=p["snelheid"], na=q["snelheid"]))

    cv, cn = voor.get("clients") or {}, na.get("clients") or {}
    sv, sn = cv.get("per_ssid") or {}, cn.get("per_ssid") or {}
    for ssid, a in sorted(sv.items()):
        b = int(sn.get(ssid) or 0)
        if a >= MIN_CLIENTS and b == 0:
            rij("bad", _("Clients"), ssid, _("{voor} naar 0 clients", voor=a))
        elif a >= MIN_CLIENTS and b < a * (1 - DALING):
            rij("warn", _("Clients"), ssid, _("{voor} naar {na} clients", voor=a, na=b))
    for ssid, b in sorted(sn.items()):
        if ssid not in sv:
            rij("info", _("Clients"), ssid, _("nieuwe SSID met {na} clients", na=b))
    av, an = cv.get("per_toestel") or {}, cn.get("per_toestel") or {}
    for s, a in sorted(av.items()):
        if a >= MIN_CLIENTS and not an.get(s) and s in tn and (tn[s].get("type") == "ACCESS_POINT"):
            rij("warn", _("Clients"), naam(s), _("{voor} naar 0 clients", voor=a))

    volgorde = {"bad": 0, "warn": 1, "ok": 2, "info": 3}
    rijen.sort(key=lambda r: (volgorde[r["ernst"]], r["soort"], r["wat"]))

    def tel(s):
        t = s["toestellen"]
        poorten = [p for lijst in (s.get("poorten") or {}).values() if isinstance(lijst, list) for p in lijst if isinstance(p, dict)]
        return {"toestellen": len(t), "online": sum(1 for d in t if isinstance(d, dict) and _is_up(d.get("status"))),
                "poorten_up": sum(1 for p in poorten if _is_up(p.get("status"))),
                "clients": int((s.get("clients") or {}).get("totaal") or 0)}

    let_op = []
    if voor.get("site") != na.get("site"):
        let_op.append(_("De snapshots gaan niet over dezelfde site ({voor} en {na}).", voor=voor.get("site") or _("alle"), na=na.get("site") or _("alle")))
    for s, wat in ((voor, _("Voor")), (na, _("Na"))):
        if s.get("fouten"):
            let_op.append(_("{wat}: niet alles gelezen ({n} meldingen).", wat=wat, n=len(s["fouten"])))
    return {"voor": {"tijd": voor.get("tijd"), "site": voor.get("site"), **tel(voor)},
            "na": {"tijd": na.get("tijd"), "site": na.get("site"), **tel(na)},
            "rijen": rijen, "ernst": dict(Counter(r["ernst"] for r in rijen)), "let_op": let_op}

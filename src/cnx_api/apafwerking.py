"""AP-migratie afwerken in new Central: de APs uit de AOS-8-inventaris terugvinden, hernoemen naar hun AOS-8-naam
en aan de gekozen site en device group toewijzen. Eerst een plan (leest enkel), dan uitvoeren.

Paden volgens developer.arubanetworks.com/new-central(-config)/reference (november 2026):
  GET  /network-monitoring/v1/device-inventory                  APs met serial, MAC, naam, site, device group, scopeId
  GET  /network-config/v1/sites, /network-config/v1/device-groups   scope-id's op naam
  POST /network-config/v1/site-add-devices                      {desScopeId, devices: [serial]}
  POST /network-config/v1/device-groups-add-devices             {desScopeId, devices: [serial]}
  POST /network-config/v1alpha1/system-info/{naam}              hostname, lokaal op de scope van de AP (CAMPUS_AP)

Het hernoemen volgt de werkwijze van HPE's eigen workflow (Rename Hostnames): het System-info-profiel van het
toestel, standaard sys-system-info-profile, krijgt de nieuwe hostname. Te bevestigen in een lab.
"""
import re
from urllib.parse import quote

from . import alias_api as cx
from . import configapi, monitor
from .monitor import ApiFout, Invoer, haal
from .taal import _

MON = "/network-monitoring/v1"
SCOPE = "/network-config/v1"
CFG = "/network-config/v1alpha1"
FUNCTIE = "CAMPUS_AP"
PROFIEL = "sys-system-info-profile"
NAAM = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
PER_KEER = 50
MAX_APS = 10000


def _mac(x):
    h = re.sub(r"[^0-9a-f]", "", str(x or "").lower())
    return h if len(h) == 12 else ""


def _scopes(pad):
    return {str(x.get("scopeName")): str(x.get("scopeId") or x.get("id") or "") for x in configapi._offset_lijst(SCOPE + pad)
            if isinstance(x, dict) and x.get("scopeName")}


def plan(aps, koppeling, hernoemen=True, voortgang=lambda *a: None):
    """aps: [{naam, serial, mac, groep}] uit de inventaris; koppeling: {AP-groep: {site, groep}}. Leest enkel."""
    aps = [a for a in (aps if isinstance(aps, list) else []) if isinstance(a, dict)][:MAX_APS]
    if not aps:
        raise Invoer(_("Lees eerst de inventaris van deze klant in."))
    koppeling = koppeling if isinstance(koppeling, dict) else {}
    voortgang(0, 3, _("APs zoeken in Central"))
    inv = monitor.alles_next(MON + "/device-inventory", {"limit": 1000, "filter": "deviceType eq 'ACCESS_POINT'"})["items"]
    op_serial = {str(d.get("serialNumber") or "").upper(): d for d in inv if isinstance(d, dict) and d.get("serialNumber")}
    op_mac = {_mac(d.get("macAddress")): d for d in inv if isinstance(d, dict) and _mac(d.get("macAddress"))}
    voortgang(1, 3, _("sites en device groups lezen"))
    sites, groepen = _scopes("/sites"), _scopes("/device-groups")
    voortgang(2, 3, _("plan maken"))
    bezet = {}                                 # namen die in Central al aan een ander toestel hangen
    for d in inv:
        if isinstance(d, dict) and d.get("deviceName"):
            bezet.setdefault(str(d["deviceName"]).lower(), str(d.get("serialNumber") or ""))
    gewenst = {}
    for a in aps:
        if a.get("naam"):
            gewenst.setdefault(str(a["naam"]).lower(), []).append(a)

    acties, niet_gevonden, geweigerd, gelijk = [], [], [], 0
    for a in aps:
        naam8 = str(a.get("naam") or "").strip()
        d = op_serial.get(str(a.get("serial") or "").strip().upper()) or op_mac.get(_mac(a.get("mac")))
        if d is None:
            niet_gevonden.append({"naam": naam8, "serial": str(a.get("serial") or ""), "mac": str(a.get("mac") or ""), "groep": str(a.get("groep") or "")})
            continue
        serial = str(d["serialNumber"])
        doel = koppeling.get(str(a.get("groep") or "")) or {}
        x = {"serial": serial, "mac": str(d.get("macAddress") or a.get("mac") or ""), "groep8": str(a.get("groep") or ""),
             "naam_nu": str(d.get("deviceName") or ""), "naam": "", "scope": str(d.get("scopeId") or ""),
             "site_nu": str(d.get("siteName") or ""), "site": "", "site_id": "",
             "groep_nu": str(d.get("deviceGroupName") or ""), "dg": "", "dg_id": "", "status": str(d.get("status") or "")}
        wie = naam8 or serial
        if hernoemen and naam8 and naam8 != x["naam_nu"]:
            andere = bezet.get(naam8.lower())
            if not NAAM.match(naam8):
                geweigerd.append(_("{ap}: naam '{naam}' kan niet in Central (enkel letters, cijfers, punt, liggend streepje en streepje)", ap=serial, naam=naam8))
            elif len(gewenst.get(naam8.lower(), [])) > 1:
                geweigerd.append(_("{ap}: naam '{naam}' staat meer dan eens in de inventaris", ap=serial, naam=naam8))
            elif andere and andere != serial:
                geweigerd.append(_("{ap}: naam '{naam}' hangt in Central al aan {ander}", ap=serial, naam=naam8, ander=andere))
            elif not x["scope"]:
                geweigerd.append(_("{ap}: nog geen scope in Central, hernoemen kan pas na het onboarden", ap=wie))
            else:
                x["naam"] = naam8
        site = str(doel.get("site") or "").strip()
        if site and site != x["site_nu"]:
            if site in sites:
                x["site"], x["site_id"] = site, sites[site]
            else:
                geweigerd.append(_("{ap}: site '{site}' bestaat niet in Central", ap=wie, site=site))
        dg = str(doel.get("groep") or "").strip()
        if dg and dg != x["groep_nu"]:
            if dg in groepen:
                x["dg"], x["dg_id"] = dg, groepen[dg]
            else:
                geweigerd.append(_("{ap}: device group '{groep}' bestaat niet in Central", ap=wie, groep=dg))
        if x["naam"] or x["site"] or x["dg"]:
            acties.append(x)
        else:
            gelijk += 1
    voortgang(3, 3, _("klaar"))
    return {"acties": acties, "niet_gevonden": niet_gevonden, "geweigerd": geweigerd, "gelijk": gelijk,
            "in_central": len(op_serial), "aps": len(aps)}


def _melding(r):
    try:
        j = r.json()
        if isinstance(j, dict):
            return str(j.get("message") or j.get("errorCode") or r.text[:200])
    except ValueError:
        pass
    return r.text[:200]


def _toewijzen(pad, scope_id, serials, uitslag, sleutel, voortgang, gedaan, totaal):
    for i in range(0, len(serials), PER_KEER):
        deel = serials[i:i + PER_KEER]
        voortgang(gedaan[0], totaal, _("{n} APs toewijzen", n=len(deel)))
        r = cx.api("POST", pad, None, {"desScopeId": scope_id, "devices": deel})
        tekst = "ok" if r.status_code < 300 else _("fout {code}: {melding}", code=r.status_code, melding=_melding(r))
        for s in deel:
            uitslag[s][sleutel] = tekst
        gedaan[0] += len(deel)


def _hostname_zetten(x):
    """Zet de hostname in het System-info-profiel op de scope van de AP en leest hem terug."""
    params = {"object-type": "LOCAL", "scope-id": x["scope"], "device-function": FUNCTIE}
    try:
        lokaal = configapi._lijst_uit(configapi._haal_of_leeg(f"{CFG}/system-info", {"view-type": "LOCAL", "scope-id": x["scope"], "device-function": FUNCTIE}), "profile")
    except ApiFout:
        lokaal = []
    namen = [str(p["name"]) for p in lokaal if isinstance(p, dict) and p.get("name")]
    profiel = PROFIEL if PROFIEL in namen or not namen else namen[0]
    body = {"name": profiel, "hostname": x["naam"]}
    pad = f"{CFG}/system-info/{quote(profiel, safe='')}"
    r = cx.api("PATCH" if profiel in namen else "POST", pad, params, body)
    if r.status_code >= 300 and profiel not in namen:          # bestond toch al: bijwerken
        r = cx.api("PATCH", pad, params, body)
    if r.status_code >= 300:
        return _("fout {code}: {melding}", code=r.status_code, melding=_melding(r))
    try:
        terug = configapi._lijst_uit(haal(f"{CFG}/system-info", {"view-type": "LOCAL", "scope-id": x["scope"], "device-function": FUNCTIE,
                                                                 "effective": "true"}), "profile")
    except ApiFout:
        return _("Central meldde ok, terugzien lukte niet")
    if any(isinstance(p, dict) and p.get("hostname") == x["naam"] for p in terug):
        return "ok"
    return _("Central meldde ok, maar de hostname staat er nog niet")


def uitvoeren(acties, voortgang=lambda *a: None):
    """Voert een plan uit: eerst site en device group (per 50), dan de hostnames een voor een."""
    acties = [a for a in acties if isinstance(a, dict) and a.get("serial")]
    uitslag = {a["serial"]: {"site_uit": "", "dg_uit": "", "naam_uit": ""} for a in acties}
    totaal = sum(bool(a.get("site")) + bool(a.get("dg")) + bool(a.get("naam")) for a in acties)
    gedaan = [0]
    for sleutel, veld, pad in (("site_uit", "site_id", SCOPE + "/site-add-devices"), ("dg_uit", "dg_id", SCOPE + "/device-groups-add-devices")):
        per_scope = {}
        for a in acties:
            if a.get(veld):
                per_scope.setdefault(a[veld], []).append(a["serial"])
        for scope_id, serials in per_scope.items():
            _toewijzen(pad, scope_id, serials, uitslag, sleutel, voortgang, gedaan, totaal)
    for a in acties:
        if a.get("naam") and a.get("scope"):
            voortgang(gedaan[0], totaal, _("{ap} hernoemen", ap=a["naam"]))
            monitor.serial(a["scope"])
            uitslag[a["serial"]]["naam_uit"] = _hostname_zetten(a)
            gedaan[0] += 1
    voortgang(totaal, totaal, _("klaar"))
    return [dict(a, **uitslag[a["serial"]]) for a in acties]

"""Een nagemaakte new Central voor de tabbladen Switches en Overzicht: antwoorden in de vorm van de API-referentie.
Gebruikt door de tests, en om het scherm lokaal te bekijken zonder echte Central."""
import json
import re
from urllib.parse import unquote

SWITCHES = [
    {"id": "SG00TEST01", "type": "switch", "serialNumber": "SG00TEST01", "macAddress": "00:00:00:00:00:01", "deviceName": "SITE01-SW01",
     "model": "6200M 48G", "deployment": "Standalone", "siteName": "SITE01", "siteId": "1001", "firmwareVersion": "10.16.1051",
     "deviceFunction": "ACCESS_SWITCH", "ipv4": "10.10.120.21", "status": "ONLINE", "uptimeInMillis": 259200000,
     "switchTrends": [{"cpuUtilization": 7, "memoryUtilization": 41, "poeAvailable": 740, "poeConsumption": 96.5, "systemTemperature": 38}]},
    {"id": "SG00TEST02", "type": "switch", "serialNumber": "SG00TEST02", "macAddress": "00:00:00:00:00:02", "deviceName": "SITE01-SW02",
     "model": "6200M 48G", "deployment": "Standalone", "siteName": "SITE01", "siteId": "1001", "firmwareVersion": "10.16.1051",
     "ipv4": "10.10.120.22", "status": "OFFLINE", "lastSeenAt": "2026-11-16T08:00:00.000Z"},
    {"id": "STACK01", "type": "switch", "serialNumber": "SG00TEST03", "macAddress": "00:00:00:00:00:03", "deviceName": "SITE02-STACK",
     "model": "6300M", "deployment": "Stack", "stackId": "STACK01", "siteName": "SITE02", "siteId": "1002", "firmwareVersion": "10.16.1040",
     "ipv4": "10.20.120.20", "status": "ONLINE"},
]
for _s, _extra in zip(SWITCHES, ({"scopeId": "d1", "deviceFunction": "ACCESS_SWITCH", "deviceGroupName": "ACCESS", "isProvisioned": "Yes"},
                                 {"scopeId": "d2", "deviceFunction": "-", "deviceGroupName": "", "isProvisioned": "No"},
                                 {"scopeId": "d3", "deviceFunction": "ACCESS_SWITCH", "deviceGroupName": "ACCESS_VSF", "isProvisioned": "Yes"})):
    _s.update(_extra)
GATEWAYS = [
    {"id": "GW0TEST01", "type": "gateway", "serialNumber": "GW0TEST01", "macAddress": "00:00:00:00:00:09", "deviceName": "GW-SITE01-01",
     "model": "7210", "siteName": "SITE01", "siteId": "1001", "deviceFunction": "MOBILITY_GW", "deviceGroupName": "WIRELESS",
     "scopeId": "d9", "ipv4": "172.16.0.9", "status": "ONLINE", "isProvisioned": "Yes"},
]
# APs (na een migratie uit AOS 8): enkel in de lijsten als de filter om APs vraagt, of met MET_APS (snapshots)
APS = [
    {"id": "CNAP0001", "type": "ap", "serialNumber": "CNAP0001", "macAddress": "aa:bb:cc:00:00:01", "deviceName": "aa:bb:cc:00:00:01",
     "model": "AP-635", "siteName": "", "siteId": "", "deviceGroupName": "", "deviceFunction": "CAMPUS_AP", "scopeId": "a1",
     "status": "ONLINE", "firmwareVersion": "10.7.1.0", "ipv4": "10.30.0.11"},
    {"id": "CNAP0002", "type": "ap", "serialNumber": "CNAP0002", "macAddress": "aa:bb:cc:00:00:02", "deviceName": "OUD-AP-2",
     "model": "AP-635", "siteName": "SITE01", "siteId": "1001", "deviceGroupName": "WIRELESS", "deviceFunction": "CAMPUS_AP", "scopeId": "a2",
     "status": "ONLINE", "firmwareVersion": "10.7.1.0", "ipv4": "10.30.0.12"},
]
MET_APS = False
CLIENTS = [{"clientConnectionType": "Wireless", "wlanName": "CORP", "connectedDeviceSerial": "CNAP0001", "macAddress": "11:11:11:11:11:01"}] * 6 + \
          [{"clientConnectionType": "Wired", "connectedDeviceSerial": "SG00TEST01", "macAddress": "11:11:11:11:11:99"}]
POORT_WIJZIGING = {}   # (serial, poort) -> velden die anders zijn (voor een tweede snapshot)
HOSTNAMES = {}         # scope-id van een AP -> hostname uit het System-info-profiel
AANROEPEN = []
GEWIST = set()        # (scope-id, profiel-pad, sleutel) van lokaal gewiste objecten

# configuratie-API
CFG = "/network-config/v1alpha1"
SITES = [{"id": "1001", "scopeId": "1001", "scopeName": "SITE01", "collectionName": "Belgium"},
         {"id": "1002", "scopeId": "1002", "scopeName": "SITE02", "collectionName": "Belgium"}]
GROEPEN = [{"id": "g10", "scopeId": "g10", "scopeName": "ACCESS"}, {"id": "g11", "scopeId": "g11", "scopeName": "ACCESS_VSF"},
           {"id": "g12", "scopeId": "g12", "scopeName": "WIRELESS"}]


def _alias(naam, typ, waarde):
    sleutel = {"ALIAS_VLAN_DESCRIPTION": ("vlan-description-value", "description"), "ALIAS_IPV4_ADDRESS_TYPE": ("ipv4-address-value", "ipv4-address")}[typ]
    return {"name": naam, "type": typ, "default-value": {sleutel[0]: {sleutel[1]: waarde}}}


ALIASSEN = {
    "LIBRARY": [_alias("sys_vlan_2000_description", "ALIAS_VLAN_DESCRIPTION", "Clients")],
    "g1": [_alias("sys_vlan_120_description", "ALIAS_VLAN_DESCRIPTION", "MGMT")],
    "1001": [_alias("sys_vlan_120_description", "ALIAS_VLAN_DESCRIPTION", "Beheer")],
    "d1": [_alias("sys_vlan_ipv4_120", "ALIAS_IPV4_ADDRESS_TYPE", "10.10.120.21/24"),
           _alias("sys_vlan_120_description", "ALIAS_VLAN_DESCRIPTION", "Beheer-oud")],
    # gateway: uplink via DHCP op VLAN 4094, beheer-IP op VLAN 120 (zoals een bulk-download van een gateway)
    "d9": [_alias("sys_vlan_ipv4_4094", "ALIAS_IPV4_ADDRESS_TYPE", "DHCP"), _alias("sys_vlan_ipv4_120", "ALIAS_IPV4_ADDRESS_TYPE", "10.10.120.5/24")],
}


def _config(method, pad, p):
    if pad == "/network-config/v1/global":
        return Antwoord(200, {"id": "g1", "scopeId": "g1", "type": "network-config/global"})
    if pad in ("/network-config/v1/site-collections", "/network-config/v1/sites", "/network-config/v1/device-groups"):
        items = {"site-collections": [{"id": "c1", "scopeId": "c1", "scopeName": "Belgium"}], "sites": SITES, "device-groups": GROEPEN}[pad.rsplit("/", 1)[1]]
        deel = items[int(p.get("offset", 0)):int(p.get("offset", 0)) + int(p.get("limit", 100))]
        return Antwoord(200, {"items": deel, "count": len(deel), "total": len(items), "offset": None})
    if pad == CFG + "/aliases":
        lijst = ALIASSEN["LIBRARY"] if p.get("view-type") == "LIBRARY" else ALIASSEN.get(p.get("scope-id"))
        return Antwoord(200, {"alias": lijst}) if lijst else Antwoord(404, {"errorCode": "ERR_CN003", "message": "Not found"})
    if pad == CFG + "/config-assignments":
        if p.get("scope-id") == "g1":
            return Antwoord(200, {"config-assignment": [{"profile-type": "aliases", "profile-instance": "sys_vlan_2000_description",
                                                         "device-function": "ACCESS_SWITCH", "scope-id": "g1"},
                                                        {"profile-type": "system-info", "profile-instance": "campus-access-sys",
                                                         "device-function": "ACCESS_SWITCH", "scope-id": "g1"}]})
        if p.get("scope-id") == "g10":        # device group ACCESS: eigen hostnameprofiel, wint van Global
            return Antwoord(200, {"config-assignment": [{"profile-type": "system-info", "profile-instance": "ORG_Hostname",
                                                         "device-function": "ALL", "scope-id": "g10"}]})
        if p.get("scope-id") == "d3":         # switch uit Classic: de import wijst zijn eigen profiel toe op de switch
            return Antwoord(200, {"config-assignment": [{"profile-type": "system-info", "profile-instance": "sys-system-info-profile",
                                                         "device-function": "ACCESS_SWITCH", "scope-id": "d3"}]})
        return Antwoord(404, {"errorCode": "ERR_CN003", "message": "Not found"})
    if pad == CFG + "/system-info":
        if str(p.get("scope-id", "")).startswith("a"):
            if p["scope-id"] in HOSTNAMES:
                return Antwoord(200, {"profile": [{"name": "sys-system-info-profile", "hostname": HOSTNAMES[p["scope-id"]]}]})
            return Antwoord(404, {"errorCode": "ERR_CN003", "message": "Not found"})
        if p.get("scope-id") == "d3":         # switch uit Classic: eigen profiel van de import
            return Antwoord(200, {"profile": [{"name": "sys-system-info-profile", "hostname": "SITE02-STACK"}]})
        if p.get("scope-id") == "d9":         # gateway: eigen profiel op het toestel
            return Antwoord(200, {"profile": [{"name": "sys-system-info-profile", "hostname": "GW-SITE01-01"}]})
        return Antwoord(200, {"profile": [{"name": "campus-access-sys"}, {"name": "lab-profiel"}]})
    if pad == CFG + "/mgmt-interfaces":
        return Antwoord(200, {"profile": [{"name": "mgmt"}]})
        return Antwoord(200, {"config-assignment": []})
    if pad == CFG + "/config-health/devices":
        devs = [{"serial": "SG00TEST01", "configStatus": "SYNCHRONIZED"},
                {"serial": "SG00TEST03", "configStatus": "OUT_OF_SYNC", "topPriorityIssue": "Push failed", "recommendedAction": "Resync"}]
        return Antwoord(200, {"devices": devs, "count": 2, "total": 2, "offset": 0})
    if pad == CFG + "/config-health/active-issue":
        return Antwoord(200, {"configPushFailures": [{"id": "1", "issue": "Push failed", "recommendedAction": "Resync", "timestamp": "1794900000000"}],
                              "invalidConfig": [{"id": "2", "issueDescription": "VLAN 30 bestaat niet", "profileName": "UPLINK", "profileType": "sw-port-profiles",
                                                 "assignedScope": "1002", "assignedScopeType": "SCOPE_TYPE_SITE"}]})
    if pad == CFG + "/layer2-vlan":
        # Zoals echte Central: op de scope van een switch zie je met view-type LOCAL en de juiste device
        # function wat lokaal op die switch staat; zonder (of met een andere) function niets.
        if p.get("scope-id") == "d1" and p.get("device-function") == "ACCESS_SWITCH":      # lokale overrides op SITE01-SW01
            return Antwoord(200, {"l2-vlan": [{"vlan": 10, "name": "DATA-OUD"}, {"vlan": 999, "name": "TEST"}, {"vlan": 120, "name": "MGMT", "description": "beheer"}]})
        if str(p.get("scope-id", "")).startswith("d"):
            return Antwoord(404, {"errorCode": "ERR_CN003", "message": "Not found"})
        vlans = [{"vlan": 10, "name": "DATA"}, {"vlan": 120, "name": "MGMT", "description": "beheer"}]
        if p.get("scope-id") == "1002":
            vlans = [{"vlan": 10, "name": "DATA"}, {"vlan": 120, "name": "MGMT", "description": "management"}, {"vlan": 30, "name": "VOICE"}]
        return Antwoord(200, {"l2-vlan": vlans})
    if pad == CFG + "/dns":
        return Antwoord(200, {"profile": [{"name": "dns", "name-server": [{"ip": "10.0.0.53", "priority": 1}]}]})
    if pad == CFG + "/firmware-compliance":
        return Antwoord(200, {"name": "standaard", "version-chart": {"version": "10.16.1051"}})
    if pad == CFG + "/snmp":
        return Antwoord(500, {"errorCode": "ERR_C001", "message": "intern"})
    return None


class Antwoord:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.headers = status, data, {}
        self.text = json.dumps(data) if data is not None else ""

    def json(self):
        if self._data is None:
            raise ValueError("geen JSON")
        return self._data


def _pagina(items, params, sleutel="next"):
    return {"items": items, "count": len(items), "total": len(items), sleutel: None}


def api(method, pad, params=None, body=None):
    AANROEPEN.append((method, pad, params, body))
    p = params or {}
    if method == "DELETE" and pad.startswith(CFG + "/"):
        basis, _, sleutel = pad[len(CFG) + 1:].rpartition("/")
        k = (p.get("scope-id"), basis, unquote(sleutel))
        if p.get("object-type") != "LOCAL" or k in GEWIST:
            return Antwoord(400, {"message": "unexpected req_xpath"})
        GEWIST.add(k)
        return Antwoord(200, {"message": "Success."})
    if method == "GET" and pad.startswith("/network-config/"):
        r = _config(method, pad, p)
        if r is not None and str(p.get("scope-id", "")).startswith("d") and r.status_code == 200 and isinstance(r._data, dict):
            from cnx_api.configapi import PROFIELEN, _id
            basis = pad[len(CFG) + 1:]
            sleutel = next((x[3] for x in PROFIELEN if x[1] == basis), None)
            data = {k: [x for i, x in enumerate(v) if (p.get("scope-id"), basis, _id(x, sleutel, i)) not in GEWIST] if isinstance(v, list) else v
                    for k, v in r._data.items()}
            return Antwoord(200, data)
        if r is not None:
            return r
    if method in ("POST", "PATCH") and pad.startswith(CFG + "/system-info/") and str(p.get("scope-id", "")).startswith("a"):
        if p.get("object-type") != "LOCAL" or p.get("device-function") != "CAMPUS_AP":
            return Antwoord(400, {"message": "object-type LOCAL en device-function nodig"})
        if method == "POST" and p["scope-id"] in HOSTNAMES:
            return Antwoord(400, {"message": "profile already exists"})
        HOSTNAMES[p["scope-id"]] = (body or {}).get("hostname")
        for ap in APS:
            if ap["scopeId"] == p["scope-id"]:
                ap["deviceName"] = HOSTNAMES[p["scope-id"]]
        return Antwoord(200, {"message": "Success."})
    if method == "POST" and pad in ("/network-config/v1/site-add-devices", "/network-config/v1/device-groups-add-devices",
                                    "/network-config/v1alpha1/persona-assignment/ACCESS_SWITCH"):
        b = body or {}
        serials = b.get("devices") or b.get("device-id") or []
        for sw in SWITCHES + APS:
            if sw["serialNumber"] in serials:
                if pad.endswith("site-add-devices"):
                    site = next(x for x in SITES if x["scopeId"] == b["desScopeId"])
                    sw.update(siteName=site["scopeName"], siteId=site["scopeId"])
                elif pad.endswith("device-groups-add-devices"):
                    sw["deviceGroupName"] = next(x["scopeName"] for x in GROEPEN if x["scopeId"] == b["desScopeId"])
                else:
                    sw["deviceFunction"] = "ACCESS_SWITCH"
                if sw.get("siteName") and sw.get("deviceFunction") and sw.get("deviceGroupName"):
                    sw["isProvisioned"] = "Yes"
        return Antwoord(200, {"items": [], "code": "OK", "status": "SUCCESS", "message": "Success."})
    if method == "GET" and pad == "/network-monitoring/v1/switches":
        return Antwoord(200, _pagina(SWITCHES, p))
    m = re.fullmatch(r"/network-monitoring/v1/switches/([^/]+)(/[a-z-]+)?", pad)
    if method == "GET" and m:
        sn, deel = m.group(1), m.group(2) or ""
        sw = next((s for s in SWITCHES if sn in (s["serialNumber"], s.get("stackId"))), None)
        if not sw:
            return Antwoord(404, {"errorCode": "HPE_GL_NETWORK_MONITORING_DEVICE_NOT_FOUND", "message": "Device not found"})
        if deel == "":
            return Antwoord(200, dict(sw, health="Good", lastRestartReason="Reboot requested", healthReasons={"poorReasons": [], "fairReasons": []}))
        if deel == "/interfaces":
            return Antwoord(200, {"items": [dict(x, **POORT_WIJZIGING.get((sn, x["name"]), {})) for x in [
                {"id": "1/1/1", "name": "1/1/1", "index": 1, "status": "Up", "adminStatus": "Up", "operStatus": "Up", "speed": 1000, "duplex": "Full",
                 "vlanMode": "Access", "nativeVlan": 10, "allowedVlanIds": [10], "poeStatus": "Delivering", "neighbour": "AP-01", "neighbourPort": "eth0"},
                {"id": "1/1/2", "name": "1/1/2", "index": 2, "status": "Down", "adminStatus": "Up", "operStatus": "Down", "speed": 0, "vlanMode": "Access",
                 "nativeVlan": 10, "portError": ["CRC"]},
                {"id": "1/1/49", "name": "1/1/49", "index": 49, "status": "Up", "adminStatus": "Up", "operStatus": "Up", "speed": 10000, "vlanMode": "Trunk",
                 "allowedVlanIds": [10, 20, 120], "uplink": True, "neighbour": "CORE-01", "neighbourPort": "1/1/12", "lag": "lag1"}]],
                "count": 3, "total": 3, "offset": None})
        if deel == "/vlans":
            return Antwoord(200, {"items": [{"id": "10", "name": "DATA", "type": "Static", "status": "Up", "voice": "Disabled", "interfaces": ["1/1/1-1/1/48"]},
                                            {"id": "120", "name": "MGMT", "type": "Static", "status": "Up", "ipv4": "10.10.120.21/24", "voice": "Disabled"}],
                                  "count": 2, "total": 2, "offset": None})
        if deel == "/interface-poe":
            return Antwoord(200, {"items": [{"id": "1/1/1", "name": "1/1/1", "powerDrawnInWatts": 12.4, "powerDeniedCount": 0}], "count": 1, "total": 1})
        if deel == "/lag":
            return Antwoord(200, {"items": [{"id": "lag1", "type": "LACP", "name": "lag1", "count": 2, "ports": ["1/1/49", "1/1/50"]}], "count": 1})
        if deel == "/vsx":
            return Antwoord(200, {})
        if deel == "/hardware-categories":
            return Antwoord(200, {"items": [{"id": sn, "type": "x", "model": sw["model"], "status": "Up", "cpu": {"health": "Good"}, "memory": {"health": "Good"},
                                             "temperature": {"health": "Good"}, "fans": {"health": "Good", "totalCount": 2, "upCount": 2},
                                             "powerSupplies": {"health": "Good", "totalCount": 1, "upCount": 1}}], "count": 1})
        if deel == "/hardware-trends":
            return Antwoord(200, {"id": sn, "type": "x", "keys": ["cpuUtilization,memoryUtilization"], "units": ["%,%"],
                                  "switchMetrics": [{"serialNumber": sn, "samples": [{"timestamp": 1794900000 + i * 300, "data": [5 + i % 4, 40 + i % 3]} for i in range(12)]}]})
    if method == "GET" and re.fullmatch(r"/network-monitoring/v1/stack/[^/]+/members", pad):
        return Antwoord(200, {"items": [{"id": "STACK01", "type": "x", "stackType": "VSF", "topology": "Ring", "members": [
            {"stackMemberId": 1, "deviceName": "SITE02-STACK", "serialNumber": "SG00TEST03", "model": "6300M", "switchRole": "Conductor", "status": "ONLINE"},
            {"stackMemberId": 2, "deviceName": "SITE02-STACK", "serialNumber": "SG00TEST04", "model": "6300M", "switchRole": "Standby", "status": "ONLINE"}]}], "count": 1})
    if method == "GET" and pad.startswith("/network-monitoring/v1/neighbours/"):
        return Antwoord(200, {"id": "1", "type": "Neighbours", "neighbours": [
            {"name": "CORE-01", "type": "SWITCH", "serial": "CORE0001", "health": "Good", "localPort": "1/1/49", "toPort": "1/1/12", "siteName": "SITE01"}]})
    if method == "GET" and pad.startswith("/network-monitoring/v1/topology/"):
        return Antwoord(200, {"id": "1001", "type": "Topology",
                              "devices": [{"serial": "SG00TEST01", "name": "SITE01-SW01", "health": "Good", "model": "6200M", "deviceFunction": "ACCESS_SWITCH"},
                                          {"serial": "CORE0001", "name": "CORE-01", "health": "Fair", "healthReason": "High CPU"}],
                              "links": [{"from": "SG00TEST01", "to": "CORE0001", "speed": 10, "health": "Good", "edgeType": "Uplink",
                                         "fromPortList": [{"name": "1/1/49"}], "toPortList": [{"name": "1/1/12"}]}]})
    if method == "GET" and pad.startswith("/network-monitoring/v1/site-health/"):
        return Antwoord(200, {"id": "1001", "health": {"groups": [{"name": "Good", "value": 3}]}, "deviceTypes": [{"name": "Switches", "health": {"groups": [{"name": "Good", "value": 2}]}}]})
    if method == "GET" and pad == "/network-monitoring/v1/sites-health":
        return Antwoord(200, {"items": [{"id": "1001", "siteName": "SITE01", "health": {"groups": [{"name": "Good", "value": 2}, {"name": "Poor", "value": 1}]},
                                         "devices": {"count": 3}, "clients": {"count": 40}, "alerts": {"totalCount": 1}, "reasons": [], "address": {"city": "Antwerpen"}},
                                        {"id": "1002", "siteName": "SITE02", "health": {"groups": [{"name": "Good", "value": 1}]}, "devices": {"count": 1}, "clients": {"count": 5}}],
                              "count": 2, "total": 2, "offset": 0, "response": {"status": "SUCCESS"}})
    if method == "GET" and pad == "/network-monitoring/v1/sites-device-health":
        return Antwoord(200, {"items": [{"id": "1001", "siteName": "SITE01", "deviceTypes": [{"name": "Switches", "health": {"groups": [{"name": "Good", "value": 1}, {"name": "Poor", "value": 1}]}}]}],
                              "count": 1, "total": 1, "offset": 0})
    if method == "GET" and pad in ("/network-monitoring/v1/devices", "/network-monitoring/v1/device-inventory"):
        f = str(p.get("filter") or "")
        if "ACCESS_POINT" in f:
            alle = [dict(a, deviceType="ACCESS_POINT") for a in APS]
        else:
            alle = ([dict(s, deviceType="SWITCH", configStatus="Synchronized") for s in SWITCHES] if "GATEWAY" not in f else []) + \
                   ([dict(g, deviceType="GATEWAY", configStatus="Synchronized") for g in GATEWAYS] if "SWITCH" not in f else []) + \
                   ([dict(a, deviceType="ACCESS_POINT") for a in APS] if MET_APS and not f else [])
        return Antwoord(200, _pagina(alle, p))
    if method == "GET" and pad == "/network-monitoring/v1/clients":
        return Antwoord(200, _pagina(CLIENTS, p))
    if method == "GET" and pad == "/network-services/v1/firmware-details":
        return Antwoord(200, _pagina([{"serialNumber": s["serialNumber"], "deviceName": s["deviceName"], "deviceType": "SWITCH", "firmwareVersion": s["firmwareVersion"],
                                       "recommendedVersion": "10.16.1051", "upgradeStatus": "Up To Date" if s["firmwareVersion"] == "10.16.1051" else "Upgrade Available",
                                       "siteName": s["siteName"]} for s in SWITCHES], p))
    if method == "GET" and pad == "/network-notifications/v1/alerts":
        return Antwoord(200, _pagina([{"id": "a1", "name": "Switch offline", "severity": "Critical", "priority": "High", "status": "Active", "category": "System",
                                       "summary": "SITE01-SW02 is offline", "createdAt": "2026-11-16T08:01:00Z", "deviceType": "Switch"}], p))
    if method == "GET" and pad == "/network-services/v1/audits":
        return Antwoord(200, {"items": [{"id": "x", "occurredOn": "2026-11-17T09:00:00.000Z", "source": "beheerder@example.com", "category": "Configuration",
                                         "subCategory": "Alias", "action": "Create", "destinationName": "Global", "description": "Alias aangemaakt"}],
                              "count": 1, "offset": 1, "total": 1})
    if method == "GET" and pad == "/network-troubleshooting/v1/events":
        return Antwoord(200, {"events": [{"eventId": "1", "timeAt": "2026-11-17T08:00:00.000Z", "eventName": "Port down", "category": "Connectivity", "severity": "negative",
                                          "sourceName": "SITE01-SW01", "description": "1/1/2 down", "reason": "Link loss"}], "count": 1, "total": 1, "next": None})
    m = re.fullmatch(r"/network-troubleshooting/v1/cx/([^/]+)/(ping|traceroute|http|aaa|showCommands|show-commands|locate|list-tasks)(/async-operations/([^/]+))?", pad)
    if m:
        sn, soort, taak = m.group(1), m.group(2), m.group(4)
        if soort == "show-commands":
            return Antwoord(200, [{"categoryName": "System", "count": 2, "commands": [{"command": "show version"}, {"command": "show system"}]},
                                  {"categoryName": "Interfaces", "count": 1, "commands": [{"command": "show interface brief"}]}])
        if soort == "list-tasks":
            return Antwoord(200, [])
        if soort == "locate":
            return Antwoord(202, {"status": "INITIATED", "startTime": "2026-11-17T10:00:00Z"})
        if method == "POST":
            return Antwoord(202, {"location": f"/network-troubleshooting/v1/cx/{sn}/{soort}/async-operations/1a7a4e3d-6ab8-4d34-93cf-7443e0f32bbe",
                                  "status": "INITIATED", "startTime": "2026-11-17T10:00:00Z"})
        uit = {"ping": {"destination": "8.8.8.8", "resolvedIp": "8.8.8.8", "transmittedPacketsCount": "5", "receivedPacketsCount": "5", "packetLossPercent": "0",
                        "minimumRoundTripTimeMilliseconds": "4.1", "averageRoundTripTimeMilliseconds": "4.6", "maximumRoundTripTimeMilliseconds": "5.2"},
               "traceroute": {"destination": "8.8.8.8", "hops": [{"hop": "1", "probes": [{"ipAddress": "10.10.120.1", "responseTimeMilliseconds": "0.6"}]},
                                                                  {"hop": "2", "probes": [{"ipAddress": "8.8.8.8", "reverseDnsResolution": "dns.google", "responseTimeMilliseconds": "4.2"}]}]},
               "http": {"destination": "www.example.com", "results": {"httpTransactionRttInMilliseconds": "120", "resolvedIp": "93.184.215.14"}, "statistics": {"probesTransmitted": "1"}},
               "aaa": {"authenticationStatus": "accept", "username": "test", "authMethodType": "pap", "radiusServerIp": "10.0.0.5"},
               "showCommands": {"commands": ["show version"], "results": [{"command": "show version", "output": "ArubaOS-CX\nVersion : FL.10.16.1051"}]}}[soort]
        return Antwoord(200, {"status": "COMPLETED", "progressPercent": 100, "startTime": "2026-11-17T10:00:00Z", "endTime": "2026-11-17T10:00:04Z", "output": uit,
                              "rawOutput": "PING 8.8.8.8: 5 packets, 0% loss" if soort == "ping" else None})
    return Antwoord(404, {"errorCode": "NOT_FOUND", "message": f"nep-Central kent {method} {pad} niet"})

"""Een nagemaakte GreenLake (devices, async-operations, service catalog, subscriptions) voor de tests, in de vorm van
developer.greenlake.hpe.com. Vervangt glponboard._verzend."""
import json
import re
import uuid
from urllib.parse import urlparse

GLP = "https://global.api.greenlake.hpe.com"
SM_CENTRAL = "0892c36d-40df-4f26-923b-76b5d213b420"


class Antwoord:
    def __init__(self, status, data=None, headers=None):
        self.status_code, self._data, self.headers = status, data, headers or {}
        self.text = json.dumps(data) if data is not None else ""

    def json(self):
        if self._data is None:
            raise ValueError("geen JSON")
        return self._data


def nieuw():
    """Begintoestand: een AP al in GreenLake (zonder applicatie), subscriptions voor APs en switches."""
    return {
        "devices": {"CNAP0002": {"id": "glp-ap2", "serialNumber": "CNAP0002", "macAddress": "aa:bb:cc:00:00:02", "deviceType": "AP",
                                 "application": None, "region": None, "subscription": []}},
        "async": {},
        "subs": [{"id": "sub-ap", "key": "KEYAP", "subscriptionType": "CENTRAL_AP", "tier": "FOUNDATION_AP", "quantity": "10",
                  "availableQuantity": "4", "subscriptionStatus": "STARTED", "endTime": "2028-01-01T00:00:00Z"},
                 {"id": "sub-sw", "key": "KEYSW", "subscriptionType": "CENTRAL_SWITCH", "tier": "FOUNDATION_SWITCH_6200", "quantity": "5",
                  "availableQuantity": "1", "subscriptionStatus": "STARTED", "endTime": "2028-01-01T00:00:00Z"}],
        "aanroepen": [],
        "na_toevoegen": [],        # callbacks (bv. het toestel ook in de nagemaakte Central zetten)
    }


STAAT = nieuw()


def _pagina(items, params):
    off, lim = int((params or {}).get("offset", 0)), int((params or {}).get("limit", 2000))
    return {"items": items[off:off + lim], "count": len(items[off:off + lim]), "offset": off, "total": len(items)}


def _async(status="SUCCEEDED", result=None):
    aid = str(uuid.uuid4())
    STAAT["async"][aid] = {"id": aid, "type": "devices/asyncOperation", "status": "RUNNING", "eind": status, "result": result,
                           "suggestedPollingIntervalSeconds": 1}
    return Antwoord(202, {"code": 0, "status": "100 CONTINUE", "transactionId": aid},
                    {"Location": f"/devices/v1/async-operations/{aid}"})


def verzend(v, method, url, params, body, kop):
    p = dict(params or {})
    pad = urlparse(url).path
    STAAT["aanroepen"].append((method, pad, p, body, kop))
    if "Authorization" not in v.s.headers:
        return Antwoord(401, {"message": "unauthorized"})
    dry = p.get("dry-run") == "true"
    if method == "GET" and pad == "/devices/v1/devices":
        alle = list(STAAT["devices"].values())
        m = re.match(r"serialNumber in (.*)$", str(p.get("filter") or ""))
        if m:
            wil = set(re.findall(r"'([^']+)'", m.group(1)))
            alle = [d for d in alle if d["serialNumber"] in wil]
        return Antwoord(200, _pagina(alle, p))
    if method == "POST" and pad == "/devices/v1/devices":
        assert set(body) == {"network", "compute", "storage"} and len(body["network"]) <= 5
        fout = [d["serialNumber"] for d in body["network"] if d["serialNumber"].startswith("FOUT")]
        if not dry:
            for d in body["network"]:
                if d["serialNumber"] not in fout:
                    STAAT["devices"][d["serialNumber"]] = {"id": "glp-" + d["serialNumber"].lower(), "serialNumber": d["serialNumber"],
                                                          "macAddress": d["macAddress"], "application": None, "subscription": []}
                    for cb in STAAT["na_toevoegen"]:
                        cb(d)
        return _async("SUCCEEDED", {"succeededDevices": [d["serialNumber"] for d in body["network"] if d["serialNumber"] not in fout],
                                    "failedDevices": [{"serialNumber": s, "message": "Device not found in HPE records"} for s in fout]})
    if method == "PATCH" and pad == "/devices/v1/devices":
        assert kop == {"Content-Type": "application/merge-patch+json"}
        ids = p["id"]
        assert len(ids) <= 5 and len(body) in (1, 2) and not ("application" in body and "subscription" in body)
        if not dry:
            for d in STAAT["devices"].values():
                if d["id"] in ids:
                    if "application" in body:
                        d["application"], d["region"] = {"id": body["application"]["id"]}, body["region"]
                    if "subscription" in body:
                        d["subscription"] = [{"id": s["id"]} for s in body["subscription"]]
        return _async("SUCCEEDED", None)
    m = re.fullmatch(r"/devices/v1/async-operations/([^/]+)", pad)
    if method == "GET" and m:
        a = STAAT["async"][m.group(1)]
        if a.get("gezien"):                   # de eerste keer nog bezig, daarna klaar
            a["status"] = a["eind"]
        a["gezien"] = True
        return Antwoord(200, {k: w for k, w in a.items() if k not in ("eind", "gezien")})
    if method == "GET" and pad == "/service-catalog/v1/service-managers":
        return Antwoord(200, _pagina([{"id": SM_CENTRAL, "name": "HPE Aruba Networking Central"}, {"id": "sm-andere", "name": "Compute Ops Management"}], p))
    if method == "GET" and pad == "/service-catalog/v1/service-manager-provisions":
        return Antwoord(200, _pagina([{"id": "prov-1", "serviceManager": {"id": SM_CENTRAL}, "region": "eu-central", "provisionStatus": "PROVISIONED"},
                                      {"id": "prov-2", "serviceManager": {"id": "sm-andere"}, "region": "eu-central", "provisionStatus": "PROVISIONED"}], p))
    if method == "GET" and pad == "/subscriptions/v1/subscriptions":
        return Antwoord(200, _pagina(STAAT["subs"], p))
    return Antwoord(404, {"message": f"nep-GreenLake kent {method} {pad} niet"})

"""AOS-8 naar AOS-10: een inventaris van een mobility conductor inlezen en beoordelen. Leest enkel bestanden.

Invoer, een of meer bestanden:
  - een Excel-export (.xlsx) met de AP-lijst (kolommen van `show ap database long`) en de controllerlijst
    (kolommen van `show switches`), op aparte bladen;
  - dezelfde lijsten als CSV;
  - de tekst-uitvoer van `show ap database long` en `show switches` zoals op de CLI van de conductor.

Uitvoer: per AP en per controller of het model AOS-10 ondersteunt (data/aos10-modellen.json), de clusters
(controllers die samen APs bedienen, uit Switch IP en Standby IP van de APs), de AP-groepen, wat je best opkuist
voor de migratie, en een rapport als HTML voor de klant.
"""
import base64, csv, datetime, html, io, json, re, zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from . import resource
from .taal import _, huidig


class Fout(Exception):
    pass


# ---------------------------------------------------------------- inlezen

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _kolom(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


# Grenzen tegen kwaadaardige bestanden: een klein .xlsx kan uitgepakt gigabytes worden, en een cel in de laatste
# kolom (XFD) maakt van elke rij een lijst van 16.384 waarden. Een echte inventaris (3.000 APs: ongeveer 40.000 cellen,
# 2 MB XML) blijft ver onder deze grenzen. De bladen worden rij per rij gelezen, nooit als een boom in het geheugen.
MAX_UITGEPAKT = 20 * 1024 * 1024     # bytes, alle gelezen onderdelen van een .xlsx samen
MAX_ONDERDELEN = 500                 # bestanden in de zip
MAX_KOLOMMEN = 256
MAX_RIJEN = 100_000                  # per blad
MAX_CELLEN = 1_000_000               # per bestand
MAX_BESTANDEN = 10                   # per inlezing


def _onderdeel(z, naam, teller):
    """Een XML-onderdeel van de zip als bytes, met de grens op de uitgepakte grootte en zonder DOCTYPE (entiteiten)."""
    info = z.getinfo(naam)
    teller[0] += info.file_size
    if info.file_size > MAX_UITGEPAKT or teller[0] > MAX_UITGEPAKT:
        raise Fout(_("Excel-bestand te groot uitgepakt (maximum 20 MB)"))
    with z.open(info) as f:
        data = f.read(MAX_UITGEPAKT + 1)
    if len(data) > MAX_UITGEPAKT or b"<!DOCTYPE" in data[:4096].upper():
        raise Fout(_("Excel-bestand niet aanvaard (te groot of met een DOCTYPE)"))
    return data


def _elementen(data, tag):
    """Elk afgesloten element met deze tag, waarna het gewist wordt: geheugen per element, niet per blad."""
    volledig = f"{{{NS['m']}}}{tag}"
    for _gebeurtenis, el in ET.iterparse(io.BytesIO(data), events=("end",)):
        if el.tag == volledig:
            yield el
            el.clear()


def lees_xlsx(data):
    """{bladnaam: [rijen]} uit een .xlsx, enkel met de standaardbibliotheek. Waarden als tekst."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise Fout(_("geen geldig Excel-bestand (.xlsx)"))
    with z:
        if len(z.infolist()) > MAX_ONDERDELEN:
            raise Fout(_("Excel-bestand met te veel onderdelen"))
        namen = set(z.namelist())
        if "xl/_rels/workbook.xml.rels" not in namen or "xl/workbook.xml" not in namen:
            raise Fout(_("geen geldig Excel-bestand (.xlsx)"))
        teller, cellen = [0], 0
        gedeeld = []
        if "xl/sharedStrings.xml" in namen:
            for si in _elementen(_onderdeel(z, "xl/sharedStrings.xml", teller), "si"):
                gedeeld.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(_onderdeel(z, "xl/_rels/workbook.xml.rels", teller)).findall("pr:Relationship", NS)}
        bladen = {}
        for s in ET.fromstring(_onderdeel(z, "xl/workbook.xml", teller)).find("m:sheets", NS).findall("m:sheet", NS):
            doel = rels.get(s.get(f"{{{NS['r']}}}id"), "")
            pad = doel.lstrip("/") if doel.startswith("/") else "xl/" + doel
            if pad not in namen:
                continue
            rijen = []
            for row in _elementen(_onderdeel(z, pad, teller), "row"):
                if len(rijen) >= MAX_RIJEN:
                    raise Fout(_("Excel-blad met meer dan {n} rijen", n=MAX_RIJEN))
                rij = {}
                for c in row.findall("m:c", NS):
                    t, v = c.get("t"), c.find("m:v", NS)
                    if t == "s" and v is not None:
                        w = gedeeld[int(v.text)] if v.text and int(v.text) < len(gedeeld) else ""
                    elif t == "inlineStr":
                        w = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                    else:
                        w = v.text if v is not None and v.text is not None else ""
                        if t != "str" and re.fullmatch(r"-?\d+\.0", w):
                            w = w[:-2]
                    k = _kolom(c.get("r")) if c.get("r") else len(rij)
                    if k < MAX_KOLOMMEN:                  # kolommen daarna staan nooit in een inventaris
                        rij[k] = w
                cellen += (max(rij) + 1) if rij else 0
                if cellen > MAX_CELLEN:
                    raise Fout(_("Excel-bestand met te veel cellen"))
                rijen.append([rij.get(i, "") for i in range(max(rij) + 1)] if rij else [])
            bladen[s.get("name")] = rijen
        return bladen


def lees_csv(tekst):
    eerste = tekst.splitlines()[0] if tekst.strip() else ""
    scheiding = ";" if eerste.count(";") > eerste.count(",") else ","
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(tekst), delimiter=scheiding)]


STREEP = re.compile(r"^\s*-{2,}(\s+-{2,})+\s*$")


def lees_cli(tekst):
    """Tabellen uit CLI-uitvoer van AOS-8: een kopregel, daaronder streepjes per kolom, dan de rijen."""
    regels = tekst.replace("\r", "").split("\n")
    tabellen = []
    for i, r in enumerate(regels):
        if i == 0 or not STREEP.match(r):
            continue
        starts = [m.start() for m in re.finditer(r"-+", r)]
        snij = lambda x: [x[a:b].strip() for a, b in zip(starts, starts[1:] + [None])]  # noqa: E731
        rijen = [snij(regels[i - 1])]
        for x in regels[i + 1:]:
            if not x.strip() or STREEP.match(x) or re.match(r"^\s*(Total|Flags|Num|\(|AP Database|All Switches)", x):
                break
            rijen.append(snij(x))
        tabellen.append(rijen)
    return tabellen


def _tabellen(bestand):
    """Alle tabellen (lijst van rijen) uit een bestand {naam, inhoud (base64)}."""
    naam = str(bestand.get("naam") or "")
    try:
        data = base64.b64decode(bestand.get("inhoud") or "", validate=False)
    except (ValueError, TypeError):
        raise Fout(_("{naam}: kon het bestand niet lezen", naam=naam))
    if data[:2] == b"PK" or naam.lower().endswith(".xlsx"):
        return list(lees_xlsx(data).values())
    tekst = data.decode("utf-8-sig", errors="replace")
    cli = lees_cli(tekst)
    if cli:
        return cli
    return [lees_csv(tekst)]


def _sleutel(k):
    return re.sub(r"[^a-z0-9#]", "", str(k).lower())


AP_KOP = {"name": "naam", "group": "groep", "aptype": "model", "ipaddress": "ip", "status": "status", "flags": "flags",
          "switchip": "switch_ip", "standbyip": "standby_ip", "wiredmacaddress": "mac", "serial#": "serial",
          "controllername": "controller"}
CTRL_KOP = {"ipaddress": "ip", "name": "naam", "type": "type", "model": "model", "version": "versie", "status": "status",
            "configurationstate": "config", "linkedapcount": "aps"}


def _herken(rijen):
    """('ap' | 'controller' | None, rijen als dicts). De kopregel mag in de eerste tien rijen staan."""
    for i, kop in enumerate(rijen[:10]):
        k = [_sleutel(x) for x in kop]
        if "serial#" in k and "aptype" in k:
            soort, kaart = "ap", AP_KOP
        elif {"name", "model", "type", "version"} <= set(k):
            soort, kaart = "controller", CTRL_KOP
        else:
            continue
        uit = []
        for r in rijen[i + 1:]:
            if not any(str(x).strip() for x in r):
                continue
            d = {kaart[k[j]]: str(r[j]).strip() for j in range(min(len(k), len(r))) if k[j] in kaart}
            if d.get("naam") or d.get("serial"):
                uit.append(d)
        return soort, uit
    return None, []


def lees_bestanden(bestanden):
    """(aps, controllers, meldingen) uit de opgeladen bestanden."""
    if not isinstance(bestanden, list) or not bestanden:
        raise Fout(_("kies minstens een bestand"))
    if len(bestanden) > MAX_BESTANDEN:
        raise Fout(_("hoogstens {n} bestanden tegelijk", n=MAX_BESTANDEN))
    aps, ctrls, meldingen = {}, {}, []
    for b in bestanden:
        if not isinstance(b, dict):
            continue
        gevonden = False
        for t in _tabellen(b):
            soort, rijen = _herken(t)
            if soort == "ap":
                for r in rijen:
                    aps[r.get("serial") or r.get("mac") or r.get("naam")] = r
            elif soort == "controller":
                for r in rijen:
                    ctrls[r.get("naam") or r.get("ip")] = r
            gevonden = gevonden or bool(soort)
        if not gevonden:
            meldingen.append(_("{naam}: geen AP- of controllerlijst herkend", naam=b.get("naam")))
    if not aps:
        raise Fout(_("geen AP-lijst gevonden. Verwacht de kolommen van 'show ap database long' (Name, Group, AP Type, Serial #, ...)"))
    if not ctrls:
        meldingen.append(_("geen controllerlijst gevonden ('show switches'): controllers enkel uit de AP-lijst"))
    return list(aps.values()), list(ctrls.values()), meldingen


# ---------------------------------------------------------------- beoordelen

STATUS_LABEL = {"ok": "klaar", "einde": "einde nadert", "nee": "vervangen", "weg": "valt weg", "onbekend": "na te kijken"}


def modellen():
    with open(resource("aos10-modellen.json"), encoding="utf-8") as f:
        return json.load(f)


def ap_model(x):
    x = str(x or "").strip().upper().replace(" ", "")
    if not x:
        return ""
    x = re.sub(r"^(AP|IAP|RAP)-?", "", x)
    return "AP-" + x


def ctrl_model(x):
    x = str(x or "").strip()
    return re.sub(r"^(Aruba|A)(?=\d|MM)", "", x, flags=re.I).upper()


def beoordeel(model, regels):
    for r in regels:
        if re.search(r["patroon"], model, re.I):
            return r["status"], _(r.get("opmerking", "")) if r.get("opmerking") else ""
    return "onbekend", _("niet in de lijst met AOS-10-modellen: nakijken")


def _is_up(s):
    return str(s or "").lower().startswith("up")


def _ip(x):
    x = str(x or "").strip()
    return "" if x in ("", "0.0.0.0", "N/A", "None") else x


def _model_tekst(teller):
    return ", ".join(f"{m.replace('AP-', '')}×{n}" for m, n in sorted(teller.items(), key=lambda x: (-x[1], x[0])))


def gereedheid(aps, ctrls):
    tabel = modellen()
    ip_naam = {_ip(c.get("ip")): c.get("naam") for c in ctrls if _ip(c.get("ip"))}
    ctrl = {c["naam"]: dict(c) for c in ctrls if c.get("naam")}

    # APs
    ap_rijen = []
    for a in aps:
        m = ap_model(a.get("model"))
        st, opm = beoordeel(m, tabel["ap"])
        c = a.get("controller") or ip_naam.get(_ip(a.get("switch_ip"))) or _ip(a.get("switch_ip")) or _("(onbekend)")
        sb = ip_naam.get(_ip(a.get("standby_ip"))) or _ip(a.get("standby_ip"))
        ap_rijen.append({"naam": a.get("naam", ""), "groep": a.get("groep", ""), "model": m, "serial": a.get("serial", ""),
                         "mac": a.get("mac", ""), "ip": a.get("ip", ""), "up": _is_up(a.get("status")),
                         "status": "up" if _is_up(a.get("status")) else (a.get("status") or "onbekend").split()[0].lower(),
                         "controller": c, "standby": sb or "", "aos10": st, "aos10_label": STATUS_LABEL[st], "opmerking": opm})
        ctrl.setdefault(c, {"naam": c, "ip": _ip(a.get("switch_ip")), "model": "", "type": "", "versie": "", "status": ""})
        if sb:
            ctrl.setdefault(sb, {"naam": sb, "ip": _ip(a.get("standby_ip")), "model": "", "type": "", "versie": "", "status": ""})

    # controllers en clusters: controllers die elkaars standby zijn, horen samen
    ouder = {n: n for n in ctrl}

    def wortel(n):
        while ouder[n] != n:
            ouder[n] = ouder[ouder[n]]
            n = ouder[n]
        return n
    for a in ap_rijen:
        if a["standby"] and a["standby"] in ouder:
            ouder[wortel(a["standby"])] = wortel(a["controller"])
    per_ctrl = defaultdict(list)
    for a in ap_rijen:
        per_ctrl[a["controller"]].append(a)
    ctrl_rijen = []
    for n, c in ctrl.items():
        m = ctrl_model(c.get("model"))
        typ = str(c.get("type") or "").lower()
        st, opm = beoordeel(m, tabel["controller"]) if m else ("onbekend", _("model onbekend (geen controllerlijst)"))
        if typ in ("conductor", "standby", "master") and st == "onbekend":
            st, opm = "weg", _("mobility conductor: valt weg")
        eigen = per_ctrl.get(n, [])
        ctrl_rijen.append({"naam": n, "ip": c.get("ip", ""), "model": m, "type": c.get("type", ""), "versie": c.get("versie", ""),
                           "status": (c.get("status") or "").lower(), "aps": len(eigen), "aps_up": sum(1 for a in eigen if a["up"]),
                           "aos10": st, "aos10_label": STATUS_LABEL[st], "opmerking": opm,
                           "cluster": wortel(n) if st != "weg" else ""})
    leden = defaultdict(list)
    for c in ctrl_rijen:
        if c["cluster"]:
            leden[c["cluster"]].append(c)
    clusters = []
    for w, cs in leden.items():
        namen = sorted(c["naam"] for c in cs)
        lijst = [a for c in cs for a in per_ctrl.get(c["naam"], [])]
        if not lijst and all(c["aps"] == 0 for c in cs) and len(cs) == 1 and cs[0]["status"] == "":
            continue
        t = Counter(a["aos10"] for a in lijst)
        actief = [c for c in cs if c["aps"]]
        n_ctrl = len(cs)
        if not lijst:
            aanpak = _("geen APs")
        elif n_ctrl >= 2:
            aanpak = _("in stappen: een controller omzetten, APs verhuizen, dan de volgende")
        else:
            aanpak = _("een controller: onderhoudsvenster of tijdelijke gateway")
        blok = []
        if t["nee"]:
            blok.append(_("eerst {n} APs vervangen", n=t["nee"]))
        if any(c["aos10"] in ("nee", "onbekend") for c in cs):
            blok.append(_("controllermodel nakijken"))
        clusters.append({"naam": " + ".join(namen), "controllers": n_ctrl, "actief": len(actief),
                         "modellen_ctrl": ", ".join(sorted({c["model"] or "?" for c in cs})),
                         "aps": len(lijst), "ok": t["ok"], "einde": t["einde"], "nee": t["nee"], "onbekend": t["onbekend"],
                         "ap_modellen": _model_tekst(Counter(a["model"] for a in lijst)),
                         "groepen": len({a["groep"] for a in lijst}), "redundant": n_ctrl >= 2, "aanpak": aanpak,
                         "klaar": bool(lijst) and not blok, "blokkade": "; ".join(blok)})
    clusters.sort(key=lambda c: (not c["klaar"], -c["aps"]))

    # AP-groepen
    pg = defaultdict(list)
    for a in ap_rijen:
        pg[a["groep"] or _("(leeg)")].append(a)
    groepen = [{"groep": g, "aps": len(l), "controllers": ", ".join(sorted({a["controller"] for a in l})),
                "modellen": _model_tekst(Counter(a["model"] for a in l)), "vervangen": sum(1 for a in l if a["aos10"] == "nee"),
                "einde": sum(1 for a in l if a["aos10"] == "einde"), "down": sum(1 for a in l if not a["up"])}
               for g, l in pg.items()]
    groepen.sort(key=lambda g: (-g["aps"], g["groep"]))

    # modellen
    mt = defaultdict(list)
    for a in ap_rijen:
        mt[a["model"]].append(a)
    model_rijen = [{"soort": "AP", "model": m, "aantal": len(l), "up": sum(1 for a in l if a["up"]), "aos10": l[0]["aos10"],
                    "aos10_label": l[0]["aos10_label"], "opmerking": l[0]["opmerking"]} for m, l in mt.items()]
    cm = defaultdict(list)
    for c in ctrl_rijen:
        cm[c["model"] or "?"].append(c)
    model_rijen += [{"soort": "Controller", "model": m, "aantal": len(l), "up": sum(1 for c in l if c["status"] == "up"),
                     "aos10": l[0]["aos10"], "aos10_label": l[0]["aos10_label"], "opmerking": l[0]["opmerking"]} for m, l in cm.items()]
    model_rijen.sort(key=lambda r: (r["soort"], -r["aantal"]))

    # opkuis
    opkuis = []
    mac = re.compile(r"^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$", re.I)
    for a in ap_rijen:
        if a["groep"].lower() == "default":
            opkuis.append({"soort": _("AP in groep default"), "naam": a["naam"], "detail": f"{a['model']}, {a['controller']}"})
        if mac.match(a["naam"]):
            opkuis.append({"soort": _("AP zonder naam (MAC)"), "naam": a["naam"], "detail": f"{a['groep']}, {a['controller']}"})
        if not a["up"]:
            opkuis.append({"soort": _("AP down"), "naam": a["naam"], "detail": f"{a['groep']}, {a['model']}, {a['controller']}"})
    for naam, n in Counter(a["naam"] for a in ap_rijen if a["naam"]).items():
        if n > 1:
            opkuis.append({"soort": _("dubbele AP-naam"), "naam": naam, "detail": f"{n} APs"})
    for c in ctrl_rijen:
        if c["status"] and c["status"] != "up":
            opkuis.append({"soort": _("controller down"), "naam": c["naam"], "detail": f"{c['model']} {c['ip']}"})
        if c["aps"] == 0 and c["aos10"] != "weg":
            opkuis.append({"soort": _("controller zonder APs"), "naam": c["naam"], "detail": _("stand-by, of niet in gebruik?")})

    t = Counter(a["aos10"] for a in ap_rijen)
    samen = {"aps": len(ap_rijen), "aps_up": sum(1 for a in ap_rijen if a["up"]), "ok": t["ok"], "einde": t["einde"],
             "nee": t["nee"], "onbekend": t["onbekend"],
             "controllers": sum(1 for c in ctrl_rijen if c["aos10"] != "weg"),
             "conductors": sum(1 for c in ctrl_rijen if c["aos10"] == "weg"),
             "ctrl_nakijken": sum(1 for c in ctrl_rijen if c["aos10"] in ("nee", "onbekend")),
             "clusters": len(clusters), "redundant": sum(1 for c in clusters if c["redundant"] and c["aps"]),
             "enkel": sum(1 for c in clusters if not c["redundant"] and c["aps"]), "groepen": len(groepen),
             "versies": dict(Counter(c["versie"] for c in ctrl_rijen if c["versie"]))}
    return {"samenvatting": samen, "modellen": model_rijen, "clusters": clusters, "groepen": groepen,
            "controllers": sorted(ctrl_rijen, key=lambda c: (c["aos10"] != "weg", c["naam"])), "opkuis": opkuis,
            "aps": ap_rijen, "bron": {"bijgewerkt": tabel.get("bijgewerkt", ""), "tekst": tabel.get("bron", "")}}


def analyseer(bestanden, klant="", tijd=None):
    """tijd: de lokale tijd van de browser (ISO), anders die van de server."""
    aps, ctrls, meldingen = lees_bestanden(bestanden)
    res = gereedheid(aps, ctrls)
    res["meldingen"] = meldingen
    res["klant"] = str(klant or "").strip()[:80]
    res["tijd"] = tijd or datetime.datetime.now().isoformat(timespec="seconds")
    res["taal"] = huidig()                 # de zinnen (aanpak, opmerkingen) staan in deze taal
    res["rapport"] = rapport_html(res)
    return res


# ---------------------------------------------------------------- rapport voor de klant

def rapport_html(r):
    e = lambda x: html.escape(str(x if x is not None else ""))  # noqa: E731
    s = r["samenvatting"]
    pill = {"ok": "#1f7a4a", "einde": "#a35d06", "nee": "#c4312b", "weg": "#5f6c7f", "onbekend": "#2457d6"}

    def tabel(kop, rijen):
        return ("<table><thead><tr>" + "".join(f"<th>{e(k)}</th>" for k in kop) + "</tr></thead><tbody>"
                + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in rij) + "</tr>" for rij in rijen) + "</tbody></table>")

    def st(x, label):
        return f'<span class="p" style="color:{pill.get(x, "#5f6c7f")};border-color:{pill.get(x, "#5f6c7f")}">{e(_(label))}</span>'

    def kop(*namen):
        return [_(n) for n in namen]
    titel = _("AOS-10 gereedheid") + (f" · {r.get('klant')}" if r.get("klant") else "")
    tegels = [("APs", s["aps"]), ("APs up", s["aps_up"]), (_("Klaar voor AOS-10"), s["ok"]), (_("Einde support nadert"), s["einde"]),
              (_("Te vervangen"), s["nee"]), (_("Na te kijken"), s["onbekend"]), (_("Controllers → gateway"), s["controllers"]),
              (_("Clusters met redundantie"), s["redundant"]), (_("Sites met een controller"), s["enkel"])]
    delen = [f"<h1>{e(titel)}</h1><p class='m'>"
             + e(_("Gemaakt op {tijd} uit de AOS-8-inventaris. {groepen} AP-groepen, {conductors} mobility conductors.",
                   tijd=r.get("tijd", "")[:16].replace("T", " "), groepen=s["groepen"], conductors=s["conductors"])) + "</p>",
             "<div class='t'>" + "".join(f"<div><b>{e(v)}</b><span>{e(k)}</span></div>" for k, v in tegels) + "</div>",
             f"<h2>{e(_('Modellen'))}</h2>", tabel(kop("Soort", "Model", "Aantal", "AOS-10", "Opmerking"),
                                        [[e(m["soort"]), e(m["model"]), e(m["aantal"]), st(m["aos10"], m["aos10_label"]), e(m["opmerking"])] for m in r["modellen"]]),
             f"<h2>{e(_('Clusters en aanpak'))}</h2><p class='m'>"
             + e(_("Controllers die elkaars stand-by zijn, vormen een cluster. Met twee of meer kan je in stappen migreren zonder dat de getunnelde SSID's wegvallen.")) + "</p>",
             tabel(kop("Controllers", "Model", "APs", "Klaar", "Einde", "Vervangen", "AP-modellen", "Aanpak", "Blokkade"),
                   [[e(c["naam"]), e(c["modellen_ctrl"]), e(c["aps"]), e(c["ok"]), e(c["einde"]), e(c["nee"]), e(c["ap_modellen"]),
                     e(c["aanpak"]), e(c["blokkade"]) or "–"] for c in r["clusters"]]),
             "<h2>Controllers</h2>", tabel(kop("Naam", "Model", "Rol", "Versie", "Status", "APs", "AOS-10"),
                                           [[e(c["naam"]), e(c["model"]), e(c["type"]), e(c["versie"]), e(c["status"]), e(c["aps"]),
                                             st(c["aos10"], c["aos10_label"])] for c in r["controllers"]])]
    if r["opkuis"]:
        per = Counter(o["soort"] for o in r["opkuis"])
        delen += [f"<h2>{e(_('Op te kuisen voor de migratie'))}</h2>", tabel(kop("Wat", "Aantal"), [[e(k), e(v)] for k, v in per.most_common()]),
                  tabel(kop("Wat", "Naam", "Detail"), [[e(o["soort"]), e(o["naam"]), e(o["detail"])] for o in r["opkuis"][:500]])]
    delen.append(f"<h2>{e(_('AP-groepen'))}</h2>" + tabel(kop("AP-groep", "APs", "Controllers", "Modellen", "Vervangen", "Einde", "Down"),
                                                 [[e(g["groep"]), e(g["aps"]), e(g["controllers"]), e(g["modellen"]), e(g["vervangen"]),
                                                   e(g["einde"]), e(g["down"])] for g in r["groepen"]]))
    delen.append("<p class='m'>" + e(_("Supportstatus per model: {tekst} (lijst van {datum}).",
                                       tekst=_(r["bron"]["tekst"]) if r["bron"]["tekst"] else "", datum=r["bron"]["bijgewerkt"])) + "</p>")
    css = ("body{font:13px/1.5 'Segoe UI',system-ui,sans-serif;color:#122033;margin:32px auto;max-width:1180px;padding:0 16px}"
           "h1{font-size:22px;margin:0}h2{font-size:16px;margin:28px 0 8px}.m{color:#5f6c7f}"
           "table{border-collapse:collapse;width:100%;margin:6px 0 14px}th,td{border-bottom:1px solid #e2e7ee;padding:5px 8px;text-align:left;vertical-align:top}"
           "th{font-size:11px;text-transform:uppercase;color:#5f6c7f;background:#f8fafc}"
           ".t{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:16px 0}"
           ".t div{border:1px solid #e2e7ee;border-radius:10px;padding:10px 12px}.t b{display:block;font-size:22px}.t span{color:#5f6c7f;font-size:12px}"
           ".p{border:1px solid;border-radius:999px;padding:0 8px;font-size:11.5px;font-weight:600;white-space:nowrap}"
           "@media print{body{margin:0}h2{break-after:avoid}tr{break-inside:avoid}}")
    return (f"<!DOCTYPE html><html lang='{huidig()}'><head><meta charset='utf-8'><title>{e(titel)}</title><style>{css}</style></head>"
            f"<body>{''.join(delen)}</body></html>")

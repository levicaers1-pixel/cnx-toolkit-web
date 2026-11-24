#!/usr/bin/env python3
"""Toestel-aliassen voor access switches in new Central (CNX): van een tabel per switch naar het bulkformaat van de UI.

Enkel AOS-CX access switches, en enkel waarden die per switch verschillen (device-scope):
hostname, system VLAN IP en beheer-IP (OOBM). Standaard access; de kolom device_function (Access, Aggregation of
Core Switch) bepaalt de Device Function in de upload.
Geheimen en alles wat voor een site of de hele tenant geldt, horen in gewone profielen op Global,
Site of Device Group, niet hier.

  cnx alias uit-classic-lijst --lijst export_switch_list.csv [--prefix 24] [--site-collection Belgium] --out toestellen.csv
  cnx alias uit-classic --export 02-export [--groepen groepen.csv] --out toestellen.csv
  cnx alias controleer  --toestellen toestellen.csv [--namen namen.csv]
  cnx alias genereer    --toestellen toestellen.csv --out 05-aliassen
  cnx alias vergelijk   --toestellen toestellen.csv --download bulk_alias_download.csv
  cnx alias globaliseer --download bulk_alias_download.csv --out 06-globaal

Gemeenschappelijke opties: --config <bestand> (standaard klantconfig.json in de werkmap, anders de meegeleverde).

Invoer:
  toestellen.csv   een rij per access switch (een VSF-stack is een rij: het serienummer van de conductor)
  namen.csv        optioneel, kolommen soort,naam (soort: site_collection, site, device_group).
                   Haal de namen uit new Central; zo valt een tikfout in een sitenaam op voor de upload.

Uitvoer van genereer:
  05-aliassen/<golf>__access-switch[__deelN].csv   klaar voor Configuration > Library > Named Objects >
                                                   Aliases > bulk upload
  05-aliassen/rapport.md                            wat er in elk bestand zit
Dezelfde uitvoer als de pagina cnx-alias-invoer.html. Enkel standaardbibliotheek, geen API-calls.
"""
import argparse, csv, io, ipaddress, json, os, re, sys
from collections import OrderedDict, defaultdict

from . import __version__, resource


def standaard_config():
    """Klantconfig in de werkmap gaat voor op de meegeleverde standaard."""
    for naam in ("klantconfig.json", "alias-config.json"):
        if os.path.exists(naam):
            return naam
    return resource("alias-config.json")

FUNCTIE = "Access Switch"
# Device function per switch: code in Central -> label in de bulk-upload. Leeg = Access Switch.
FUNCTIE_LABELS = {"ACCESS_SWITCH": "Access Switch", "AGG_SWITCH": "Aggregation Switch", "CORE_SWITCH": "Core Switch",
                  "MOBILITY_GW": "Mobility Gateway"}
_FUNCTIE_ALIAS = {"ACCESS_SWITCH": "ACCESS_SWITCH", "ACCESS": "ACCESS_SWITCH", "AGG_SWITCH": "AGG_SWITCH",
                  "AGGREGATION_SWITCH": "AGG_SWITCH", "AGGREGATION": "AGG_SWITCH", "AGG": "AGG_SWITCH",
                  "CORE_SWITCH": "CORE_SWITCH", "CORE": "CORE_SWITCH",
                  "MOBILITY_GW": "MOBILITY_GW", "MOBILITY_GATEWAY": "MOBILITY_GW", "MOBILITY": "MOBILITY_GW"}


def functie_code(waarde):
    """'Core Switch', 'CORE_SWITCH', 'core' -> CORE_SWITCH. Leeg -> ACCESS_SWITCH. Onbekend -> None."""
    x = re.sub(r"[\s_-]+", "_", str(waarde or "").strip().upper())
    return "ACCESS_SWITCH" if not x else _FUNCTIE_ALIAS.get(x)


def functie_label(t):
    return FUNCTIE_LABELS.get(functie_code(t.get("device_function")) or "ACCESS_SWITCH")
BASIS = ["Device Function", "Scope Level", "Site Collection Name", "Site Name", "Device Group Name", "Device", "Modified"]
KOP_EIGEN = ["Alias Name", "Alias Type"]
KOP_VOORGEDEF = ["Pre-defined Alias Name", "Instance Name"]
TOESTEL_KOLOMMEN = ["serial", "hostname", "stack", "site_collection", "site", "device_group", "device_function", "golf",
                    "sys_vlan_ip", "beheer_vlan", "mgmt_ip", "systeemprofiel", "opmerking"]


def is_stack(t):
    return (t.get("stack") or "").strip().lower() in ("ja", "yes", "j", "y", "1", "true")
SECTIE_VOLGORDE = ["#ALIAS_IPV4_ADDRESS_TYPE", "#Interface-management", "#System-info"]


# ---------------------------------------------------------------- invoer

def lees_csv(pad):
    with open(pad, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        except csv.Error:
            dialect = csv.excel
        rijen = []
        for i, r in enumerate(csv.DictReader(f, dialect=dialect), start=2):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            if any(r.values()):
                r["_regel"] = i
                rijen.append(r)
        return rijen


def lees_config(pad):
    with open(pad, encoding="utf-8") as f:
        return json.load(f)


def lees_namen(pad):
    if not pad:
        return None
    namen = defaultdict(set)
    for r in lees_csv(pad):
        namen[r.get("soort", "").lower()].add(r.get("naam", ""))
    return namen


# ---------------------------------------------------------------- controle

class Bevindingen:
    def __init__(self):
        self.lijst = []

    def fout(self, regel, serial, veld, tekst):
        self.lijst.append(("FOUT", regel, serial, veld, tekst))

    def let_op(self, regel, serial, veld, tekst):
        self.lijst.append(("LET OP", regel, serial, veld, tekst))

    @property
    def fouten(self):
        return [b for b in self.lijst if b[0] == "FOUT"]

    def schrijf(self, pad):
        with open(pad, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ernst", "regel", "serial", "veld", "bevinding"])
            w.writerows(self.lijst)


STANDAARD_PREFIX = 24


def prefix_van(cfg):
    """Prefix voor een IP zonder prefix: standaard_prefix uit de klantconfig, anders /24."""
    try:
        p = int(str((cfg or {}).get("standaard_prefix", STANDAARD_PREFIX)).lstrip("/"))
        return p if 0 < p <= 32 else STANDAARD_PREFIX
    except ValueError:
        return STANDAARD_PREFIX


def met_prefix(v, cfg=None):
    """Een IP zonder prefix krijgt de standaardprefix (/24). DHCP en lege waarden blijven zoals ze zijn."""
    v = (v or "").strip()
    if not v or v.upper() == "DHCP" or "/" in v:
        return v
    return f"{v}/{prefix_van(cfg)}"


def ip_met_prefix(v):
    if "/" not in v:
        return None
    try:
        return ipaddress.IPv4Interface(v)
    except ValueError:
        return None


STANDAARD_REGEX = r"^[A-Za-z][A-Za-z0-9._-]{0,31}$"


def controleer_config(cfg):
    """Problemen in een klantconfig: [(veld, tekst, soort)]. soort 'ontbreekt' = nog in te vullen,
    'fout' = ongeldige waarde. Gebruikt door controleer en door het tabblad Klantconfig van cnx web."""
    uit = []
    v = cfg.get("velden") if isinstance(cfg.get("velden"), dict) else {}

    def tekst(pad):
        x = v
        for k in pad:
            x = x.get(k) if isinstance(x, dict) else None
        return x

    for pad, label in ((("hostname", "instance"), "System-info-profiel (velden.hostname.instance)"),
                       (("mgmt_ip", "instance"), "Beheerinterface (velden.mgmt_ip.instance)")):
        x = tekst(pad)
        if not isinstance(x, str) or not x.strip() or "VUL-IN" in x:
            uit.append((label, "nog niet ingevuld", "ontbreekt"))
    vlan = tekst(("sys_vlan_ip", "standaard_vlan"))
    if isinstance(vlan, bool) or not (isinstance(vlan, int) or (isinstance(vlan, str) and vlan.isdigit())) or not 1 <= int(vlan) <= 4094:
        uit.append(("Beheer-VLAN (velden.sys_vlan_ip.standaard_vlan)", f"'{vlan}': VLAN-ID tussen 1 en 4094 verwacht", "fout"))
    patroon = tekst(("sys_vlan_ip", "alias_patroon"))
    if patroon is not None and (not isinstance(patroon, str) or "{vlan}" not in patroon):
        uit.append(("Aliaspatroon (velden.sys_vlan_ip.alias_patroon)", f"'{patroon}': moet {{vlan}} bevatten", "fout"))
    try:
        re.compile(cfg.get("hostname_regex") or STANDAARD_REGEX)
    except (re.error, TypeError) as e:
        uit.append(("Hostname-regel (hostname_regex)", f"geen geldige regex: {e}", "fout"))
    if cfg.get("modified", "Yes") != "Yes":
        uit.append(("Modified", f"'{cfg.get('modified')}': moet Yes zijn, Central past enkel rijen met Yes toe", "fout"))
    if "VUL-IN" in json.dumps(v) and not any(s == "ontbreekt" for _, _, s in uit):
        uit.append(("velden", "bevat nog VUL-IN", "ontbreekt"))
    return uit


def voorstel_uit_bulk(pad):
    """Klantconfig-waarden zoals ze in een bulk-download uit new Central staan: de meest gebruikte per veld."""
    from collections import Counter
    profiel, vlan, mgmt = Counter(), Counter(), Counter()
    for (serial, sectie, naam, inst, veld), w in lees_bulk(pad).items():
        if not w:
            continue
        if sectie == "#System-info" and naam == "hostname":
            profiel[inst] += 1
        elif sectie == "#ALIAS_IPV4_ADDRESS_TYPE" and re.fullmatch(r"sys_vlan_ipv4_\d+", naam):
            vlan[int(naam.rsplit("_", 1)[1])] += 1
        elif sectie == "#Interface-management" and naam == "IPv4-address":
            mgmt[inst] += 1
    def top(c):
        return {"waarde": c.most_common(1)[0][0], "switches": c.most_common(1)[0][1], "andere": len(c) - 1} if c else None
    return {"hostname_instance": top(profiel), "standaard_vlan": top(vlan), "mgmt_instance": top(mgmt)}


def controleer(toestellen, cfg, namen):
    b = Bevindingen()
    for veld, tekst, _ in controleer_config(cfg):
        if veld.startswith(("System-info-profiel", "Beheerinterface")) or (veld == "velden" and "VUL-IN" in tekst):
            continue            # enkel nodig voor switches met een hostname of beheer-IP: per switch hieronder
        b.fout("", "", "klantconfig", f"{veld}: {tekst}")
    try:
        regex = re.compile(cfg.get("hostname_regex") or STANDAARD_REGEX)
    except (re.error, TypeError):
        regex = re.compile(STANDAARD_REGEX)
    gezien = defaultdict(list)
    serials = defaultdict(list)

    for t in toestellen:
        s, r = t.get("serial", ""), t["_regel"]
        fc = functie_code(t.get("device_function"))
        if fc is None:
            b.fout(r, s, "device_function", f"'{t['device_function']}': onbekend. Gebruik Access Switch, Aggregation Switch, Core Switch of Mobility Gateway")
        elif fc != "ACCESS_SWITCH":
            b.let_op(r, s, "device_function", f"{FUNCTIE_LABELS[fc]}: de rijen in het aliasbestand krijgen Device Function {FUNCTIE_LABELS[fc]}")
        if is_stack(t):
            b.let_op(r, s, "stack", "VSF-stack: de bulk-upload ondersteunt geen stacks. Komt in manueel-stacks.csv")
        if not s and is_stack(t):
            pass
        elif not s:
            b.fout(r, "", "serial", "leeg")
        else:
            if not re.match(r"^[A-Z0-9]{8,14}$", s):
                b.let_op(r, s, "serial", "ongewoon formaat, nakijken")
            serials[s].append(r)

        for veld in ("site", "device_group"):
            if not t.get(veld):
                b.fout(r, s, veld, "leeg: nodig om het toestel in de upload te plaatsen")
        if namen:
            for veld in ("site_collection", "site", "device_group"):
                v = t.get(veld)
                if v and namen.get(veld) and v not in namen[veld]:
                    b.fout(r, s, veld, f"'{v}' bestaat niet in new Central (namen.csv)")

        # De hostname staat de upload nooit in de weg: zonder geldige hostname gaat enkel het IP mee.
        h = t.get("hostname", "")
        if not h:
            b.let_op(r, s, "hostname", "leeg: geen hostname in het aliasbestand, enkel het IP")
        elif not regex.match(h):
            b.let_op(r, s, "hostname", f"'{h}' voldoet niet aan {regex.pattern}: niet in het aliasbestand, enkel het IP")
        elif not hostname_profiel(t, cfg):
            b.let_op(r, s, "hostname", "geen System-info-profiel in de klantconfig: hostname niet in het aliasbestand, enkel het IP")
        else:
            gezien[("hostname", h.lower())].append(s)
        if t.get("mgmt_ip") and not _instantie(cfg, "mgmt_ip"):
            b.fout(r, s, "mgmt_ip", "geen beheerinterface in de klantconfig (velden.mgmt_ip.instance): vul die in stap 1 in, of laat mgmt_ip leeg")

        for veld, dhcp in (("sys_vlan_ip", True), ("mgmt_ip", False)):
            v = t.get(veld, "")
            if not v or (dhcp and v.upper() == "DHCP"):
                continue
            if "/" not in v:
                b.let_op(r, s, veld, f"'{v}' zonder prefix: /{prefix_van(cfg)} aangenomen")
                v = met_prefix(v, cfg)
            x = ip_met_prefix(v)
            if not x:
                b.fout(r, s, veld, f"'{v}': geen geldig IP-adres (10.1.1.10/24)" + (" of DHCP" if dhcp else ""))
                continue
            if x.network.prefixlen < 31 and x.ip in (x.network.network_address, x.network.broadcast_address):
                b.fout(r, s, veld, f"'{v}' is het netwerk- of broadcastadres")
            gezien[("ip", str(x.ip))].append(s)
        bv = t.get("beheer_vlan", "")
        if bv and (not bv.isdigit() or not 1 <= int(bv) <= 4094):
            b.fout(r, s, "beheer_vlan", f"'{bv}': VLAN-ID tussen 1 en 4094 verwacht")
        if not t.get("sys_vlan_ip") and not t.get("mgmt_ip"):
            b.let_op(r, s, "", "geen system VLAN IP en geen beheer-IP: enkel de hostname wordt gezet" if hostname_mee(t, cfg)
                     else "geen IP en geen hostname: deze switch komt niet in het aliasbestand")

    for s, regels in serials.items():
        if len(regels) > 1:
            b.fout(", ".join(map(str, regels)), s, "serial", f"staat {len(regels)} keer in de lijst")
    for (soort, waarde), lijst in gezien.items():
        if len(lijst) > 1:
            if soort == "hostname":
                b.let_op("", ", ".join(sorted(set(lijst))), soort, f"'{waarde}' komt {len(lijst)} keer voor")
            else:
                b.fout("", ", ".join(sorted(set(lijst))), soort, f"'{waarde}' komt {len(lijst)} keer voor")
    return b


# ---------------------------------------------------------------- opbouw

def sys_vlan_alias(t, cfg):
    """Naam van de system VLAN-alias. Central noemt die sys_vlan_ipv4_<vlan-id>."""
    v = cfg["velden"]["sys_vlan_ip"]
    vlan = t.get("beheer_vlan") or str(v.get("standaard_vlan", 1))
    return v.get("alias_patroon", "sys_vlan_ipv4_{vlan}").format(vlan=vlan)


def _instantie(cfg, veld):
    x = ((cfg.get("velden") or {}).get(veld) or {}).get("instance") if isinstance(cfg, dict) else None
    return x.strip() if isinstance(x, str) and x.strip() and "VUL-IN" not in x else ""


def hostname_profiel(t, cfg):
    """Het System-info-profiel voor de hostname van deze switch, of leeg als er geen is."""
    return (t.get("systeemprofiel") or "").strip() or _instantie(cfg, "hostname")


def hostname_mee(t, cfg):
    """Gaat de hostname mee in het aliasbestand? Enkel als ze geldig is en er een profiel is."""
    try:
        regex = re.compile(cfg.get("hostname_regex") or STANDAARD_REGEX)
    except (re.error, TypeError):
        regex = re.compile(STANDAARD_REGEX)
    h = t.get("hostname", "")
    return bool(h and regex.match(h) and hostname_profiel(t, cfg))


def rijen_voor_toestel(t, cfg, x_hierarchie=False):
    v = cfg["velden"]
    uit = []
    if hostname_mee(t, cfg):
        uit.append(("#System-info", ("hostname",), "hostname", hostname_profiel(t, cfg), (t["hostname"],)))
    if t.get("sys_vlan_ip"):
        w = "DHCP" if t["sys_vlan_ip"].upper() == "DHCP" else met_prefix(t["sys_vlan_ip"], cfg)
        uit.append(("#ALIAS_IPV4_ADDRESS_TYPE", ("ipv4-address",), sys_vlan_alias(t, cfg), "ALIAS_IPV4_ADDRESS_TYPE", (w,)))
    if t.get("mgmt_ip"):
        uit.append(("#Interface-management", ("ipv4-static",), "IPv4-address", v["mgmt_ip"]["instance"], (met_prefix(t["mgmt_ip"], cfg),)))
    plaats = ["x", "x", "x"] if x_hierarchie else [t.get("site_collection", ""), t.get("site", ""), t.get("device_group", "")]
    basis = [functie_label(t), "Device"] + plaats + [t["serial"], cfg.get("modified", "Yes")]
    return [(sec, kol, naam, inst, basis, w) for sec, kol, naam, inst, w in uit]


def schrijf_bulk(pad, rijen):
    with open(pad, "w", newline="", encoding="utf-8") as f:
        f.write(bulk_tekst(rijen))


def bulk_tekst(rijen):
    """Het bulkbestand voor de UI van Central als tekst (zonder het weg te schrijven)."""
    per_sectie = OrderedDict((s, OrderedDict()) for s in SECTIE_VOLGORDE)
    for sec, kol, naam, inst, basis, w in rijen:
        sleutel = ("" if sec.startswith("#ALIAS_") else naam, kol)
        per_sectie[sec].setdefault(sleutel, []).append((naam, inst, basis, w))
    f = io.StringIO(newline="")
    wr = csv.writer(f, lineterminator="\n")
    eerste = True
    for sec, tabellen in per_sectie.items():
        if not tabellen:
            continue
        if not eerste:
            wr.writerow([])
        eerste = False
        f.write(sec + "\n")
        for i, ((_, kol), items) in enumerate(tabellen.items()):
            if i:
                wr.writerow([])
            kop = KOP_EIGEN if sec.startswith("#ALIAS_") else KOP_VOORGEDEF
            wr.writerow(kop + BASIS + list(kol))
            for naam, inst, basis, w in items:
                wr.writerow([naam, inst] + basis + list(w))
    f.write("\n")
    return f.getvalue()


def veilig(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-").lower()


def bouw(args):
    cfg = lees_config(args.config)
    toestellen = lees_csv(args.toestellen)
    return cfg, toestellen, controleer(toestellen, cfg, lees_namen(getattr(args, "namen", None)))


def toon(b, max_regels=40):
    for ernst, regel, serial, veld, tekst in b.lijst[:max_regels]:
        print(f"  {ernst:6} regel {str(regel):8} {serial:14} {veld:16} {tekst}")
    if len(b.lijst) > max_regels:
        print(f"  ... en nog {len(b.lijst) - max_regels}. Alles staat in bevindingen.csv")


# ---------------------------------------------------------------- commando's

def cmd_controleer(args):
    cfg, toestellen, b = bouw(args)
    b.schrijf(args.bevindingen)
    print(f"{len(toestellen)} access switches: {len(b.fouten)} fouten, {len(b.lijst) - len(b.fouten)} aandachtspunten")
    toon(b)
    print(f"Volledige lijst: {args.bevindingen}")
    return 1 if b.fouten else 0


def cmd_genereer(args):
    cfg, toestellen, b = bouw(args)
    os.makedirs(args.out, exist_ok=True)
    b.schrijf(os.path.join(args.out, "bevindingen.csv"))
    if b.fouten:
        print(f"{len(b.fouten)} fouten, er wordt niets gegenereerd. Eerst oplossen:")
        toon(b)
        return 1
    golven = OrderedDict()
    stacks = [t for t in toestellen if is_stack(t)]
    if stacks:
        with open(os.path.join(args.out, "manueel-stacks.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=TOESTEL_KOLOMMEN, extrasaction="ignore")
            w.writeheader()
            w.writerows(stacks)
        print(f"  manueel-stacks.csv                            {len(stacks):5} stacks: niet via bulk-upload, manueel instellen")
    for t in toestellen:
        if is_stack(t):
            continue
        golven.setdefault(t.get("golf") or "golf1", []).append((t, rijen_voor_toestel(t, cfg, args.x_voor_hierarchie)))

    rapport = ["# Alias-upload access switches", "",
               "Upload elk bestand apart via Configuration > Library > Named Objects > Aliases (bulk upload). "
               "Na elke upload: bulk download en `cnx alias vergelijk`.", "",
               "| Bestand | Golf | Switches | Rijen |", "|---|---|---|---|"]
    n_bestanden = 0
    for golf, items in golven.items():
        delen, huidig, n = [], [], 0
        for t, rijen in items:                  # een switch nooit over twee bestanden verdelen
            if huidig and n + len(rijen) > args.max_rijen:
                delen.append(huidig)
                huidig, n = [], 0
            huidig.append((t, rijen))
            n += len(rijen)
        if huidig:
            delen.append(huidig)
        for i, deel in enumerate(delen, start=1):
            naam = f"{veilig(golf)}__access-switch" + (f"__deel{i}" if len(delen) > 1 else "") + ".csv"
            alle = [r for _, rijen in deel for r in rijen]
            schrijf_bulk(os.path.join(args.out, naam), alle)
            rapport.append(f"| {naam} | {golf} | {len(deel)} | {len(alle)} |")
            print(f"  {naam:45} {len(deel):5} switches {len(alle):6} rijen")
            n_bestanden += 1
    if stacks:
        rapport += ["", f"{len(stacks)} VSF-stacks zitten niet in de upload (niet ondersteund). Zie manueel-stacks.csv."]
    if b.lijst:
        rapport += ["", f"{len(b.lijst)} aandachtspunten, zie bevindingen.csv."]
    with open(os.path.join(args.out, "rapport.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rapport) + "\n")
    print(f"{n_bestanden} bestanden in {args.out}. {len(b.lijst)} aandachtspunten in bevindingen.csv")
    return 0


def lees_bulk(pad):
    """Leest een bulk-download van new Central. Geeft {(serial, sectie, naam, instance, veld): waarde}."""
    waarden = {}
    sectie, kop = None, None
    with open(pad, newline="", encoding="utf-8-sig") as f:
        for cellen in csv.reader(f):
            while cellen and cellen[-1] == "":
                cellen.pop()
            if not cellen:
                kop = None
                continue
            eerste = cellen[0].strip()
            if eerste.startswith("#"):
                sectie, kop = eerste, None
            elif eerste in ("Alias Name", "Pre-defined Alias Name"):
                kop = cellen
            elif kop and sectie and len(cellen) >= 9 and not eerste.startswith("//"):
                cellen += [""] * (len(kop) - len(cellen))
                rij = dict(zip(kop, cellen))
                if rij.get("Scope Level") != "Device":
                    continue
                for veld in kop[9:]:
                    waarden[(rij["Device"], sectie, cellen[0], cellen[1], veld)] = rij.get(veld, "")
    return waarden


def cmd_vergelijk(args):
    cfg, toestellen, b = bouw(args)
    if b.fouten:
        print("Let op: de invoer heeft fouten. De vergelijking loopt toch.")
    verwacht = {}
    for t in toestellen:
        if not t.get("serial") or is_stack(t):
            continue
        for sec, kol, naam, inst, basis, w in rijen_voor_toestel(t, cfg):
            for veld, v in zip(kol, w):
                verwacht[(t["serial"], sec, naam, inst, veld)] = v
    centraal = lees_bulk(args.download)
    in_download = {k[0] for k in centraal}
    resultaat = []
    for k, v in sorted(verwacht.items()):
        if k[0] not in in_download:
            status, gevonden = "TOESTEL NIET IN DOWNLOAD", ""
        elif k not in centraal:
            status, gevonden = "ONTBREEKT", ""
        else:
            gevonden = centraal[k]
            status = "identiek" if gevonden.strip().lower() == v.strip().lower() else "VERSCHILT"
        resultaat.append([k[0], k[1], k[2], k[3], k[4], v, gevonden, status])
    with open(args.uit, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["serial", "sectie", "alias", "instance", "veld", "verwacht", "in_central", "status"])
        w.writerows(resultaat)
    telling = defaultdict(int)
    for r in resultaat:
        telling[r[-1]] += 1
    for status, n in sorted(telling.items()):
        print(f"  {status:26} {n}")
    for r in [r for r in resultaat if r[-1] != "identiek"][:25]:
        print(f"  {r[-1]:26} {r[0]:14} {r[2]}/{r[3]}: verwacht '{r[5]}', in Central '{r[6]}'")
    print(f"Volledige vergelijking: {args.uit}")
    return 0 if telling.get("identiek", 0) == len(resultaat) else 1


def cmd_uit_classic(args):
    inv = lees_csv(os.path.join(args.export, "inventory.csv"))
    groepen = {g.get("groep", ""): g for g in lees_csv(args.groepen)} if args.groepen else {}
    stacks = defaultdict(int)
    for s in inv:
        if s.get("stack_id"):
            stacks[s["stack_id"]] += 1
    n, overgeslagen = 0, 0
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TOESTEL_KOLOMMEN)
        w.writeheader()
        for s in inv:
            g = groepen.get(s.get("group", ""), {})
            df = g.get("device_function", "").upper()
            if df and df not in ("ACCESS_SWITCH", "ACCESS SWITCH"):
                overgeslagen += 1
                continue
            opm = ["uit Classic"]
            if s.get("ip"):
                opm.append(f"Classic IP {s['ip']}: prefix aanvullen, of naar mgmt_ip als de switch via OOBM beheerd wordt")
            if stacks.get(s.get("stack_id", ""), 0) > 1:
                opm.append(f"VSF-stack {s['stack_id']}: enkel de rij van de conductor houden")
            w.writerow({"serial": s.get("serial", ""), "hostname": s.get("name", ""), "site_collection": "",
                        "site": s.get("site", ""), "device_group": g.get("cnx_groep") or s.get("group", ""),
                        "golf": "classic", "sys_vlan_ip": s.get("ip", ""), "beheer_vlan": "", "mgmt_ip": "",
                        "systeemprofiel": "sys-system-info-profile", "opmerking": ". ".join(opm)})
            n += 1
    print(f"{n} access switches naar {args.out}" + (f", {overgeslagen} andere switches overgeslagen (manueel)" if overgeslagen else "")
          + ". Vul site_collection aan, zet de prefix bij de IP's en draai daarna 'controleer'.")
    return 0


def cmd_uit_classic_lijst(args):
    """Switchlijst uit de UI van Classic Central (Devices > Switches > export) naar toestellen.csv."""
    with open(args.lijst, newline="", encoding="utf-8-sig") as f:
        rijen = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    if os.path.exists(args.out) and not args.overschrijf:
        sys.exit(f"{args.out} bestaat al. Kies een andere naam of gebruik --overschrijf.")
    n, stacks, zonder_prefix, overgeslagen = 0, 0, 0, []
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TOESTEL_KOLOMMEN)
        w.writeheader()
        for r in rijen:
            if not any(r.values()):
                continue
            typ, host, ser, ip = r.get("type", ""), r.get("device name", ""), r.get("serial", "").upper(), r.get("ip address", "")
            if not typ.upper().startswith("AOS-CX"):
                overgeslagen.append(host or ser)
                continue
            stack = "stack" in typ.lower() or not re.match(r"^[A-Z0-9]{8,14}$", ser)
            opm = [f"uit Classic: {r.get('model') or typ}, groep {r.get('group', '')}"]
            if stack:
                stacks += 1
                opm.append(f"VSF-stack (stack-ID {r.get('serial', '')}): vul het serienummer van de conductor in")
            if ip and ip != "-":
                if "/" not in ip:
                    ip = f"{ip}/{(args.prefix or str(STANDAARD_PREFIX)).lstrip('/')}"
                    zonder_prefix += 0 if args.prefix else 1
                opm.append("IP uit Classic. Beheerd via OOBM? Verplaats het dan naar mgmt_ip")
            else:
                ip = ""
            w.writerow({"serial": "" if stack else ser, "hostname": host, "stack": "ja" if stack else "",
                        "site_collection": args.site_collection or "",
                        "site": r.get("site", ""), "device_group": r.get("group", ""),
                        "golf": r.get("site", "") or "classic", "sys_vlan_ip": ip, "beheer_vlan": args.beheer_vlan,
                        "mgmt_ip": "", "systeemprofiel": "sys-system-info-profile", "opmerking": ". ".join(opm)})
            n += 1
    print(f"{n} switches naar {args.out}.")
    if stacks:
        print(f"  {stacks} VSF-stacks: de bulk-upload ondersteunt geen stacks. Ze worden gemarkeerd en komen niet in de upload.")
    if zonder_prefix:
        print(f"  {zonder_prefix} IP's zonder prefix kregen /{STANDAARD_PREFIX}. Klopt dat niet: draai opnieuw met --prefix.")
    if not args.site_collection:
        print("  site_collection is leeg: Classic kent dat niet. Gebruik --site-collection of vul aan.")
    if overgeslagen:
        print(f"  {len(overgeslagen)} niet-CX switches overgeslagen: {', '.join(overgeslagen[:10])}")
    print("  De Classic-groep wordt de device group. Draai daarna 'controleer'.")
    return 0


STANDAARD_GLOBAAL = "ALIAS_VLAN_DESCRIPTION"  # DNS: via een DNS-profiel op Global, niet via aliassen


def lees_bulk_rijen(pad):
    """Alle ingevulde rijen van eigen aliassen op device-scope: {(type, alias): {serial: [waarden...]}} plus koppen."""
    per, koppen, sectie, kop = defaultdict(lambda: defaultdict(list)), {}, None, None
    with open(pad, newline="", encoding="utf-8-sig") as f:
        for c in csv.reader(f):
            while c and c[-1] == "":
                c.pop()
            if not c:
                kop = None
                continue
            if c[0].startswith("#"):
                sectie, kop = c[0], None
            elif c[0] in ("Alias Name", "Pre-defined Alias Name"):
                kop = c
                if sectie and sectie.startswith("#ALIAS_"):
                    koppen[sectie[1:]] = c
            elif kop and sectie and sectie.startswith("#ALIAS_") and len(c) >= 9:
                c += [""] * (len(kop) - len(c))
                if c[3] != "Device" or not any(c[9:]):
                    continue
                per[(c[1], c[0])][c[7]].append(tuple(c[9:len(kop)]))
    return per, koppen


def cmd_globaliseer(args):
    """Waarden die de import op elke switch vastzette, naar Global trekken en op de switches leegmaken."""
    types = [x.strip() for x in args.types.split(",") if x.strip()]
    per, koppen = lees_bulk_rijen(args.download)
    os.makedirs(args.out, exist_ok=True)
    globaal, leeg, afwijkingen = defaultdict(list), defaultdict(list), []
    n_alias = 0
    for (typ, alias), per_switch in sorted(per.items()):
        if typ not in types:
            continue
        n_alias += 1
        waarden = {s: tuple(sorted(v)) for s, v in per_switch.items()}
        telling = defaultdict(list)
        for s, w in waarden.items():
            telling[w].append(s)
        standaard, met = max(telling.items(), key=lambda x: len(x[1]))
        for w in standaard:
            globaal[typ].append([alias, typ, FUNCTIE, "Global", "", "", "", "", "Yes"] + list(w))
        for s, w in sorted(waarden.items()):
            if w != standaard:
                afwijkingen.append((alias, s, " | ".join("; ".join(x) for x in w), " | ".join("; ".join(x) for x in standaard)))
                if not args.ook_afwijkers:
                    continue
            leeg[typ].append([alias, typ, FUNCTIE, "Device", "", "", "", s, "Yes"] + [""] * (len(koppen[typ]) - 9))

    def schrijf(naam, rijen, plaats_kolommen_uit=None):
        with open(os.path.join(args.out, naam), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            for i, typ in enumerate(sorted(rijen)):
                if i:
                    w.writerow([])
                f.write("#" + typ + "\n")
                w.writerow(koppen[typ])
                w.writerows(rijen[typ])
            f.write("\n")

    # device-rijen hebben de hierarchie nodig zoals in de download
    hier = {}
    with open(args.download, newline="", encoding="utf-8-sig") as f:
        for c in csv.reader(f):
            if len(c) >= 9 and c[3] == "Device" and c[7]:
                hier.setdefault(c[7], c[4:7])
    for rijen in leeg.values():
        for r in rijen:
            r[4:7] = hier.get(r[7], ["", "", ""])

    schrijf("2-global-waarden.csv", globaal)
    with open(os.path.join(args.out, "1-aliassen-aanmaken-op-global.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["alias", "type", "device_function"])
        for typ in sorted(globaal):
            for alias in sorted({r[0] for r in globaal[typ]}):
                w.writerow([alias, typ, FUNCTIE])
    with open(os.path.join(args.out, "3-opkuis-per-switch.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["serial", "site", "device_group", "alias", "type"])
        for typ in sorted(leeg):
            for r in leeg[typ]:
                w.writerow([r[7], r[5], r[6], r[0], typ])
    with open(os.path.join(args.out, "afwijkingen.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["alias", "serial", "waarde_op_switch", "standaard"])
        w.writerows(afwijkingen)
    n_leeg = sum(len(v) for v in leeg.values())
    print(f"{n_alias} aliassen uit {args.download}")
    print(f"  1-aliassen-aanmaken-op-global.csv   {n_alias} aliassen die eerst op Global moeten bestaan (UI of API)")
    print(f"  2-global-waarden.csv                {sum(len(v) for v in globaal.values())} rijen: de standaardwaarde, upload pas na stap 1")
    print(f"  3-opkuis-per-switch.csv             {n_leeg} device-level waarden te verwijderen (UI of API, niet via bulk)")
    print(f"  afwijkingen.csv                     {len(afwijkingen)} switches met een andere waarde dan de standaard"
          + ("" if args.ook_afwijkers else " (niet in de opkuislijst, eerst beslissen)"))
    print("De bulk-upload werkt enkel bestaande aliassen bij en kan ze niet aanmaken of verwijderen.")
    return 0


def bouw_parser():
    p = argparse.ArgumentParser(prog="cnx alias", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def gemeen(sp):
        sp.add_argument("--toestellen", required=True)
        sp.add_argument("--namen", help="namen.csv met de bestaande namen uit new Central")
        sp.add_argument("--config", default=standaard_config(), help="standaard klantconfig.json in de werkmap, anders de meegeleverde")

    c = sub.add_parser("controleer"); gemeen(c)
    c.add_argument("--bevindingen", default="bevindingen.csv")
    g = sub.add_parser("genereer"); gemeen(g)
    g.add_argument("--out", default="05-aliassen")
    g.add_argument("--max-rijen", type=int, default=5000, help="maximum rijen per bestand (standaard 5000)")
    g.add_argument("--x-voor-hierarchie", action="store_true",
                   help="'x' in site collection, site en device group zetten zoals in de HPE-template")
    v = sub.add_parser("vergelijk"); gemeen(v)
    v.add_argument("--download", required=True, help="bulk-download uit new Central")
    v.add_argument("--uit", default="vergelijking.csv")
    l = sub.add_parser("uit-classic-lijst")
    l.add_argument("--lijst", required=True, help="export van Devices > Switches uit Classic Central")
    l.add_argument("--prefix", help="prefix voor IP's zonder prefix (standaard 24)")
    l.add_argument("--site-collection", help="site collection in new Central voor alle switches")
    l.add_argument("--beheer-vlan", default="", help="beheer-VLAN van de switches (leeg: standaard_vlan uit de klantconfig)")
    l.add_argument("--out", default="toestellen.csv")
    l.add_argument("--overschrijf", action="store_true")
    gl = sub.add_parser("globaliseer", help="geimporteerde waarden naar Global trekken")
    gl.add_argument("--download", required=True, help="bulk-download uit new Central")
    gl.add_argument("--types", default=STANDAARD_GLOBAAL, help=f"alias-types, komma-gescheiden (standaard {STANDAARD_GLOBAAL})")
    gl.add_argument("--ook-afwijkers", action="store_true", help="ook switches met een afwijkende waarde in de opkuislijst")
    gl.add_argument("--out", default="06-globaal")
    u = sub.add_parser("uit-classic")
    u.add_argument("--export", required=True, help="map met inventory.csv van cx_lees_toestellen.py")
    u.add_argument("--groepen", help="groepen.csv met groep,device_function[,cnx_groep]")
    u.add_argument("--out", default="toestellen.csv")
    return p


COMMANDOS = {"controleer": cmd_controleer, "genereer": cmd_genereer, "vergelijk": cmd_vergelijk,
             "uit-classic": cmd_uit_classic, "uit-classic-lijst": cmd_uit_classic_lijst,
             "globaliseer": cmd_globaliseer}


def main():
    args = bouw_parser().parse_args()
    return COMMANDOS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

"""Migratieplan AOS-8 naar AOS-10 per cluster (controllerpaar en zijn APs), op basis van de inventaris uit aos8.py.

Een plan bestaat uit een klantbreed deel (eenmalig: GreenLake, licenties, structuur en configuratie in Central) en
per gekozen cluster een stappenplan in fasen. Elke stap heeft een vaste id, zodat de voortgang (afgevinkte stappen)
in de browser bewaard kan worden (de server bewaart niets).

De stappen zijn een werkwijze, geen vervanging van de migratiegids van HPE: commando's die per AOS-8-versie kunnen
verschillen, staan gemarkeerd als na te kijken.
"""
import datetime, hashlib, html, re
from collections import Counter, defaultdict

KLANTBREED = "_klant"


# ---------------------------------------------------------------- invoer van de browser

MAX_STAPPEN = 5000


def inventaris_uit(x):
    """De inventaris zoals de browser ze terugstuurt (het resultaat van aos8.analyseer). Kijkt de vorm na."""
    if not isinstance(x, dict) or not isinstance(x.get("clusters"), list) or not isinstance(x.get("aps"), list):
        raise ValueError("Lees eerst de inventaris van deze klant in.")
    for k in ("clusters", "aps", "controllers"):
        if not all(isinstance(i, dict) for i in x.get(k) or []):
            raise ValueError("ongeldige inventaris")
    return x


def voortgang_uit(v):
    """Afgevinkte stappen van de browser: {cluster: {stap-id: tijd}}. Enkel geldige ids en tekst, de rest valt weg."""
    uit, n = {}, 0
    for c, stappen in (v.items() if isinstance(v, dict) else []):
        if not isinstance(stappen, dict):
            continue
        for stap, tijd in stappen.items():
            if n >= MAX_STAPPEN:
                return uit
            if re.fullmatch(r"[a-z0-9-]{1,40}", str(stap)) and isinstance(tijd, str):
                uit.setdefault(str(c)[:200], {})[stap] = tijd[:20]
                n += 1
    return uit


# ---------------------------------------------------------------- het plan

def _stap(id_, titel, tekst, cmd=None, data=None, let_op=None, nakijken=False):
    return {"id": id_, "titel": titel, "tekst": tekst, "cmd": cmd or [], "data": data or [], "let_op": let_op or "", "nakijken": nakijken}


def _aantal(n, enkel, meer):
    return f"{n} {enkel if n == 1 else meer}"


def klantbreed(res):
    s = res["samenvatting"]
    meenemen = s["ok"] + s["einde"]
    versies = ", ".join(sorted(s.get("versies", {}))) or "onbekend"
    return [
        {"fase": "Eenmalig per klant", "stappen": [
            _stap("k-greenlake", "Toestellen en abonnementen in GreenLake",
                  f"Zet de serienummers van alle APs en controllers die meegaan in de GreenLake-workspace van de klant, wijs ze toe aan "
                  f"new Central en ken abonnementen toe: {_aantal(meenemen, 'AP', 'APs')} (zonder de {s['nee']} die vervangen worden) en "
                  f"{_aantal(s['controllers'], 'gateway', 'gateways')}. De lijst met serienummers staat onder Alle APs (Exporteer CSV).",
                  let_op="Nieuwe APs ter vervanging van de 200-reeks ook meteen toevoegen."),
            _stap("k-versie", "AOS-10-doelversie kiezen",
                  f"Kies een LSR-versie die alle AP- en gatewaymodellen ondersteunt. De controllers draaien nu {versies}."
                  + (f" Let op de {s['einde']} APs met einde support: hun laatste AOS-10-release bepaalt hoe lang je op die versie kan blijven." if s["einde"] else "")),
            _stap("k-structuur", "Structuur in Central",
                  "Maak de site collections en sites aan (een site per locatie), een device group voor de APs en een device group per "
                  "gatewaycluster. De AP-groepen uit AOS-8 (zie AP-groepen) zijn de basis voor de indeling."),
            _stap("k-config", "Draadloze configuratie in Central",
                  "Maak in de Library de WLAN-profielen voor de getunnelde SSID's (forward mode: tunnel naar de gatewaycluster), de rollen, "
                  "de VLAN's op de gateways en de authenticatieservers (RADIUS/ClearPass). Neem de waarden over uit de AOS-8-configuratie "
                  "(show wlan virtual-ap, show wlan ssid-profile, show aaa server-group)."),
            _stap("k-radius", "RADIUS-clients bijwerken",
                  "Voeg in ClearPass of NPS de nieuwe RADIUS-clients toe: de IP-adressen van de gateways (en van de APs als die zelf "
                  "authenticeren in het profiel dat je kiest). Doe dit voor de eerste golf, anders faalt 802.1X."),
            _stap("k-netwerk", "Bereikbaarheid naar Central",
                  "APs en gateways moeten uitgaand HTTPS (443) naar Central en GreenLake kunnen, en NTP en DNS hebben. Kijk de firewall en "
                  "eventuele proxy na voor de beheer-VLAN's van de APs en de controllers."),
            _stap("k-lab", "Werkwijze testen in het lab",
                  "Doorloop het volledige plan eerst op een labcluster: controller omzetten, een AP omzetten, SSID's testen, en ook de "
                  "terugweg. Pas de stappen aan waar de praktijk anders is."),
        ]}]


def cluster_plan(c, aps_cluster, ctrls):
    """Stappen voor een cluster. c = cluster uit aos8.gereedheid, aps_cluster = zijn APs, ctrls = zijn controllers."""
    namen = [x["naam"] for x in ctrls]
    eerste = namen[-1] if len(namen) > 1 else namen[0]          # bv. ...W02 eerst, ...W01 blijft het langst op AOS-8
    blijft = [n for n in namen if n != eerste]
    redundant = len(namen) >= 2
    groepen = Counter(a["groep"] for a in aps_cluster)
    nee = [a for a in aps_cluster if a["aos10"] == "nee"]
    down = [a for a in aps_cluster if not a["up"]]
    default = [a for a in aps_cluster if a["groep"].lower() == "default"]
    mac = [a for a in aps_cluster if re.fullmatch(r"([0-9a-f]{2}[:-]){5}[0-9a-f]{2}", a["naam"], re.I)]
    ctrl_tekst = [f"{x['naam']}: {x.get('model') or '?'}, {x.get('ip') or '?'}, {x['aps']} APs" for x in ctrls]
    fasen = []

    voor = [
        _stap("a-inventaris", "Inventaris van deze cluster nakijken",
              f"{_aantal(len(aps_cluster), 'AP', 'APs')} in {_aantal(len(groepen), 'AP-groep', 'AP-groepen')}, op {', '.join(namen)}.",
              data=ctrl_tekst + [f"AP-groep {g}: {n} APs" for g, n in groepen.most_common()]),
    ]
    if nee:
        voor.append(_stap("a-vervangen", f"{_aantal(len(nee), 'AP', 'APs')} vervangen",
                          "Deze APs ondersteunen AOS-10 niet. Vervang ze voor of tijdens de migratie door een AOS-10-model; "
                          "zet de nieuwe in GreenLake en Central voor je begint.",
                          data=[f"{a['naam']} ({a['model']}, {a['groep']}, {a['serial']})" for a in nee[:300]],
                          let_op="Zolang ze er hangen, vallen ze uit zodra hun controller naar AOS-10 gaat."))
    opkuis = [f"down: {a['naam']} ({a['groep']})" for a in down] + [f"groep default: {a['naam']}" for a in default] + \
             [f"geen naam: {a['naam']} ({a['groep']})" for a in mac]
    if opkuis:
        voor.append(_stap("a-opkuis", "Opkuisen", "Los dit op of beslis wat ermee gebeurt, zodat je na de migratie niet zoekt "
                          "of een AP ontbreekt door de migratie of al eerder.", data=opkuis[:300]))
    voor += [
        _stap("a-central", "Site en device group in Central",
              "Zet de sites voor deze AP-groepen klaar en kies de device group voor de APs en voor de gateways van deze cluster. "
              "Wijs de serienummers in GreenLake/Central al toe aan de juiste site en groep, dan landen ze meteen goed.",
              data=[f"AP-groep {g} → site ...  (vul in)" for g in groepen]),
        _stap("a-gateway-config", "Gatewayconfiguratie klaarzetten",
              "Zet in de device group van de gateways: beheer-IP per gateway (het IP van de controller kan je hergebruiken), "
              "default gateway, DNS, NTP, de uplink (trunk met de user-VLAN's van de getunnelde SSID's) en de clusterinstellingen.",
              data=ctrl_tekst),
        _stap("a-backup", "Back-up van AOS-8",
              "Bewaar de configuratie van de conductor en van deze controllers, en een AP-lijst van deze cluster als referentie "
              "voor de controle achteraf.",
              cmd=["show ap database long", "show running-config", "backup flash"]),
        _stap("a-venster", "Onderhoudsvenster en communicatie",
              ("In stappen: de getunnelde SSID's blijven beschikbaar, maar roaming tussen APs op AOS-8 en AOS-10 is niet naadloos. "
               "Zet de APs per gebouw of verdieping om en verwittig de gebruikers.") if redundant else
              ("Deze cluster heeft maar een controller: zodra die naar AOS-10 gaat, verliezen de APs op AOS-8 hun tunnel. "
               "Plan een onderhoudsvenster voor controller en APs samen, of zet eerst een tijdelijke gateway in Central en migreer "
               "de APs daarnaar."),
              let_op="" if redundant else "Reken op uitval van het draadloze netwerk tijdens het venster."),
    ]
    fasen.append({"fase": "Voorbereiden", "stappen": voor})

    gw = []
    if redundant:
        gw.append(_stap("b-vrijmaken", f"{eerste} vrijmaken",
                        f"Haal {eerste} uit de AOS-8-cluster zodat alle APs naar {', '.join(blijft)} gaan. Controleer dat er "
                        f"geen APs meer op {eerste} staan.",
                        cmd=["show lc-cluster group-membership", f"show ap database long | include {eerste}"]))
    gw += [
        _stap("b-omzetten", f"{eerste} omzetten naar AOS-10",
              f"Verwijder {eerste} van de conductor, laad het AOS-10-image, wis de configuratie en herstart. De gateway meldt "
              "zich via GreenLake bij Central.",
              cmd=["copy scp: <server> <user> <aos10-image> system: partition 1", "boot system partition 1", "write erase all", "reload"],
              nakijken=True, let_op="Exacte commando's en volgorde nakijken in de migratiegids van HPE voor jouw AOS-8-versie."),
        _stap("b-central", f"{eerste} in Central",
              "De gateway staat online in Central, op de juiste site en in de device group van deze cluster, met de juiste firmware. "
              "De configuratie is zonder fouten gepusht, de uplink en de VLAN's staan, en de cluster is gevormd."),
    ]
    fasen.append({"fase": "Eerste gateway" if redundant else "Gateway omzetten", "stappen": gw})

    ap = [
        _stap("c-precheck", "Controle voor de omzetting",
              "Laat AOS-8 nakijken of de APs AOS-10 en Central kunnen bereiken voor je ze omzet.",
              cmd=["ap convert pre-validate specific-aps"], nakijken=True),
        _stap("c-pilot", "Pilot: een of twee APs omzetten",
              "Zet een of twee APs om vanuit de conductor en controleer ze volledig voor je verder gaat: online in Central, AOS-10, "
              "juiste site en groep, naam, tunnel naar de gateway, en per SSID een testclient (aanmelden, VLAN, IP, internet).",
              cmd=["ap convert add ap-name <naam>", "ap convert active specific-aps server-type activate"], nakijken=True),
    ]
    for g, n in groepen.most_common():
        ap.append(_stap("c-g-" + hashlib.sha1(g.encode()).hexdigest()[:10], f"AP-groep {g} omzetten ({n} APs)",
                        "Zet de APs van deze groep om en controleer daarna in Central: aantal online, namen, site, en een testclient.",
                        cmd=[f"ap convert add ap-group {g}", "ap convert active specific-aps server-type activate"], nakijken=True))
    ap.append(_stap("c-controle", "Alle APs van deze cluster op AOS-10",
                    f"Op AOS-8 staan geen APs meer van deze cluster; in Central staan er {len(aps_cluster) - len(nee)} online "
                    "(plus de vervangers van de APs die niet mee konden).",
                    cmd=["show ap database long"]))
    fasen.append({"fase": "APs omzetten", "stappen": ap})

    if redundant:
        fasen.append({"fase": "Tweede gateway", "stappen": [
            _stap("d-omzetten", f"{', '.join(blijft)} omzetten naar AOS-10",
                  "Nu er geen APs meer op AOS-8 hangen: verwijder de controller van de conductor en zet hem om zoals de eerste.",
                  cmd=["copy scp: <server> <user> <aos10-image> system: partition 1", "boot system partition 1", "write erase all", "reload"],
                  nakijken=True),
            _stap("d-cluster", "Cluster compleet",
                  "Beide gateways staan in dezelfde device group en vormen samen de cluster. Elke AP heeft een actieve en een "
                  "stand-by gateway. Test een failover: herstart een gateway en kijk of de clients blijven werken."),
        ]})

    fasen.append({"fase": "Afronden", "stappen": [
        _stap("e-aos8", "AOS-8 opkuisen", "Verwijder de controllers van deze cluster uit de conductor en geef de AOS-8-licenties vrij."),
        _stap("e-doc", "Documentatie en overdracht", "Werk de documentatie bij (namen, IP's, sites) en meld de klant dat deze cluster klaar is."),
    ]})
    terug = ("Zolang de laatste controller nog op AOS-8 staat, blijven de APs die nog niet omgezet zijn werken. Een AP die al op "
             "AOS-10 staat, terugzetten naar AOS-8 vraagt een downgrade van de firmware: test die terugweg in het lab voor de "
             "eerste productiegolf.")
    return {"naam": c["naam"], "redundant": redundant, "aps": len(aps_cluster), "vervangen": len(nee), "fasen": fasen,
            "terugval": terug, "blokkade": c.get("blokkade", ""),
            "ap_lijst": [{"naam": a["naam"], "model": a["model"], "groep": a["groep"], "serial": a["serial"], "aos10": a["aos10_label"]}
                         for a in sorted(aps_cluster, key=lambda a: (a["groep"], a["naam"]))]}


def maak_plan(res, clusternamen):
    if not isinstance(clusternamen, list) or not clusternamen:
        raise ValueError("kies minstens een cluster")
    cl = {c["naam"]: c for c in res["clusters"]}
    onbekend = [n for n in clusternamen if n not in cl]
    if onbekend:
        raise ValueError("onbekende cluster: " + ", ".join(map(str, onbekend[:5])))
    per_ctrl = defaultdict(list)
    for a in res["aps"]:
        per_ctrl[a["controller"]].append(a)
    golven = []
    for n in clusternamen:
        c = cl[n]
        leden = set(n.split(" + "))
        ctrls = sorted((x for x in res["controllers"] if x["naam"] in leden), key=lambda x: x["naam"])
        aps = [a for x in ctrls for a in per_ctrl.get(x["naam"], [])]
        golven.append(cluster_plan(c, aps, ctrls))
    return {"klant": res.get("klant", ""), "tijd": datetime.datetime.now().isoformat(timespec="seconds"),
            "klantbreed": klantbreed(res), "clusters": golven}


# ---------------------------------------------------------------- als document

def plan_html(plan, vg=None):
    vg = vg or {}
    e = lambda x: html.escape(str(x if x is not None else ""))  # noqa: E731

    def stappen(fasen, sleutel):
        uit = []
        for f in fasen:
            uit.append(f"<h3>{e(f['fase'])}</h3><ol>")
            for s in f["stappen"]:
                klaar = vg.get(sleutel, {}).get(s["id"])
                uit.append(f"<li><div class='st'><span class='vak'>{'✓' if klaar else ''}</span><b>{e(s['titel'])}</b>"
                           + (f" <span class='nk'>nakijken</span>" if s["nakijken"] else "")
                           + (f" <span class='kl'>gedaan {e(klaar.replace('T', ' '))}</span>" if klaar else "") + "</div>"
                           + f"<p>{e(s['tekst'])}</p>"
                           + ("<pre>" + "\n".join(e(c) for c in s["cmd"]) + "</pre>" if s["cmd"] else "")
                           + ("<ul class='d'>" + "".join(f"<li>{e(d)}</li>" for d in s["data"]) + "</ul>" if s["data"] else "")
                           + (f"<p class='lo'>Let op: {e(s['let_op'])}</p>" if s["let_op"] else "") + "</li>")
            uit.append("</ol>")
        return "".join(uit)
    titel = "Migratieplan AOS-8 naar AOS-10" + (f" · {plan['klant']}" if plan.get("klant") else "")
    delen = [f"<h1>{e(titel)}</h1><p class='m'>Gemaakt op {e(plan['tijd'][:16].replace('T', ' '))}. Clusters: "
             f"{e(', '.join(c['naam'] for c in plan['clusters']))}. Stappen gemarkeerd met <span class='nk'>nakijken</span> bevatten "
             "commando's die per AOS-8-versie kunnen verschillen: kijk ze na in de migratiegids van HPE.</p>",
             "<h2>Klantbreed (eenmalig)</h2>", stappen(plan["klantbreed"], KLANTBREED)]
    for c in plan["clusters"]:
        delen.append(f"<h2 class='nb'>Cluster {e(c['naam'])}</h2><p class='m'>{e(c['aps'])} APs, "
                     f"{'twee of meer controllers: in stappen' if c['redundant'] else 'een controller: onderhoudsvenster'}"
                     + (f". Blokkade: {e(c['blokkade'])}" if c["blokkade"] else "") + ".</p>")
        delen.append(stappen(c["fasen"], c["naam"]))
        delen.append(f"<h3>Terugval</h3><p>{e(c['terugval'])}</p>")
        delen.append("<h3>APs in deze cluster</h3><table><thead><tr><th>Naam</th><th>Model</th><th>AP-groep</th><th>Serienummer</th>"
                     "<th>AOS-10</th><th>Omgezet</th></tr></thead><tbody>"
                     + "".join(f"<tr><td>{e(a['naam'])}</td><td>{e(a['model'])}</td><td>{e(a['groep'])}</td><td>{e(a['serial'])}</td>"
                               f"<td>{e(a['aos10'])}</td><td class='vak2'></td></tr>" for a in c["ap_lijst"]) + "</tbody></table>")
    css = ("body{font:13px/1.5 'Segoe UI',system-ui,sans-serif;color:#122033;margin:32px auto;max-width:980px;padding:0 16px}"
           "h1{font-size:22px;margin:0}h2{font-size:17px;margin:30px 0 4px;border-bottom:2px solid #2457d6;padding-bottom:4px}"
           "h3{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:#5f6c7f;margin:18px 0 6px}.m{color:#5f6c7f}"
           "ol{padding-left:20px}ol>li{margin:0 0 12px}.st{display:flex;gap:8px;align-items:center;flex-wrap:wrap}"
           ".vak{display:inline-grid;place-items:center;width:15px;height:15px;border:1.5px solid #5f6c7f;border-radius:3px;font-size:11px;color:#1f7a4a}"
           "p{margin:3px 0}pre{background:#f4f6f9;border:1px solid #e2e7ee;border-radius:6px;padding:6px 10px;font:12px Consolas,monospace;margin:4px 0;white-space:pre-wrap}"
           ".d{margin:4px 0;color:#2b3a4f;font-size:12.5px;columns:2}.lo{color:#a35d06}"
           ".nk{border:1px solid #2457d6;color:#2457d6;border-radius:999px;padding:0 7px;font-size:11px}"
           ".kl{color:#1f7a4a;font-size:11.5px}table{border-collapse:collapse;width:100%;font-size:12px}"
           "th,td{border-bottom:1px solid #e2e7ee;padding:3px 6px;text-align:left}th{background:#f8fafc;font-size:10.5px;text-transform:uppercase;color:#5f6c7f}"
           ".vak2{width:60px}@media print{body{margin:0}.nb{break-before:page}li,tr{break-inside:avoid}}")
    return (f"<!DOCTYPE html><html lang='nl'><head><meta charset='utf-8'><title>{e(titel)}</title><style>{css}</style></head>"
            f"<body>{''.join(delen)}</body></html>")

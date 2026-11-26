"""Migratieplan AOS-8 naar AOS-10 per cluster (controllerpaar en zijn APs), op basis van de inventaris uit aos8.py.

Een plan bestaat uit een klantbreed deel (eenmalig: GreenLake, licenties, structuur en configuratie in Central) en
per gekozen cluster een stappenplan in fasen. Elke stap heeft een vaste id, zodat de voortgang (afgevinkte stappen)
in de browser bewaard kan worden (de server bewaart niets).

De stappen zijn een werkwijze, geen vervanging van de migratiegids van HPE: commando's die per AOS-8-versie kunnen
verschillen, staan gemarkeerd als na te kijken.
"""
import datetime, hashlib, html, re
from collections import Counter, defaultdict

from .taal import _, huidig

KLANTBREED = "_klant"


# ---------------------------------------------------------------- invoer van de browser

MAX_STAPPEN = 5000


def inventaris_uit(x):
    """De inventaris zoals de browser ze terugstuurt (het resultaat van aos8.analyseer). Kijkt de vorm na."""
    if not isinstance(x, dict) or not isinstance(x.get("clusters"), list) or not isinstance(x.get("aps"), list):
        raise ValueError(_("Lees eerst de inventaris van deze klant in."))
    for k in ("clusters", "aps", "controllers"):
        if not all(isinstance(i, dict) for i in x.get(k) or []):
            raise ValueError(_("ongeldige inventaris"))
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
    versies = ", ".join(sorted(s.get("versies", {}))) or _("onbekend")
    return [
        {"fase": _("Eenmalig per klant"), "stappen": [
            _stap("k-greenlake", _("Toestellen en abonnementen in GreenLake"),
                  _("Zet de serienummers van alle APs en controllers die meegaan in de GreenLake-workspace van de klant, wijs ze toe aan "
                    "new Central en ken abonnementen toe: {aps} (zonder de {nee} die vervangen worden) en {gateways}. De lijst met "
                    "serienummers staat onder Alle APs (Exporteer CSV).",
                    aps=_aantal(meenemen, "AP", "APs"), nee=s["nee"], gateways=_aantal(s["controllers"], "gateway", "gateways")),
                  let_op=_("Nieuwe APs ter vervanging van de 200-reeks ook meteen toevoegen.")),
            _stap("k-versie", _("AOS-10-doelversie kiezen"),
                  _("Kies een LSR-versie die alle AP- en gatewaymodellen ondersteunt. De controllers draaien nu {versies}.", versies=versies)
                  + (_(" Let op de {n} APs met einde support: hun laatste AOS-10-release bepaalt hoe lang je op die versie kan blijven.",
                       n=s["einde"]) if s["einde"] else "")),
            _stap("k-structuur", _("Structuur in Central"),
                  _("Maak de site collections en sites aan (een site per locatie), een device group voor de APs en een device group per "
                    "gatewaycluster. De AP-groepen uit AOS-8 (zie AP-groepen) zijn de basis voor de indeling.")),
            _stap("k-config", _("Draadloze configuratie in Central"),
                  _("Maak in de Library de WLAN-profielen voor de getunnelde SSID's (forward mode: tunnel naar de gatewaycluster), de rollen, "
                    "de VLAN's op de gateways en de authenticatieservers (RADIUS/ClearPass). Neem de waarden over uit de AOS-8-configuratie "
                    "(show wlan virtual-ap, show wlan ssid-profile, show aaa server-group).")),
            _stap("k-radius", _("RADIUS-clients bijwerken"),
                  _("Voeg in ClearPass of NPS de nieuwe RADIUS-clients toe: de IP-adressen van de gateways (en van de APs als die zelf "
                    "authenticeren in het profiel dat je kiest). Doe dit voor de eerste golf, anders faalt 802.1X.")),
            _stap("k-netwerk", _("Bereikbaarheid naar Central"),
                  _("APs en gateways moeten uitgaand HTTPS (443) naar Central en GreenLake kunnen, en NTP en DNS hebben. Kijk de firewall en "
                    "eventuele proxy na voor de beheer-VLAN's van de APs en de controllers.")),
            _stap("k-lab", _("Werkwijze testen in het lab"),
                  _("Doorloop het volledige plan eerst op een labcluster: controller omzetten, een AP omzetten, SSID's testen, en ook de "
                    "terugweg. Pas de stappen aan waar de praktijk anders is.")),
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
        _stap("a-inventaris", _("Inventaris van deze cluster nakijken"),
              _("{aps} in {groepen}, op {namen}.", aps=_aantal(len(aps_cluster), "AP", "APs"),
                groepen=_aantal(len(groepen), _("AP-groep"), _("AP-groepen")), namen=", ".join(namen)),
              data=ctrl_tekst + [_("AP-groep {groep}: {n} APs", groep=g, n=n) for g, n in groepen.most_common()]),
    ]
    if nee:
        voor.append(_stap("a-vervangen", _("{aps} vervangen", aps=_aantal(len(nee), "AP", "APs")),
                          _("Deze APs ondersteunen AOS-10 niet. Vervang ze voor of tijdens de migratie door een AOS-10-model; "
                            "zet de nieuwe in GreenLake en Central voor je begint."),
                          data=[f"{a['naam']} ({a['model']}, {a['groep']}, {a['serial']})" for a in nee[:300]],
                          let_op=_("Zolang ze er hangen, vallen ze uit zodra hun controller naar AOS-10 gaat.")))
    opkuis = [_("down: {naam} ({groep})", naam=a["naam"], groep=a["groep"]) for a in down] + \
             [_("groep default: {naam}", naam=a["naam"]) for a in default] + \
             [_("geen naam: {naam} ({groep})", naam=a["naam"], groep=a["groep"]) for a in mac]
    if opkuis:
        voor.append(_stap("a-opkuis", _("Opkuisen"), _("Los dit op of beslis wat ermee gebeurt, zodat je na de migratie niet zoekt "
                          "of een AP ontbreekt door de migratie of al eerder."), data=opkuis[:300]))
    voor += [
        _stap("a-central", _("Site en device group in Central"),
              _("Zet de sites voor deze AP-groepen klaar en kies de device group voor de APs en voor de gateways van deze cluster. "
                "Wijs de serienummers in GreenLake/Central al toe aan de juiste site en groep, dan landen ze meteen goed."),
              data=[_("AP-groep {groep} → site ...  (vul in)", groep=g) for g in groepen]),
        _stap("a-gateway-config", _("Gatewayconfiguratie klaarzetten"),
              _("Zet in de device group van de gateways: beheer-IP per gateway (het IP van de controller kan je hergebruiken), "
                "default gateway, DNS, NTP, de uplink (trunk met de user-VLAN's van de getunnelde SSID's) en de clusterinstellingen."),
              data=ctrl_tekst),
        _stap("a-backup", _("Back-up van AOS-8"),
              _("Bewaar de configuratie van de conductor en van deze controllers, en een AP-lijst van deze cluster als referentie "
                "voor de controle achteraf."),
              cmd=["show ap database long", "show running-config", "backup flash"]),
        _stap("a-venster", _("Onderhoudsvenster en communicatie"),
              _("In stappen: de getunnelde SSID's blijven beschikbaar, maar roaming tussen APs op AOS-8 en AOS-10 is niet naadloos. "
                "Zet de APs per gebouw of verdieping om en verwittig de gebruikers.") if redundant else
              _("Deze cluster heeft maar een controller: zodra die naar AOS-10 gaat, verliezen de APs op AOS-8 hun tunnel. "
                "Plan een onderhoudsvenster voor controller en APs samen, of zet eerst een tijdelijke gateway in Central en migreer "
                "de APs daarnaar."),
              let_op="" if redundant else _("Reken op uitval van het draadloze netwerk tijdens het venster.")),
    ]
    fasen.append({"fase": _("Voorbereiden"), "stappen": voor})

    gw = []
    if redundant:
        gw.append(_stap("b-vrijmaken", _("{naam} vrijmaken", naam=eerste),
                        _("Haal {naam} uit de AOS-8-cluster zodat alle APs naar {andere} gaan. Controleer dat er "
                          "geen APs meer op {naam} staan.", naam=eerste, andere=", ".join(blijft)),
                        cmd=["show lc-cluster group-membership", f"show ap database long | include {eerste}"]))
    gw += [
        _stap("b-omzetten", _("{naam} omzetten naar AOS-10", naam=eerste),
              _("Verwijder {naam} van de conductor, laad het AOS-10-image, wis de configuratie en herstart. De gateway meldt "
                "zich via GreenLake bij Central.", naam=eerste),
              cmd=["copy scp: <server> <user> <aos10-image> system: partition 1", "boot system partition 1", "write erase all", "reload"],
              nakijken=True, let_op=_("Exacte commando's en volgorde nakijken in de migratiegids van HPE voor jouw AOS-8-versie.")),
        _stap("b-central", _("{naam} in Central", naam=eerste),
              _("De gateway staat online in Central, op de juiste site en in de device group van deze cluster, met de juiste firmware. "
                "De configuratie is zonder fouten gepusht, de uplink en de VLAN's staan, en de cluster is gevormd.")),
    ]
    fasen.append({"fase": _("Eerste gateway") if redundant else _("Gateway omzetten"), "stappen": gw})

    ap = [
        _stap("c-precheck", _("Controle voor de omzetting"),
              _("Laat AOS-8 nakijken of de APs AOS-10 en Central kunnen bereiken voor je ze omzet."),
              cmd=["ap convert pre-validate specific-aps"], nakijken=True),
        _stap("c-pilot", _("Pilot: een of twee APs omzetten"),
              _("Zet een of twee APs om vanuit de conductor en controleer ze volledig voor je verder gaat: online in Central, AOS-10, "
                "juiste site en groep, naam, tunnel naar de gateway, en per SSID een testclient (aanmelden, VLAN, IP, internet)."),
              cmd=["ap convert add ap-name <naam>", "ap convert active specific-aps server-type activate"], nakijken=True),
    ]
    for g, n in groepen.most_common():
        ap.append(_stap("c-g-" + hashlib.sha1(g.encode()).hexdigest()[:10], _("AP-groep {groep} omzetten ({n} APs)", groep=g, n=n),
                        _("Zet de APs van deze groep om en controleer daarna in Central: aantal online, namen, site, en een testclient."),
                        cmd=[f"ap convert add ap-group {g}", "ap convert active specific-aps server-type activate"], nakijken=True))
    ap.append(_stap("c-controle", _("Alle APs van deze cluster op AOS-10"),
                    _("Op AOS-8 staan geen APs meer van deze cluster; in Central staan er {n} online "
                      "(plus de vervangers van de APs die niet mee konden).", n=len(aps_cluster) - len(nee)),
                    cmd=["show ap database long"]))
    fasen.append({"fase": _("APs omzetten"), "stappen": ap})

    if redundant:
        fasen.append({"fase": _("Tweede gateway"), "stappen": [
            _stap("d-omzetten", _("{namen} omzetten naar AOS-10", namen=", ".join(blijft)),
                  _("Nu er geen APs meer op AOS-8 hangen: verwijder de controller van de conductor en zet hem om zoals de eerste."),
                  cmd=["copy scp: <server> <user> <aos10-image> system: partition 1", "boot system partition 1", "write erase all", "reload"],
                  nakijken=True),
            _stap("d-cluster", _("Cluster compleet"),
                  _("Beide gateways staan in dezelfde device group en vormen samen de cluster. Elke AP heeft een actieve en een "
                    "stand-by gateway. Test een failover: herstart een gateway en kijk of de clients blijven werken.")),
        ]})

    fasen.append({"fase": _("Afronden"), "stappen": [
        _stap("e-aos8", _("AOS-8 opkuisen"), _("Verwijder de controllers van deze cluster uit de conductor en geef de AOS-8-licenties vrij.")),
        _stap("e-doc", _("Documentatie en overdracht"), _("Werk de documentatie bij (namen, IP's, sites) en meld de klant dat deze cluster klaar is.")),
    ]})
    terug = _("Zolang de laatste controller nog op AOS-8 staat, blijven de APs die nog niet omgezet zijn werken. Een AP die al op "
              "AOS-10 staat, terugzetten naar AOS-8 vraagt een downgrade van de firmware: test die terugweg in het lab voor de "
              "eerste productiegolf.")
    return {"naam": c["naam"], "redundant": redundant, "aps": len(aps_cluster), "vervangen": len(nee), "fasen": fasen,
            "terugval": terug, "blokkade": c.get("blokkade", ""),
            "ap_lijst": [{"naam": a["naam"], "model": a["model"], "groep": a["groep"], "serial": a["serial"], "aos10": _(a["aos10_label"])}
                         for a in sorted(aps_cluster, key=lambda a: (a["groep"], a["naam"]))]}


def maak_plan(res, clusternamen, tijd=None):
    if not isinstance(clusternamen, list) or not clusternamen:
        raise ValueError(_("kies minstens een cluster"))
    cl = {c["naam"]: c for c in res["clusters"]}
    onbekend = [n for n in clusternamen if n not in cl]
    if onbekend:
        raise ValueError(_("onbekende cluster: {namen}", namen=", ".join(map(str, onbekend[:5]))))
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
    return {"klant": res.get("klant", ""), "tijd": tijd or datetime.datetime.now().isoformat(timespec="seconds"),
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
                           + (f" <span class='nk'>{e(_('nakijken'))}</span>" if s["nakijken"] else "")
                           + (f" <span class='kl'>{e(_('gedaan {tijd}', tijd=klaar.replace('T', ' ')))}</span>" if klaar else "") + "</div>"
                           + f"<p>{e(s['tekst'])}</p>"
                           + ("<pre>" + "\n".join(e(c) for c in s["cmd"]) + "</pre>" if s["cmd"] else "")
                           + ("<ul class='d'>" + "".join(f"<li>{e(d)}</li>" for d in s["data"]) + "</ul>" if s["data"] else "")
                           + (f"<p class='lo'>Let op: {e(s['let_op'])}</p>" if s["let_op"] else "") + "</li>")
            uit.append("</ol>")
        return "".join(uit)
    titel = _("Migratieplan AOS-8 naar AOS-10") + (f" · {plan['klant']}" if plan.get("klant") else "")
    delen = [f"<h1>{e(titel)}</h1><p class='m'>"
             + e(_("Gemaakt op {tijd}. Clusters: {clusters}.", tijd=plan["tijd"][:16].replace("T", " "),
                   clusters=", ".join(c["naam"] for c in plan["clusters"])))
             + " " + e(_("Stappen gemarkeerd met")) + f" <span class='nk'>{e(_('nakijken'))}</span> "
             + e(_("bevatten commando's die per AOS-8-versie kunnen verschillen: kijk ze na in de migratiegids van HPE.")) + "</p>",
             f"<h2>{e(_('Klantbreed (eenmalig)'))}</h2>", stappen(plan["klantbreed"], KLANTBREED)]
    for c in plan["clusters"]:
        delen.append(f"<h2 class='nb'>Cluster {e(c['naam'])}</h2><p class='m'>{e(c['aps'])} APs, "
                     + e(_("twee of meer controllers: in stappen") if c["redundant"] else _("een controller: onderhoudsvenster"))
                     + (". " + e(_("Blokkade: {tekst}", tekst=c["blokkade"])) if c["blokkade"] else "") + ".</p>")
        delen.append(stappen(c["fasen"], c["naam"]))
        delen.append(f"<h3>{e(_('Terugval'))}</h3><p>{e(c['terugval'])}</p>")
        delen.append(f"<h3>{e(_('APs in deze cluster'))}</h3><table><thead><tr>"
                     + "".join(f"<th>{e(_(k))}</th>" for k in ("Naam", "Model", "AP-groep", "Serienummer", "AOS-10", "Omgezet"))
                     + "</tr></thead><tbody>"
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
    return (f"<!DOCTYPE html><html lang='{huidig()}'><head><meta charset='utf-8'><title>{e(titel)}</title><style>{css}</style></head>"
            f"<body>{''.join(delen)}</body></html>")

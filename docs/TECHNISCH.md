# CNX Toolkit: technische achtergrond

Achtergrond bij de werking, vastgesteld in een labomgeving in november 2026.

## Toestel-aliassen voor access switches (CNX bulk upload)

Een tabel met een rij per access switch wordt het bulkformaat dat new Central in de UI aanvaardt
(Configuration > Library > Named Objects > Aliases > bulk upload). Voor nieuwe switches en voor switches uit Classic.

**Wat de bulk-upload niet kan:** aliassen aanmaken of verwijderen, en stacks. VSF-stacks worden gemarkeerd
(kolom `stack`) en komen in `manueel-stacks.csv`.

**Enkel AOS-CX access switches.** Core- en aggregation-switches worden manueel ingevoerd. Het script en de pagina
weigeren elke andere device function.

## Wat hier wel en niet in hoort

| Hier (device-scope, per switch) | Niet hier |
|---|---|
| Hostname, system VLAN IP (of DHCP), beheer-IP (OOBM) | Geheimen, alles wat voor een site, device group of de hele tenant gelijk is (gewone profielen op Global, Site of Device Group), en alles van core en aggregation (manueel) |

## Commandolijn

| Hulpmiddel | Voor wie |
|---|---|
| `cnx alias` | Vanaf de commandolijn, voor grote lijsten uit Excel of uit de Classic-export |
| `cnx api` | Wat de bulk-upload niet kan: aliassen aanmaken en lokale waarden verwijderen, via de API |

`cnx alias` leest en schrijft `toestellen.csv`; de webapp (Onboarden) maakt hetzelfde uploadbestand rechtstreeks uit Central.

## Bestanden

| Bestand | Inhoud |
|---|---|
| `toestellen-sjabloon.csv` | Kolommen: serial, hostname, site_collection, site, device_group, golf, sys_vlan_ip, beheer_vlan, mgmt_ip, systeemprofiel, opmerking. Een VSF-stack is een rij, met het serienummer van de conductor |
| `klantconfig.json` | Standaarden: System-info-profiel, patroon van de system VLAN-alias en standaard beheer-VLAN (120), beheerinterface |

## Namen die Central zelf kiest (vastgesteld op 12 november 2026)

| Waarde | Naam in Central | Gevolg |
|---|---|---|
| System VLAN IP | `sys_vlan_ipv4_<vlan-id>`, bijvoorbeeld `sys_vlan_ipv4_120` | Per switch kolom `beheer_vlan`. Standaard 120 |
| Hostname | in het profiel `sys-system-info-profile` bij een geimporteerde switch, anders in het profiel van de groep (bv. een gedeeld profiel per klant) | Per switch kolom `systeemprofiel`. Wordt overgenomen uit een bulk-download |

## Vertrekken van Classic

De snelste weg: in Classic Central **Devices > Switches > export** (CSV). Die lijst gaat rechtstreeks in de pagina
(sleep het bestand naar Export of gebruik Importeer CSV) of in het script met `uit-classic-lijst`.

| Kolom in de Classic-export | Wordt |
|---|---|
| DEVICE NAME | hostname |
| SERIAL | serial. Bij een VSF-stack toont Classic een stack-ID: dat veld blijft leeg en moet het serienummer van de conductor krijgen |
| SITE | site, en standaard ook de golf |
| GROUP | device group. Een Classic-groep met de toggle verschijnt in new Central als device group met dezelfde naam |
| IP ADDRESS | system VLAN IP. Classic geeft geen prefix: zonder `--prefix` wordt het /24. Beheerd via OOBM? Dan naar het veld beheer-IP |
| TYPE | enkel `AOS-CX` en `AOS-CX Stack` worden overgenomen |

Classic kent geen site collection: in de pagina vul je die in Tabel voor alle switches tegelijk in, in het script met `--site-collection`.

## Werkwijze met het script

```bash
# Switchlijst uit de UI van Classic omzetten
cnx alias uit-classic-lijst --lijst export_switch_list.csv --prefix 24 --site-collection Belgium --out toestellen.csv

# Of uit de API-export van cx_lees_toestellen.py (niet-access switches worden overgeslagen)
cnx alias uit-classic --export 02-export --groepen groepen.csv --out toestellen.csv

# Controleren
cnx alias controleer --toestellen toestellen.csv --namen namen.csv

# Uploadbestanden: een per golf, nooit een switch over twee bestanden
cnx alias genereer --toestellen toestellen.csv --out 05-aliassen

# Na de upload: bulk download uit Central en vergelijken
cnx alias vergelijk --toestellen toestellen.csv --download bulk_alias_download_....csv
```

Controles: dubbele serienummers, hostnames en IP's; een IP zonder prefix krijgt /24 (`standaard_prefix` in de
klantconfig) met een aandachtspunt; `DHCP` mag voor de system VLAN; geen netwerk-
of broadcastadres; hostname-regel uit de config; met `namen.csv` ook of site collection, site en device group
letterlijk bestaan in new Central. `genereer` weigert zolang er fouten zijn.

## Aanbevolen: System-info-profiel

- Nieuwe switches: hostname in het gedeelde profiel uit `klantconfig.json`.
- Switches uit Classic houden het geimporteerde `sys-system-info-profile`, hun hostname gaat daarin (kolom
  `systeemprofiel`, ingevuld door de import). Omzetten naar het gedeelde profiel kost een verwijdering per switch en
  levert weinig op.
- Opnieuw bekijken als iets uit het System-info-profiel centraal moet wijzigen (contact, locatie, tijdzone, banner):
  switches uit Classic halen dat dan niet op.

## Geimporteerde waarden naar Global trekken

Bij de import van een switch uit Classic zet Central heel wat globale config vast als alias op die ene switch:
26 VLAN-beschrijvingen (`sys_vlan_<id>_description`), de DNS-servers (`sys_dns_resolver`) en meer. Een waarde op
device-scope wint van Global, dus een wijziging op Global komt nooit op die switches.

De geimporteerde VLAN-objecten verwijzen naar de alias, niet naar de tekst. Daarom:
1. De alias met de standaardwaarde op **Global** zetten.
2. De waarde op **device-scope** leegmaken, zodat de switch Global erft.

```bash
cnx alias globaliseer --download bulk_alias_download_....csv --out 06-globaal
```

| Uitvoer | Inhoud |
|---|---|
| `1-aliassen-aanmaken-op-global.csv` | Aliassen die eerst op Global moeten bestaan. De bulk-upload kan ze niet aanmaken |
| `2-global-waarden.csv` | Per alias de waarde die op de meeste switches staat, op Global |
| `3-opkuis-per-switch.csv` | Per switch de lokale waarden die weg moeten. De bulk-upload kan ze niet verwijderen |
| `afwijkingen.csv` | Switches met een andere waarde dan de standaard. Niet in de opkuislijst tenzij `--ook-afwijkers` |

Standaard enkel `ALIAS_VLAN_DESCRIPTION`. DNS niet: zie hieronder. Nooit `ALIAS_IPV4_ADDRESS_TYPE`: dat is het beheer-IP.

### Aanmaken en opkuisen via de API

Vastgesteld op 12 november 2026: een alias is een LOCAL object op een scope, met de waarde in `default-value`
(VLAN-beschrijving: `{"vlan-description-value": {"description": "Security"}}`). Een alias op Global is een LOCAL
object op de scope Global, er is geen aparte toewijzing nodig.

```bash
# 0. Alleen-lezen
cnx api lees --naam sys_vlan_2006_description --serial <SERIAL> --global

# 1. Aanmaken op Global (eerst een, dan alles)
cnx api aanmaken --waarden 06-globaal/2-global-waarden.csv --alleen sys_vlan_2006_description --apply

# 2. Lokale waarden op de switches verwijderen (eerst een switch)
cnx api opkuisen --lijst 06-globaal/3-opkuis-per-switch.csv --serial <SERIAL> --alleen sys_vlan_2006_description --apply
```

Zonder `--apply` is alles een dry-run. Elke aanmaak wordt met een GET nagekeken en gelogd.
De DNS-servers (meerdere rijen per alias) maakt het script niet aan: zet die in een gewoon DNS-profiel op Global.
**Werkwijze in productie (per golf switches uit Classic):**
1. `globaliseer` op een bulk-download van de golf.
2. `cnx api aanmaken --library`: de aliassen gedeeld in de library en toegewezen aan Global voor Access
   Switch (`profile-type` `aliases`). `cnx api toewijzen` kijkt de toewijzing na en zet ze waar ze ontbreekt.
   `opkuisen` weigert een alias zonder toewijzing aan Global, zodat een switch nooit zonder waarde valt.
3. `cnx api opkuisen`: de lokale waarden op de switches weg. Ze erven de library-alias op Global.
4. Controle: bulk-download en `show running-config vlan <id>` op een switch.

Nooit eerst lokaal op Global aanmaken: Central laat die kopie daarna niet meer verwijderen zolang een switch ze
gebruikt ("is referred by 1 configs"), ook niet als dezelfde alias in de library klaarstaat. Voor het lab, waar dat
toch gebeurde: `naar-library --serial <switch>` zet de waarde tijdelijk lokaal op de switch, verwijdert de kopie op
Global en haalt de lokale waarde weer weg.

**Beslissing: globale aliassen horen in de library**, gedeeld en toegewezen aan Global, niet als lokaal object op
Global. Werkwijze, in deze volgorde, telkens eerst met een alias:

```bash
# a. alleen-lezen: hoe ziet een toewijzing aan Global eruit (profile-type)
cnx api toewijzingen
# b. in de library aanmaken en aan Global toewijzen
cnx api aanmaken --waarden 06-globaal/2-global-waarden.csv --library --alleen sys_vlan_2000_description --apply
# c. de lokale kopie op Global opruimen (enkel als de library-versie bestaat)
cnx api global-lokaal-weg --waarden 06-globaal/2-global-waarden.csv --alleen sys_vlan_2000_description --apply
```

Te verifieren: het `profile-type` voor een alias in `config-assignments` (standaard `aliases`, aan te passen met
`--profiel-type`), en of de library een naam aanvaardt die ook lokaal op Global bestaat. Weigert ze dat, dan eerst c
met `--forceer`, dan b. Tussen beide heeft de switch even geen beschrijving: enkel in een onderhoudsvenster.

Labtest 12 november 2026 op <SERIAL>:
- Aanmaken als LOCAL op Global (scope-ID via `/network-config/v1/global`): 26 keer 200.
- DELETE als LOCAL op de switch: 24 keer 200. "unexpected req_xpath" betekent dat de alias daar niet (meer) bestaat.
- `sys_dns_resolver` kan niet weg: "referenced by Dns sys-dns-profile". DNS gaat via een DNS-profiel op Global en het
  verwijderen van het geimporteerde `sys-dns-profile`, niet via aliassen. `opkuisen` slaat DNS standaard over.
- De switch neemt de waarde van Global over: na het opkuisen gebruikt <SERIAL> de alias op Global (Central
  weigert die te verwijderen omdat de switch ernaar verwijst). Nog na te kijken op de CLI van de switch.
- `profile-type` voor een alias in `config-assignments` is `aliases` (bevestigd uit de bestaande toewijzingen).

## VLAN's op Global ook voor aggregation en core

Elke `layer2-vlan` die op Global aan Access Switch hangt, ook toewijzen aan Aggregation en Core Switch:

```bash
cnx api vlans-doorzetten                            # dry-run: welke VLAN's, welke switches
cnx api vlans-doorzetten --apply
cnx api vlans-doorzetten --ook-beschrijvingen --apply   # ook sys_vlan_<id>_description
cnx api vlans-terugdraaien --log alias-api-log-<tijd>.json --apply
```

Gevolg: elke aggregation- en core-switch in new Central krijgt die VLAN's. Een VLAN dat daar al lokaal bestaat
(geimporteerd), houdt de lokale versie. Bestaande toewijzingen worden overgeslagen. Het logboek van
`--apply` is nodig om terug te draaien: bewaar het. Te verifieren: DELETE op `config-assignments` met dezelfde body.

## Wat het formaat doet (vastgesteld op 12 november 2026)

- Secties beginnen met `#TYPE` (eigen aliassen) of `#Profielnaam` (voorgedefinieerde aliassen). Elke subtabel heeft een eigen kopregel, gescheiden door een lege regel.
- De eerste negen kolommen zijn vast. Daarna de waardekolommen van het type.
- Eén device function per bestand. Hier altijd `Access Switch`.
- `Modified` moet `Yes` zijn voor elke rij die iets moet wijzigen of toevoegen. Een download staat volledig op `No`. Met `No` meldt de upload succes en wordt de rij genegeerd.
- De hostname is een voorgedefinieerde alias van het System-info-profiel. `Instance Name` is de naam van dat profiel.
- Een bulk-download bevat per poort een rij voor elke poort-alias, ook als ze leeg is. Download, aanpassen, terug opladen werkt niet bij 1000 switches. Het script en de pagina genereren enkel rijen met een waarde.

## Te testen in de lab voor de eerste echte golf

| # | Vraag | Waarom |
|---|---|---|
| 1 | Aanvaardt de upload een dun bestand (enkel de rijen die je zet)? | Daar is alles op gebouwd |
| 2 | ~~Wist een lege waarde een bestaande waarde?~~ | Verwijderen kan niet via de bulk-upload. Opkuisen via `cnx api opkuisen` |
| 3 | ~~Moet `Modified` op `Yes` staan?~~ | **Ja, vastgesteld op 12 november 2026.** Met `No` meldt de upload succes maar wordt niets toegepast. Standaard nu `Yes` |
| 4 | Werken ingevulde site-kolommen en `x` allebei bij device-scope? | Standaard ingevuld, `--x-voor-hierarchie` zet `x` |
| 5 | ~~Maakt de upload een eigen alias aan?~~ | **Nee.** Enkel bestaande aliassen worden bijgewerkt |
| 6 | Maximum aantal rijen per upload? | Stel `--max-rijen` bij |
| 7 | Kan een waarde klaargezet worden voor een toestel dat nog niet geonboard is? | Bepaalt of de upload voor of na de onboarding gebeurt |

Test 1 en 2 samen: genereer een bestand met enkel de hostname van de labswitch, upload, en kijk of de system VLAN IP blijft staan.

## Switches en Overzicht (cnx web)

`monitor.py` gebruikt enkel deze aanvragen (referentie: developer.arubanetworks.com/new-central/reference, november 2026):

| Doel | Aanvraag |
|---|---|
| Switches, toestellen, inventaris | `GET /network-monitoring/v1/switches`, `/devices`, `/device-inventory` (limit 1000, `next` is een paginanummer) |
| Een switch | `GET /network-monitoring/v1/switches/{serial}` en `/interfaces`, `/vlans`, `/interface-poe`, `/lag`, `/vsx`, `/hardware-categories`, `/hardware-trends`, `/interface-trends`; `GET /network-monitoring/v1/stack/{serial}/members`; `GET /network-monitoring/v1/neighbours/{serial}` |
| Sites | `GET /network-monitoring/v1/sites-health`, `/sites-device-health` (offset), `/site-health/{site-id}`, `/topology/{site-id}` |
| Firmware | `GET /network-services/v1/firmware-details` (alleen lezen; er is geen API om een upgrade te starten) |
| Alerts | `GET /network-notifications/v1/alerts` (limit max 100) |
| Audit log | `GET /network-services/v1/audits` (`start-at`/`end-at` verplicht, max 90 dagen) |
| Events | `GET /network-troubleshooting/v1/events` (`context-type`, `context-identifier`, `site-id`, `start-at`, `end-at` verplicht, max 30 dagen) |
| CX-tests | `POST /network-troubleshooting/v1/cx/{serial}/ping`, `/traceroute`, `/http`, `/aaa`, `/showCommands`; resultaat via `GET .../{test}/async-operations/{task-id}`, de taak-ID is het laatste deel van `location` uit het 202-antwoord |
| Show-commando's | lijst: `GET .../cx/{serial}/show-commands` (met streepje); uitvoeren: `POST .../cx/{serial}/showCommands` (camelCase), max 20, elk `show ...` |
| Locate | `POST .../cx/{serial}/locate`, geen resultaat; 409 = knippert al |

Vastgesteld in de referentie, na te kijken tegen de echte API: `switchTrends` is in het schema een object maar in het
voorbeeld een lijst (de webapp aanvaardt beide); `keys` van de trends kan een enkele tekst met komma's zijn; topologie
`devices` en `links` zijn in het schema objecten (de webapp aanvaardt ook lijsten); de betekenis van `offset` bij de audit
log is onduidelijk, daarom haalt de webapp er maximaal 1000 op.

## Aliassen, gereedheid en snapshots (configuratie-API)

`configapi.py` leest enkel (referentie: developer.arubanetworks.com/new-central-config/reference, november 2026):

| Doel | Aanvraag |
|---|---|
| Scopes | `GET /network-config/v1/global`; `/site-collections`, `/sites`, `/device-groups` (limit max 100, offset); switches via `device-inventory` (`scopeId`) |
| Aliassen | `GET /network-config/v1alpha1/aliases` met `view-type=LIBRARY`, of `view-type=LOCAL&scope-id=…&object-type=LOCAL&device-function=…&detailed=true`; lijst onder `alias` |
| Toewijzingen | `GET /network-config/v1alpha1/config-assignments?scope-id=…` (`profile-type` = `aliases`) |
| Configuratiestatus | `GET /network-config/v1alpha1/config-health/devices` (limit/offset, lijst onder `devices`, `configStatus`); problemen per switch: `GET .../config-health/active-issue?serial=…` |
| Snapshot | per profiel `GET /network-config/v1alpha1/<profiel>?view-type=LOCAL&scope-id=…&device-function=…&effective=true` |

Een 404 van de configuratie-API op een scope betekent meestal dat daar niets ingesteld is; de toolkit telt dat als leeg.
Welke velden `detailed=true` toevoegt, staat niet in de referentie: het alias-overzicht toont ze ongewijzigd in de
kolom Annotaties. De sleutel van de ethernet-interfaces staat niet in de referentie; de snapshot neemt de enige lijst
uit het antwoord en noemt de items naar `name` of `id`.

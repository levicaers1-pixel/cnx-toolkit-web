# CNX Toolkit

Hulpmiddelen om AOS-CX access switches naar HPE Aruba Networking Central (new Central) te brengen en daar proper
te houden.

| Commando | Wat het doet |
|---|---|
| `cnx` | De webapp (ook bij dubbelklikken op `cnx.exe`): switches onboarden en overrides controleren. Zie [Webapp](#webapp) |
| `cnx web` | Hetzelfde, met opties (`--poort`, `--map`, `--geen-browser`) |
| `cnx menu` | Het menu in het venster, voor wie liever niet in de browser werkt |
| `cnx invoer` | Invulpagina in de browser: een veld per parameter, controle terwijl je typt, uploadbestanden voor Central |
| `cnx alias ...` | Hetzelfde vanaf de commandolijn, voor grote lijsten. Ook: switchlijst uit Classic omzetten, vergelijken na de upload, geimporteerde waarden analyseren |
| `cnx api ...` | Via de API van new Central: aliassen aanmaken en toewijzen, lokale waarden opkuisen, VLAN's van Global doorzetten naar aggregation en core |
| `cnx overrides` | Scherm in de browser: lokale overrides per switch bekijken en veilig wissen |
| `cnx sjablonen` | `klantconfig.json` en `toestellen-sjabloon.csv` in de huidige map zetten |
| `cnx hulp` | Deze handleiding openen |

## Webapp

Dubbelklik op `cnx.exe` (of typ `cnx`) en je browser opent een scherm met deze tabbladen:

| Tabblad | Wat |
|---|---|
| Onboarden | Device group in new Central kiezen, switches en gateways aanvinken, IP en hostname nakijken, en het importbestand (aliassen) downloaden. Zie [Onboarden](#onboarden) |
| Overrides controleren | Wat lokaal op een switch staat tegenover wat hij erft, voor profielen en aliassen, en overrides wissen. Zie [Overrides controleren](#overrides-controleren) |
| AP-migratie | Een AOS-8-inventaris van de mobility conductor inlezen en zien wat klaar is voor AOS-10: modellen, clusters, AP-groepen, wat je opkuist, en een rapport voor de klant. Zie [AP-migratie](#ap-migratie) |
| Instellingen | `klantconfig.json` invullen in een formulier, met controle. Enkel nodig voor `cnx alias`; de andere tabbladen hebben het niet nodig |
| Handleiding | Deze handleiding |

Wat de vroegere tabbladen onder Expert deden (aliasbestanden, Central API), kan nog op de commandolijn met
`cnx alias` en `cnx api`.

### Overrides controleren

- **Links** filter je de switches op device group en site, en scan je de getoonde (of aangevinkte) switches. Na de
  scan staat bij elke switch hoeveel objecten afwijkend, overbodig of alleen op die switch staan.
- **Rechts** zie je na een scan een tabel per switch met een oordeel (in orde, opkuisen, na te kijken); klik op een
  switch voor de details. Per switch: tellers, een korte samenvatting, wissen, en alles wat lokaal staat.
- Twee tabbladen: **Profielen** en **Aliassen**.
- De woorden: *afwijkend* (lokaal anders dan geerfd), *overbodig* (lokaal gelijk aan geerfd), *alleen op deze
  switch* (nergens hoger) en *per switch (normaal)* (hostname, beheer-IP: hier hoef je niets te doen).
- De aanvragen naar Central en profielen die niet gelezen konden worden, staan ingeklapt onder Technische details.

### AP-migratie

Voor de stap van AOS-8 (mobility conductor en controllers) naar AOS-10 in new Central. Leest enkel bestanden: er
wordt niets gewijzigd en je hoeft niet aan te melden.

1. Neem op de mobility conductor de uitvoer van `show ap database long` en `show switches`, elk als tekstbestand
   (of samen in een bestand). Een Excel- (.xlsx) of CSV-bestand met dezelfde kolommen kan ook.
2. Kies de bestanden in het tabblad AP-migratie en klik op Inlezen.
3. Je krijgt:
   - **Modellen**: per AP- en controllermodel of het AOS-10 ondersteunt: *klaar*, *einde nadert* (kan mee, maar de
     support stopt binnenkort), *vervangen*, *valt weg* (de conductor) of *na te kijken* (onbekend model).
   - **Clusters**: controllers die elkaars stand-by zijn (uit Standby IP van de APs). Met twee of meer migreer je in
     stappen zonder dat de getunnelde SSID's wegvallen; met een controller heb je een onderhoudsvenster of een
     tijdelijke gateway nodig. Een cluster met APs die vervangen moeten, staat als geblokkeerd.
   - **AP-groepen**: de basis voor de mapping naar sites en device groups in Central.
   - **Op te kuisen**: APs in de groep default, zonder naam (MAC als naam), down of met een dubbele naam, en
     controllers die down zijn of geen APs hebben.
   - **Rapport downloaden (HTML)**: dezelfde gegevens als rapport voor de klant, af te drukken als PDF.
4. **Migratieplan**: vink de clusters aan die je in een golf migreert en klik op Stappenplan maken. Je krijgt een
   klantbreed deel (eenmalig: GreenLake en abonnementen, AOS-10-versie, structuur en draadloze configuratie in
   Central, RADIUS-clients, bereikbaarheid, labtest) en per cluster de fasen Voorbereiden, Eerste gateway (of
   Gateway omzetten bij een cluster met een controller), APs omzetten (een stap per AP-groep), Tweede gateway en
   Afronden, met een terugvalplan en de lijst van APs.
   - Vink stappen af terwijl je werkt. De voortgang en de laatst ingelezen inventaris worden per klant bewaard in
     deze browser, niet op de server; typ de klantnaam en de toolkit laadt ze opnieuw, ook na een herstart.
   - **Exporteren** maakt een migratiebestand (`.json`) met de inventaris, de afgevinkte stappen en de gekozen
     clusters. Met **Migratiebestand laden...** werk je verder op een andere pc of geef je het plan door aan een collega.
   - **Download stappenplan (HTML)** geeft het plan met de afgevinkte stappen, voor de technieker of de klant.
   - Stappen met *nakijken* bevatten commando's die per AOS-8-versie kunnen verschillen (omzetten van controllers en
     APs): kijk ze na in de migratiegids van HPE voor je ze uitvoert.

De supportstatus per model staat in `aos10-modellen.json` in de toolkit, met de datum van de lijst. Kijk de lijst na
voor de AOS-10-versie die je gebruikt op de pagina's Supported Access Point Platforms en Supported Gateway Platforms
van HPE.

### Onboarden

Voor switches en Mobility Gateways. Drie schermen, zonder klantconfig:

1. **Toestellen kiezen.** Kies de device group en klik op Toestellen ophalen. Per switch leest de toolkit uit Central:
   hostname, site, site collection, device function, het System-info-profiel en het beheer-IP. Staat er op de
   switch al een alias `sys_vlan_ipv4_<vlan>` (switches uit Classic), dan komen IP, prefix en VLAN daaruit; anders
   het IP uit de monitoring met de prefix die je opgeeft, en het beheer-VLAN dat op Global staat. Vink aan welke
   toestellen je wil.
   - **Gateways** in dezelfde device group komen mee, met Device Function *Mobility Gateway* in het importbestand.
     Hun beheer-IP komt enkel uit de alias `sys_vlan_ipv4_<vlan>` op de gateway: het IP in de monitoring is meestal
     dat van de uplink (bv. DHCP op VLAN 4094) en wordt niet gebruikt. Staat er nog geen alias, vul dan het beheer-IP
     in (bv. het IP van de controller in AOS-8). Andere aliassen van de gateway, zoals `sys_vlan_ipv4_4094`, blijven
     ongemoeid.
2. **Nakijken.** Een tabel met per switch hostname, device function, IP, VLAN en profiel, allemaal aan te passen,
   ook voor alle switches tegelijk. Fouten (ongeldig of dubbel IP, ongeldig VLAN) kleuren meteen rood; zolang er
   fouten zijn, kan je niet verder. Een lege of ongeldige hostname is geen fout: dan gaat enkel het IP mee.
3. **Bestand.** Een voorbeeld van het importbestand zoals Central het krijgt, met de knop Download. Laad het op via
   Configuration > Library > Named Objects > Aliases > Bulk upload. Een kopie staat in `cnx-web/onboarding` (niet met `--zonder-opslag`).

- De webapp draait enkel op je eigen computer (`127.0.0.1`), niet op internet. Sluit het zwarte venster om te stoppen.
- `cnx web --zonder-opslag`: de webapp schrijft niets op schijf. Importbestanden en logboeken krijg je enkel als
  download, en het tabblad Instellingen (klantconfig) is er niet.
- `cnx web --server --host-naam cnx.voorbeeld.be`: servermodus achter een reverse proxy (HTTPS), voor meerdere
  gebruikers. Elke browser krijgt een eigen sessie en meldt zelf aan bij Central; er wordt niets op schijf bewaard.
  Poort: `--poort` of de omgevingsvariabele `PORT` (standaard 8080). Zie [docs/WEBAPP.md](docs/WEBAPP.md).
- Overrides wissen gebeurt altijd in twee stappen: eerst een plan dat je ziet, dan pas uitvoeren.
- Aanmelden kan in het scherm of met de omgevingsvariabelen hieronder. Het client secret blijft enkel in het geheugen.
  Een token van Central verloopt na een tijd; de toolkit meldt dan zelf opnieuw aan en probeert de aanvraag nog
  een keer (je ziet "401: token verlopen, opnieuw aanmelden" in de uitvoer).

## Overrides in detail

Per switch leest de toolkit alles wat lokaal op de switch staat (VLAN's, SVI's, systeem, DNS, NTP, logging, SNMP,
poort- en interfaceprofielen, beheer, AAA, STP, LLDP, VSF, firmwarebeleid en aliassen) en vergelijkt het per veld met wat
de switch zou erven van de dichtstbijzijnde hogere scope die het object heeft: device group, dan site, site collection,
Global.

| Status | Betekenis |
|---|---|
| verschilt | Lokaal anders dan geerfd; per veld zie je beide waarden |
| gelijk | Lokaal gelijk aan geerfd: overbodig, kan weg zonder dat er iets verandert |
| enkel lokaal | Staat nergens hoger; wissen haalt het van de switch |
| per switch | Hoort per switch te verschillen (hostname, beheer-IP) |

Kies links een switch, of scan alle (of de aangevinkte) switches. Alles is te exporteren naar CSV.

**Overrides wissen.** Kies welke statussen je wil zien en vink aan wat weg mag:

| Status | Na het wissen |
|---|---|
| gelijk | De switch erft dezelfde waarde: er verandert niets. Standaard aangevinkt |
| verschilt | De switch neemt de waarde over die hij van hoger erft: de werking verandert |
| enkel lokaal | Het object verdwijnt van de switch: het staat nergens hoger |

Maak een plan: de toolkit kijkt in Central opnieuw na of elk object nog dezelfde status heeft; wat ondertussen
veranderd is, valt eruit. Het plan toont per object het gevolg. Zitten er objecten in die de switch veranderen, dan
typ je WISSEN om te bevestigen. Een object dat nog gebruikt wordt (bv. een VLAN op een poort) weigert Central; dat staat
als "in gebruik, niet gewist" in het resultaat. Na het wissen kijkt de toolkit na dat het object weg is. Systeeminfo, beheerinterface, lokaal beheer en het
firmwarebeleid worden nooit gewist. Alles komt in `cnx-web/overrides-wissen-log-<tijd>.json`; met **Logboek downloaden** krijg je het ook als bestand.
Het vroegere wisscherm voor VLAN's blijft beschikbaar met `cnx overrides`.

## Vereisten

- Windows 10 of 11. Geen Python nodig.
- Voor `cnx api` en `cnx overrides`: een API-client in HPE GreenLake (Manage Workspace, Personal API clients) met
  toegang tot new Central. Gebruik bij voorkeur een aparte client voor deze tool, met enkel de rechten die nodig zijn,
  en trek hem in na de migratie.
- `cnx invoer` en `cnx alias` werken zonder API en zonder internet.

## Installeren

1. Pak de zip uit in een map, bijvoorbeeld `C:\Tools\CNX Toolkit`.
2. Open PowerShell in die map (in Verkenner: rechtsklik met Shift, "PowerShell-venster hier openen").
3. Toont Windows bij de eerste start "Windows heeft uw pc beschermd": klik op "Meer info" en dan "Toch uitvoeren".
   Dat gebeurt bij elke niet-ondertekende `.exe`.

Controle: `.\cnx.exe --version`

## Eerste keer per klant

```powershell
.\cnx.exe sjablonen
```

Het makkelijkst: open het tabblad Instellingen in de webapp, vul de velden in en sla op. Het formulier controleert de
waarden en kan ze voorstellen uit een bulk-download van de klant. Het bewaart `klantconfig.json` in de map waar je
cnx startte (de vorige versie blijft als `klantconfig.json.bak`).

Zonder webapp: vul `klantconfig.json` zelf in. Alles met `VUL-IN` moet weg:

| Veld | Betekenis |
|---|---|
| `klant` | Naam van de klant, enkel ter info |
| `velden.hostname.instance` | Naam van het gedeelde System-info-profiel in new Central waar de hostname van nieuwe switches in komt. Optioneel: leeg, dan gaat enkel het IP mee (behalve voor switches met een eigen systeemprofiel) |
| `velden.sys_vlan_ip.standaard_vlan` | Beheer-VLAN. Central noemt de alias van het beheer-IP `sys_vlan_ipv4_<vlan>` |
| `velden.mgmt_ip.instance` | Naam van de beheerinterface (OOBM), meestal `mgmt` |
| `modified` | Laat op `Yes`: Central past enkel rijen met `Yes` toe |

`cnx alias` en `cnx overrides` gebruiken `klantconfig.json` uit de map waar je ze start. In `cnx invoer` sleep je
het bestand naar het tabblad Export.

## API-gegevens

Per PowerShell-venster:

```powershell
$env:CNX_BASE_URL      = "https://de1.api.central.arubanetworks.com"
$env:CNX_CLIENT_ID     = "..."
$env:CNX_CLIENT_SECRET = "..."
```

Gebruik de API-URL van de eigen cluster. `cnx overrides` vraagt de gegevens ook zelf in het scherm. De tool schrijft
de gegevens nergens weg.

## Werkwijzen

### 1. Toestelwaarden per golf (hostname, beheer-IP)

De bulk-upload van Central werkt enkel voor switches die al in new Central staan, met site, device group en device
function Access Switch. Zet de waarden dus na de verhuis of onboarding van een golf.

```powershell
.\cnx.exe alias uit-classic-lijst --lijst export_switch_list.csv --prefix 24 --site-collection Belgium --out toestellen.csv
.\cnx.exe alias controleer --toestellen toestellen.csv
.\cnx.exe alias genereer --toestellen toestellen.csv --out uploads
```

Upload elk bestand in `uploads` in new Central: Configuration, Library, Named Objects, Aliases, bulk upload.
Controle: bulk-download ophalen en vergelijken.

```powershell
.\cnx.exe alias vergelijk --toestellen toestellen.csv --download bulk_alias_download_....csv
```

De switchlijst uit Classic exporteer je in Classic Central via Devices, Switches, export. Liever een scherm dan een
CSV: `.\cnx.exe invoer`.

### 2. Geimporteerde VLAN-beschrijvingen naar de library

Een switch die uit Classic verhuist, krijgt zijn VLAN-beschrijvingen als lokale aliassen. Daardoor geldt een
wijziging op Global niet voor die switch.

```powershell
.\cnx.exe alias globaliseer --download bulk_alias_download_....csv --out globaal
.\cnx.exe api aanmaken --waarden globaal\2-global-waarden.csv --library --apply
.\cnx.exe api toewijzen --waarden globaal\2-global-waarden.csv --apply
.\cnx.exe api opkuisen --lijst globaal\3-opkuis-per-switch.csv --serial <SERIAL> --apply
```

Eerst zonder `--apply` (proefrun), en eerst met een switch.

Elke alias die de toolkit via de API aanmaakt, krijgt als beschrijving (description) "Alias aangemaakt via CNX API
Tool". Zo zie je in Central welke aliassen van de toolkit komen. De bulk-uploadbestanden hebben geen kolom voor de
beschrijving: aliassen uit een upload via de UI krijgen ze dus niet.

### 3. VLAN's van Global ook naar aggregation en core

```powershell
.\cnx.exe api vlans-doorzetten
.\cnx.exe api vlans-doorzetten --apply
```

Kijk in de proefrun welke VLAN's en welke switches geraakt worden. Bewaar het logboek: daarmee draai je het terug
(`vlans-terugdraaien --log ...`).

### 4. Lokale overrides wissen

```powershell
.\cnx.exe overrides
```

Per switch staat bij elke override wat er na het wissen gebeurt. Enkel overrides met een vervanging op Global, site
of device group worden aangevinkt. VLAN 1 en het beheer-VLAN zijn beschermd. Standaard een proefrun: vink
"Echt uitvoeren" aan om te wissen.

## Veiligheid

- Alles wat iets wijzigt in Central is standaard een proefrun. Enkel `--apply` of "Echt uitvoeren" schrijft.
- Elke run die iets schrijft, laat een logboek (`.json`) achter in de werkmap, met het versienummer van de tool.
- Na een wijziging leest de tool terug en meldt verschillen.
- Een alias of VLAN waarnaar iets verwijst, weigert Central te verwijderen. De tool meldt dat als "in gebruik".

## Beperkingen

- AOS-CX switches. Standaard access; met de kolom `device_function` in toestellen.csv (Access Switch, Aggregation
  Switch of Core Switch) krijgen de rijen van het aliasbestand de device function van die switch. Uit een device group
  in new Central wordt ze overgenomen.
- De bulk-upload van Central werkt enkel bestaande aliassen bij: aanmaken of verwijderen kan niet, en VSF-stacks
  worden niet ondersteund. Stacks komen in `manueel-stacks.csv`.
- De configuratie-API van new Central is v1alpha1: paden en velden kunnen wijzigen. Test een nieuwe versie van
  Central eerst met een proefrun.
- Gebruik op eigen verantwoordelijkheid. Zie LICENSE (Apache-2.0).

## Ondersteuning

Vermeld bij een vraag het versienummer (`cnx --version`) en stuur het logboek van de run mee.

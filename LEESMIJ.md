# CNX Toolkit

Hulpmiddelen om netwerktoestellen naar HPE Aruba Networking Central (new Central) te brengen en daar proper te
houden: AOS-CX switches en Mobility Gateways onboarden, lokale overrides opkuisen, en de stap van AOS-8 naar AOS-10
voor access points plannen. Gratis open-source software, niet gemaakt of ondersteund door HPE.

*English: see [MANUAL.md](MANUAL.md), or switch to EN at the top of the app.*

## Drie manieren om de toolkit te gebruiken

| Manier | Voor wie | Hoe |
|---|---|---|
| Gehoste webapp | Wie niets wil installeren | Open [cnx.caersultancy.com](https://cnx.caersultancy.com). Zie [Gehoste versie](#gehoste-versie) |
| `cnx.exe` op Windows | Wie lokaal werkt, ook met de commandolijn | Pak de zip uit en dubbelklik op `cnx.exe`. Zie [Installeren](#installeren) |
| Container | Wie zelf host | `docker run` met het image van GHCR. Zie [docs/AZURE.md](docs/AZURE.md) en de README |

De webapp is overal dezelfde. Rechtsboven kies je de taal (**NL** of **EN**); de keuze wordt onthouden in je browser.

## Webapp

| Tabblad | Wat |
|---|---|
| Onboarden | Device group in new Central kiezen, switches en gateways aanvinken, IP en hostname nakijken, en het importbestand (aliassen) downloaden. Zie [Onboarden](#onboarden) |
| Overrides controleren | Wat lokaal op een switch staat tegenover wat hij erft, voor profielen en aliassen, en overrides wissen. Zie [Overrides controleren](#overrides-controleren) |
| GreenLake Onboarding | Nieuwe toestellen in GreenLake zetten, aan Central en een subscription toewijzen, en in Central aan site, device group en device function. Zie [GreenLake Onboarding](#greenlake-onboarding) |
| Voor/na-controle | De stand van het netwerk vastleggen voor en na een change, en zien wat er wegviel. Zie [Voor/na-controle](#voorna-controle) |
| AP-migratie | Een AOS-8-inventaris van de mobility conductor inlezen en zien wat klaar is voor AOS-10, met een rapport en een migratieplan per cluster, en na de migratie de APs in Central hernoemen en toewijzen. Zie [AP-migratie](#ap-migratie) |
| Instellingen | Enkel in de lokale app: `klantconfig.json` invullen voor `cnx alias` op de commandolijn |
| Handleiding | Deze handleiding |

**Aanmelden.** Klik rechtsboven op Aanmelden en geef de API-URL van je new Central (bv.
`https://de1.api.central.arubanetworks.com`, te vinden in Central onder Menu > API Gateway > REST API), een client-ID
en een secret. Er zijn twee soorten API-clients, allebei aan te maken in GreenLake (Identity & access management > API
access):

- een client voor **je Central-instantie**: laat de workspace-ID leeg. Werkt voor alle tabbladen behalve GreenLake
  Onboarding (daar meld je dan apart aan);
- een client voor **HPE GreenLake Platform**: vul ook de **workspace-ID** in. Met die ene client meldt de toolkit aan
  bij Central en bij GreenLake (elk met een eigen token, dat hij zelf vernieuwt), en werken alle tabbladen.

Client-ID en secret blijven enkel in het geheugen van de toolkit, voor je sessie, en worden nergens bewaard. Voor
AP-migratie en het vergelijken van snapshots hoef je niet aan te melden.

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
     in (bv. het IP van de controller in AOS-8). Andere aliassen van de gateway blijven ongemoeid.
2. **Nakijken.** Een tabel met per toestel hostname, device function, IP, VLAN en System-info-profiel, allemaal aan te
   passen, ook voor alle toestellen tegelijk. Fouten (ongeldig of dubbel IP, ongeldig VLAN) kleuren meteen rood;
   zolang er fouten zijn, kan je niet verder. Een lege of ongeldige hostname is geen fout: dan gaat enkel het IP mee.
   Een leeg System-info-profiel valt op; kies het profiel dat het toestel in Central heeft.
3. **Bestand.** Een voorbeeld van het importbestand zoals Central het krijgt, met de knop Download. Laad het op via
   Configuration > Library > Named Objects > Aliases > Bulk upload, en kijk daarna een toestel na. In de lokale app
   staat ook een kopie in `cnx-web/onboarding`.

### Overrides controleren

- **Links** filter je de switches op device group en site, en scan je de getoonde (of aangevinkte) switches. Na de
  scan staat bij elke switch hoeveel objecten afwijkend, overbodig of alleen op die switch staan.
- **Rechts** zie je na een scan een tabel per switch met een oordeel (in orde, opkuisen, na te kijken); klik op een
  switch voor de details: tellers, een korte samenvatting, wissen, en alles wat lokaal staat.
- Twee tabbladen: **Profielen** en **Aliassen**. Alles is te exporteren naar CSV.
- De aanvragen naar Central en profielen die niet gelezen konden worden, staan ingeklapt onder Technische details.

De toolkit leest alles wat lokaal op de switch staat (VLAN's, SVI's, systeem, DNS, NTP, logging, SNMP, poort- en
interfaceprofielen, beheer, AAA, STP, LLDP, VSF, firmwarebeleid en aliassen) en vergelijkt het per veld met wat de
switch erft van de dichtstbijzijnde hogere scope die het object heeft: device group, dan site, site collection, Global.

| Woord | Betekenis | Na het wissen |
|---|---|---|
| afwijkend | Lokaal anders dan geerfd; per veld zie je beide waarden | De switch neemt de waarde over die hij van hoger erft: de werking verandert |
| overbodig | Lokaal gelijk aan geerfd | De switch erft dezelfde waarde: er verandert niets |
| alleen op deze switch | Staat nergens hoger | Het object verdwijnt van de switch |
| per switch (normaal) | Hoort per switch te verschillen (hostname, beheer-IP) | Wordt nooit gewist |

**Overrides wissen** gebeurt altijd in twee stappen. Vink aan wat weg mag en klik op Plan maken: de toolkit kijkt in
Central opnieuw na of elk object nog dezelfde status heeft (wat ondertussen veranderd is, valt eruit) en toont per
object het gevolg. Pas met **Echt wissen** wordt er gewist. Zitten er objecten in die de switch veranderen, dan typ je
ter bevestiging WISSEN (in het Engels: DELETE). Een object dat nog gebruikt wordt (bv. een VLAN op een poort) weigert
Central; dat staat als "in gebruik, niet gewist" in het resultaat. Na het wissen kijkt de toolkit na dat het object weg
is. Systeeminfo, beheerinterface, lokaal beheer en het firmwarebeleid worden nooit gewist. Met **Logboek downloaden**
bewaar je wat er gebeurd is; de lokale app zet het ook in `cnx-web/overrides-wissen-log-<tijd>.json`.

### GreenLake Onboarding

Nieuwe toestellen in een keer klaarzetten. Dat zijn aparte stappen met wachttijd ertussen, via twee API's; de toolkit
doet ze na elkaar:

1. toevoegen aan de inventaris van GreenLake (serienummer en MAC);
2. toewijzen aan new Central in een regio;
3. een subscription toewijzen;
4. wachten tot het toestel in Central staat (hoogstens tien minuten);
5. in Central toewijzen aan een site, device group en device function, en daarna nakijken.

**Aanmelden.** Het eenvoudigst: meld rechtsboven aan met een API-client voor HPE GreenLake Platform en je
workspace-ID (zie [Webapp](#webapp)); dan staat er "aangemeld bij GreenLake (via je aanmelding rechtsboven)". Met een
client voor je Central-instantie meld je in het tabblad apart aan met een GreenLake-platform-client; lukt dat niet,
vul dan ook de workspace-ID in. Voor stap 4 en 5 is de aanmelding bij Central nodig. Afmelden rechtsboven meldt ook af
bij GreenLake.

**Werkwijze.**

- Plak een tabel uit Excel of kies een CSV- of xlsx-bestand. Verplicht: *serial* en *mac*. Verder: *soort* (AP,
  switch of gateway), *site*, *device group*, *device function* (Access Switch, Aggregation Switch, Core Switch,
  Mobility Gateway...) en eventueel *subscription* (een key per toestel). **Voorbeeld (CSV)** geeft een sjabloon. Rijen
  met fouten (ongeldig serienummer of MAC, dubbel, onbekende functie) gaan niet mee.
- Kies de applicatie en regio (Central) en per soort een subscription; je ziet hoeveel er nog vrij zijn.
- **Plan maken (wijzigt niets)** zoekt elk toestel in GreenLake en Central. Een toestel dat al in GreenLake staat,
  wordt niet opnieuw toegevoegd; een toestel met een applicatie of subscription houdt die. Het plan weigert een ander
  MAC-adres dan in GreenLake, een toestel dat al aan een andere applicatie hangt, een site of device group die niet
  bestaat, en te weinig vrije licenties.
- **Proef** (standaard aan): GreenLake doet een dry-run en wijzigt niets; Central wordt overgeslagen. Haal het vinkje
  weg om echt uit te voeren; je typt dan ter bevestiging ONBOARDEN.
- Het resultaat toont per toestel en per stap ok of de fout, met **Logboek downloaden**.

**Te weten.**

- Een toestel dat al online kwam voor het een site en device group had, landt in de default-groep. Onboard toestellen
  voor je ze aansluit.
- Toewijzen aan een site of device group werkt volgens HPE enkel in een account met alleen new Central, niet samen
  met Classic. APs krijgen hun device function vanzelf; bij een VSF-stack wijs je enkel de conductor toe.
- Gebaseerd op de API-referenties van HPE, maar nog niet getest tegen een echte GreenLake. Begin met een proef en een
  paar toestellen. Wat nog te bevestigen is: welk id GreenLake verwacht om aan Central toe te wijzen (de toolkit stuurt
  het id van de service manager met de regio) en hoe GreenLake het resultaat per toestel teruggeeft.
- De lijst met toestellen blijft enkel in de pagina; herladen wist ze.

### Voor/na-controle

Leg voor een change, een firmware-upgrade of een migratie de stand van het netwerk vast, en daarna nog eens. Leest
enkel uit Central; er wordt niets gewijzigd.

1. Geef de snapshot een naam (bv. *voor change 1234*), kies eventueel een site en klik op **Snapshot nemen**. De
   toolkit leest per toestel de status en de firmware, per switchpoort de status en de buur, en het aantal clients per
   SSID en per AP. Namen en adressen van clients bewaart hij niet, enkel de aantallen. Zonder site leest hij hoogstens
   300 switches poort per poort.
2. Neem na de wijziging een tweede snapshot.
3. Kies in **Bewaarde snapshots** welke van voor en welke van na is en klik op **Vergelijken**. Je ziet:
   - *weg of down*: toestellen die offline gingen of uit Central verdwenen, poorten die up waren en nu down zijn, en
     SSID's waar alle clients weg zijn;
   - *nakijken*: poorten met een andere of geen buur meer, een lagere snelheid, SSID's met minstens 20 % minder clients
     en APs die hun clients kwijt zijn (vanaf 5 clients);
   - *hersteld* en *gewijzigd*: toestellen die terug online zijn, nieuwe firmware, een andere naam of site.
   - Met **Exporteer CSV** neem je het resultaat mee in een changeverslag.

De snapshots staan enkel in deze browser (de laatste tien), nooit op de server. **Exporteren** maakt er een
`.json`-bestand van, om door te geven of te bewaren; met **Snapshot laden...** lees je er een terug in. Vergelijken kan
zonder aanmelden. Op een gedeelde pc klik je op **Vergeten** als je klaar bent.

### AP-migratie

Voor de stap van AOS-8 (mobility conductor en controllers) naar AOS-10 in new Central. De gereedheid en het plan lezen
enkel bestanden: er wordt niets gewijzigd en je hoeft niet aan te melden. Alleen de afwerking na de migratie (stap 5)
schrijft naar Central.

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
   - Vink stappen af terwijl je werkt. De inventaris en de afgevinkte stappen worden per klant bewaard in deze
     browser, nooit op de server; typ de klantnaam en de toolkit laadt ze opnieuw.
   - **Exporteren** maakt een migratiebestand (`.json`) met de inventaris, de afgevinkte stappen en de gekozen
     clusters. Met **Migratiebestand laden...** werk je verder op een andere pc of geef je het plan door.
   - **Vergeten** wist de inventaris, de afgevinkte stappen en de gekozen clusters van deze klant uit de browser. Doe
     dat op een gedeelde pc als je klaar bent; exporteer eerst als je ze nog nodig hebt.
   - **Download stappenplan (HTML)** geeft het plan met de afgevinkte stappen, voor de technieker of de klant.
   - Stappen met *nakijken* bevatten commando's die per AOS-8-versie kunnen verschillen (omzetten van controllers en
     APs): kijk ze na in de migratiegids van HPE voor je ze uitvoert.
   - Het rapport en het plan komen in de taal die je rechtsboven gekozen hebt.
5. **Na de migratie: APs afwerken in Central** (aanmelden nodig). Zodra de APs in new Central staan, zoekt de toolkit
   elke AP uit de inventaris op serienummer of MAC.
   - Kies per AP-groep de site en de device group in Central, of laat *(niet wijzigen)* staan. De keuze wordt per klant
     in deze browser bewaard.
   - Laat **APs hernoemen naar hun naam uit AOS 8** aangevinkt om ze hun oude naam terug te geven.
   - **Plan maken (wijzigt niets)** toont per AP de naam, site en device group nu en straks, welke APs niet gevonden
     zijn en wat niet kan (een naam met een spatie, een naam die twee keer voorkomt of al aan een andere AP hangt, een
     site die niet bestaat).
   - **Uitvoeren** wijst eerst de sites en device groups toe (per 50 APs) en zet daarna de hostname in het
     System-info-profiel van elke AP, en kijkt na dat hij er staat. Met **Logboek downloaden** bewaar je wat er
     gebeurd is. **Hernoemlijst (CSV)** geeft de lijst `serial,new_hostname` voor HPE's eigen workflow.
   - Toewijzen aan een site of device group werkt volgens HPE enkel in een account met alleen new Central, niet samen
     met Classic. Het hernoemen volgt HPE's workflow *Rename Hostnames*. Probeer het eerst op een paar APs.

De supportstatus per model staat in `aos10-modellen.json` in de toolkit, met de datum van de lijst. Kijk ze na voor
de AOS-10-versie die je gebruikt op de pagina's Supported Access Point Platforms en Supported Gateway Platforms van HPE.

## Gehoste versie

De webapp kan ook op een server draaien, voor meerdere gebruikers (`cnx web --server`, of het container-image). Het
publieke exemplaar staat op **[cnx.caersultancy.com](https://cnx.caersultancy.com)**; tijdens de pilot vraagt het een
pilotcode.

- Elke browser krijgt een eigen sessie en meldt zelf aan bij de eigen Central. De server bewaart niets: geen
  database, niets op schijf. Na 30 minuten zonder activiteit, of bij afmelden, zijn de sessie en het secret weg.
- Tijdens een pilot kan de beheerder een **pilotcode** instellen: dan vraagt de app eerst die code.
- Het tabblad Instellingen bestaat niet in de gehoste versie; importbestanden en logboeken krijg je als download.
- Hosten op Azure (gratis binnen het maandelijkse tegoed): zie [docs/AZURE.md](docs/AZURE.md). Technische details van
  de servermodus: [docs/WEBAPP.md](docs/WEBAPP.md).

## Installeren

Voor de lokale app op Windows (10 of 11, geen Python nodig):

1. Pak de zip uit in een map, bijvoorbeeld `C:\Tools\CNX Toolkit`.
2. Dubbelklik op `cnx.exe`: je browser opent de webapp op `http://127.0.0.1:8766`. Sluit het zwarte venster om te
   stoppen.
3. Toont Windows bij de eerste start "Windows heeft uw pc beschermd": klik op "Meer info" en dan "Toch uitvoeren".
   Dat gebeurt bij elke niet-ondertekende `.exe`.

Controle: open PowerShell in die map en typ `.\cnx.exe --version`.

| Commando | Wat het doet |
|---|---|
| `cnx` | De webapp (ook bij dubbelklikken op `cnx.exe`) |
| `cnx web` | Hetzelfde, met opties: `--poort`, `--map` (werkmap), `--geen-browser`, `--zonder-opslag` (niets op schijf), `--server` (servermodus, met `--host-naam` en `--adres`) |
| `cnx menu` | Een menu in het venster |
| `cnx alias ...` | Uploadbestanden maken en controleren vanaf de commandolijn, voor grote lijsten. Ook: switchlijst uit Classic omzetten, vergelijken na de upload, geimporteerde waarden analyseren |
| `cnx api ...` | Via de API van new Central: aliassen aanmaken en toewijzen, lokale waarden opkuisen, VLAN's van Global doorzetten naar aggregation en core |
| `cnx sjablonen` | `klantconfig.json` en `toestellen-sjabloon.csv` in de huidige map zetten |
| `cnx hulp` | Deze handleiding openen |

## Vereisten

- Een API-client in HPE GreenLake (Manage Workspace, Personal API clients) met toegang tot new Central, voor
  Onboarden, Overrides controleren en `cnx api`. Gebruik bij voorkeur een aparte client voor deze tool, met enkel de
  rechten die nodig zijn, en trek hem in na de migratie.
- AP-migratie en `cnx alias` werken zonder API.

## Commandolijn

### Klantconfig

`cnx alias` gebruikt `klantconfig.json` uit de map waar je het start. Maak er een met `.\cnx.exe sjablonen` en vul
het in, of gebruik het tabblad Instellingen van de lokale app (met controle, en een voorstel uit een bulk-download).
Alles met `VUL-IN` moet weg:

| Veld | Betekenis |
|---|---|
| `klant` | Naam van de klant, enkel ter info |
| `velden.hostname.instance` | Naam van het gedeelde System-info-profiel in new Central waar de hostname van nieuwe switches in komt. Optioneel: leeg, dan gaat enkel het IP mee (behalve voor switches met een eigen systeemprofiel) |
| `velden.sys_vlan_ip.standaard_vlan` | Beheer-VLAN. Central noemt de alias van het beheer-IP `sys_vlan_ipv4_<vlan>` |
| `velden.mgmt_ip.instance` | Naam van de beheerinterface (OOBM), meestal `mgmt` |
| `modified` | Laat op `Yes`: Central past enkel rijen met `Yes` toe |

### API-gegevens

Per PowerShell-venster:

```powershell
$env:CNX_BASE_URL      = "https://de1.api.central.arubanetworks.com"
$env:CNX_CLIENT_ID     = "..."
$env:CNX_CLIENT_SECRET = "..."
```

Gebruik de API-URL van de eigen cluster. De tool schrijft de gegevens nergens weg.

### 1. Toestelwaarden per golf (hostname, beheer-IP)

De bulk-upload van Central werkt enkel voor switches die al in new Central staan, met site, device group en device
function. Zet de waarden dus na de verhuis of onboarding van een golf. Met een scherm: het tabblad Onboarden. Vanaf de
commandolijn, bv. met een switchlijst uit Classic (Devices, Switches, export):

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

### 2. Geimporteerde VLAN-beschrijvingen naar de library

Een switch die uit Classic verhuist, krijgt zijn VLAN-beschrijvingen als lokale aliassen. Daardoor geldt een
wijziging op Global niet voor die switch.

```powershell
.\cnx.exe alias globaliseer --download bulk_alias_download_....csv --out globaal
.\cnx.exe api aanmaken --waarden globaal\2-global-waarden.csv --library --apply
.\cnx.exe api toewijzen --waarden globaal\2-global-waarden.csv --apply
.\cnx.exe api opkuisen --lijst globaal\3-opkuis-per-switch.csv --serial <SERIAL> --apply
```

Eerst zonder `--apply` (proefrun), en eerst met een switch. Elke alias die de toolkit via de API aanmaakt, krijgt als
beschrijving "Alias aangemaakt via CNX API Tool". De bulk-uploadbestanden hebben geen kolom voor de beschrijving:
aliassen uit een upload via de UI krijgen ze dus niet.

### 3. VLAN's van Global ook naar aggregation en core

```powershell
.\cnx.exe api vlans-doorzetten
.\cnx.exe api vlans-doorzetten --apply
```

Kijk in de proefrun welke VLAN's en welke switches geraakt worden. Bewaar het logboek: daarmee draai je het terug
(`vlans-terugdraaien --log ...`).

## Veiligheid

- Alles wat iets wijzigt in Central, begint met een proefrun of een plan. Enkel `--apply` op de commandolijn of
  **Echt wissen** in de webapp schrijft.
- Elke wijziging laat een logboek achter (`.json`, met het versienummer van de tool): als download, en in de lokale
  app ook in de werkmap.
- Na een wijziging leest de tool terug en meldt verschillen.
- Een alias of VLAN waarnaar iets verwijst, weigert Central te verwijderen. De tool meldt dat als "in gebruik".
- Hoe de toolkit met gegevens omgaat: zie de [privacyverklaring](PRIVACY.nl.md) (ook in de app: `/privacy`) en
  [SECURITY.md](SECURITY.md).

## Beperkingen

- AOS-CX switches en Mobility Gateways (onboarden en overrides); access points enkel als analyse en plan voor de
  stap van AOS-8 naar AOS-10.
- De bulk-upload van Central werkt enkel bestaande aliassen bij: aanmaken of verwijderen kan niet, en VSF-stacks
  worden niet ondersteund. Stacks komen in `manueel-stacks.csv`.
- De configuratie-API van new Central is v1alpha1: paden en velden kunnen wijzigen. Test een nieuwe versie van
  Central eerst met een proefrun.
- De commando's in het migratieplan (stappen met *nakijken*) zijn nog niet nagekeken tegen de migratiegids van HPE.
- Gebruik op eigen verantwoordelijkheid. Zie LICENSE (Apache-2.0).

## Ondersteuning

Meld een probleem op [GitHub](https://github.com/levicaers1-pixel/cnx-toolkit-web/issues), zonder klantgegevens.
Vermeld het versienummer (`cnx --version`, of linksboven in de webapp) en voeg het logboek van de run toe. Een
beveiligingsprobleem meld je privé (zie [SECURITY.md](SECURITY.md)).

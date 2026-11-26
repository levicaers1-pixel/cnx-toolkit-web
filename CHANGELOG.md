# Changelog

Versienummers volgen MAJOR.MINOR.PATCH.

## 0.3.0 (2026-11-26)

- Nieuw tabblad **Voor/na-controle**: een snapshot van het netwerk (status en firmware per toestel, status en buur per
  switchpoort, aantal clients per SSID en per AP) voor en na een change, en een vergelijking die toont wat offline of
  down ging, wat een andere buur kreeg en waar clients wegvielen. Leest enkel; de snapshots staan in de browser, met
  exporteren en laden.
- AP-migratie: **Na de migratie: APs afwerken in Central**. De APs uit de AOS-8-inventaris worden in Central gezocht
  op serienummer of MAC, hernoemd naar hun AOS-8-naam en per AP-groep aan een site en device group toegewezen. Eerst
  een plan, dan uitvoeren, met nakijken en een logboek.
- Tabellen: de filterknoppen (zoals Aandacht) worden ook vertaald.

## 0.2.3 (2026-11-26)

- AP-migratie: knop **Vergeten** wist de inventaris, de afgevinkte stappen en de gekozen clusters van een klant uit de
  browser (na bevestiging). Uitleg erbij voor een gedeelde pc.
- Tijden in de lokale tijd van de gebruiker: de browser stuurt zijn tijd mee (kop `X-Tijd`). Het inlezen van een
  inventaris, het AOS-10-rapport, het migratieplan en de naam van het importbestand toonden in servermodus de tijd van
  de server (UTC).

## 0.2.2 (2026-11-25)

- Handleiding, README en privacyverklaring verwijzen naar het publieke exemplaar op https://cnx.caersultancy.com.
- Azure-script: `-Domein cnx.voorbeeld.be` koppelt een eigen domein met een gratis certificaat. Zonder DNS-records toont
  het welke records je moet maken (met de waarden); gekoppelde domeinen blijven bij elke update toegelaten.

## 0.2.1 (2026-11-25)

- Privacyverklaring in het Nederlands en het Engels (`PRIVACY.nl.md`, `PRIVACY.md`), ook in de app op `/privacy`, met
  een link onderaan de pagina en op de pilotpagina. Bereikbaar zonder sessie of pilotcode.
- CodeQL staat aan (Python en GitHub Actions). De eerste scan vond twee meldingen, allebei opgelost: een extra
  controle dat het importbestand in de werkmap blijft (lokale app), en een robuustere regex in een test.

## 0.2.0 (2026-11-25)

- GitHub Actions op een vaste commit-SHA (met het versienummer erbij), het basisimage op een vaste digest, en
  `.github/dependabot.yml`: Dependabot stelt elke week updates voor (actions, basisimage, pip).
- Repository: private vulnerability reporting, kwetsbaarheidsmeldingen en Dependabot-beveiligingsupdates staan aan.
- De webapp in het Engels: een knop NL/EN rechtsboven (standaard de taal van de browser, onthouden in een cookie).
  Ook meldingen en bevindingen van de server, het AOS-10-rapport, het migratieplan, de pilotpagina en de handleiding
  komen in de gekozen taal. De commandolijn blijft Nederlands.
- Handleiding nagekeken en bijgewerkt: verwijzingen naar de weggehaalde commando's `cnx invoer` en `cnx overrides`
  eruit, de gehoste versie, pilotcode en taalkeuze erbij, dezelfde woorden als in het scherm (afwijkend, overbodig,
  alleen op deze switch), en links in de handleiding in de app werken. Nieuw: `MANUAL.md` (Engels).
- Aanmeldvenster: de uitleg klopt nu ook in servermodus (de gegevens blijven in het geheugen van de toolkit, voor deze
  sessie).

## 0.1.4 (2026-11-25)

Beveiliging, na een audit:

- AP-migratie: grenzen tegen kwaadaardige Excel-bestanden. Een bestand van minder dan 1 kB kon 110 MB geheugen en
  19 seconden rekentijd kosten (en met iets meer de container laten crashen). Nu: hoogstens 20 MB uitgepakt,
  500 onderdelen, 256 kolommen, 100.000 rijen en 1 miljoen cellen, bladen worden rij per rij gelezen, een DOCTYPE
  wordt geweigerd, hoogstens 10 bestanden per inlezing.
- Servermodus: hoogstens 2 AP-migraties tegelijk op de server, uploads voor AP-migratie tot 8 MB.
- Servermodus: `X-Forwarded-For` telt enkel met `CNX_PROXY=1` (achter een proxy die de kop zelf zet, zoals Azure
  Container Apps; het script zet dit). Anders telt het adres van de verbinding. Daarnaast hoogstens 60 foute
  pilotcodes per minuut voor de hele server.
- Time-out van 60 seconden op stille verbindingen.
- Koppen: `Strict-Transport-Security` in servermodus, en een `Content-Security-Policy` met een nonce per pagina.
- Servermodus: een onverwachte fout geeft een algemene melding in plaats van de Python-fout (het type staat in de log).

## 0.1.3 (2026-11-25)

- Pilotcode voor de servermodus: met `CNX_PILOTCODE` gezet krijgt een bezoeker eerst een pagina die om de code vraagt;
  zonder juiste code blijven de app en de API dicht. Hoogstens 10 foute codes per bezoeker per kwartier, nieuw
  sessie-id na de juiste code, de code komt nooit in de logs. Het Azure-script zet ze als geheim (`-Pilot`, de code
  wordt gevraagd en niet getoond) of haalt ze weg (`-GeenPilot`).
- Azure-script: standaardregio North Europe (West Europe nam geen nieuwe klanten aan).

## 0.1.2 (2026-11-25)

- Weg: `cnx overrides` (het oude aparte wisscherm voor VLAN's) en `cnx invoer` (de oude invulpagina). Overrides wissen
  gebeurt in de webapp (Overrides controleren), het uploadbestand maak je in Onboarden of met `cnx alias`.
- Het Azure-script slaat een bestaande resourcegroep over en geeft een tip als een regio geen nieuwe klanten aanneemt.

## 0.1.1 (2026-11-25)

- Servermodus klaar voor publiek gebruik zonder login: hoogstens 20 nieuwe sessies per bezoeker per minuut (zodat
  niemand alle sessies kan opeisen), sessies die niet bij Central aangemeld zijn verdwijnen na 10 minuten, en een
  vermelding onderaan de pagina (niet van HPE, niets bewaard, gebruik op eigen risico, link naar de broncode).
- `deploy/azure-containerapps.ps1` en handleiding `docs/AZURE.md`: de toolkit gratis op Azure Container Apps zetten.

## 0.1.0 (2026-11-24)

- Start van de webversie, gebaseerd op CNX Toolkit 1.25.2: Onboarden (switches en Mobility Gateways), Overrides
  controleren, AP-migratie (AOS-8 naar AOS-10: gereedheid en migratieplan per cluster).
- Open source onder de Apache License 2.0.
- Een eigen verbinding met Central per gebruiker (voorbereiding op de servermodus). Lopende ophalingen en
  wisplannen horen bij de gebruiker die ze startte. Lokaal (`cnx web`, de exe) werkt alles zoals voorheen.
- `cnx web --zonder-opslag`: niets op schijf. Importbestanden en het logboek van overrides wissen gaan als download
  naar de browser; het tabblad Instellingen verdwijnt.
- AP-migratie: de inventaris en de afgevinkte stappen staan in de browser, niet meer in `cnx-web/migratie`. Nieuw:
  **Exporteren** en **Migratiebestand laden...** om een plan door te geven of op een andere pc verder te werken.
- Overrides wissen: knop **Logboek downloaden**.
- `cnx web --server`: servermodus voor meerdere gebruikers achter een reverse proxy. Toegelaten hostnamen
  (`--host-naam` of `CNX_HOSTS`), een sessie en CSRF-token per browser, cookie HttpOnly/Secure/SameSite=Strict, nieuw
  sessie-id na aanmelden, sessie en secret weg na 30 minuten zonder activiteit, maximaal 500 sessies en 3 lopende
  taken per sessie, uploads tot 20 MB, logs zonder parameters of gegevens, veiligheidskoppen en `/gezond` voor de
  gezondheidscheck. Aanmelden enkel bij https-adressen op `arubanetworks.com` (`CNX_CENTRAL_DOMEINEN`).
- De webapp bedient de routes van de oude overrides-app (`/api/switches`, `/api/overrides`, `/api/wissen`) niet meer.
- Container-image (`Dockerfile`): servermodus, zonder root, werkt alleen-lezen. Bij elke tag op
  `ghcr.io/levicaers1-pixel/cnx-toolkit-web`.

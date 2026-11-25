# CNX Toolkit op Azure Container Apps

Deze handleiding zet de CNX Toolkit gratis online op Azure, publiek en zonder login. Iedereen kan de pagina openen;
wie ze gebruikt, meldt enkel aan bij de eigen new Central met een eigen client-ID en secret. Het script
`deploy/azure-containerapps.ps1` doet het werk; deze handleiding legt uit wat het doet en wat je daarna regelt.

## Wat je krijgt

```
Bezoeker (browser)
   │  https://cnx-toolkit.<omgeving>.northeurope.azurecontainerapps.io  (of een eigen domein)
   ▼
Azure Container Apps  ── HTTPS en certificaat door Azure, http wordt https
   ▼
Container (ghcr.io/levicaers1-pixel/cnx-toolkit-web)
   │  cnx web --server: eigen sessie per browser, niets op schijf
   ▼
HPE new Central  ── met de client-ID en secret die de bezoeker zelf ingeeft
```

| Onderdeel | Naam (standaard) | Wat |
|---|---|---|
| Resourcegroep | `rg-cnx-toolkit` | De map waarin alles staat. Weg ermee = alles weg |
| Container Apps-omgeving | `cnx-toolkit-env` | Het netwerk en de domeinnaam. Zonder Log Analytics, dus zonder logkosten |
| Container-app | `cnx-toolkit` | 0,25 vCPU en 0,5 GB geheugen, schaalt van 0 tot 1 container |

### Kosten

Container Apps rekent per seconde dat een container draait. Elk abonnement krijgt per maand een gratis tegoed
(stand november 2026: 180.000 vCPU-seconden, 360.000 GiB-seconden en 2 miljoen aanvragen). Met 0,25 vCPU en 0,5 GB
is dat ongeveer **200 uur actief gebruik per maand gratis**. Als niemand de app gebruikt, schaalt ze naar nul en
kost ze niets. De bedragen en grenzen kunnen wijzigen: kijk ze na in de
[prijscalculator](https://azure.microsoft.com/pricing/calculator/) en zet een budgetwaarschuwing (zie verder).

Er draait nooit meer dan een container, dus ook bij veel verkeer blijven de kosten begrensd.

### Wat je moet weten

- **Inslapen.** Na enkele minuten zonder verkeer stopt de container. De eerste aanvraag daarna duurt enkele
  seconden. Een gestopte container is ook het einde van alle sessies: wie terugkomt, meldt opnieuw aan bij Central.
  De AP-migratie staat in de browser en blijft bewaard.
- **Een container.** Sessies leven in het geheugen. Zet het maximum nooit hoger dan 1, anders verliezen gebruikers
  hun sessie als ze op een andere container terechtkomen.
- **Publiek.** Iedereen met de link kan de pagina openen. Zonder geldige Central-gegevens kan je er niets mee. De app
  aanvaardt enkel Central-adressen op `arubanetworks.com`, begrenst nieuwe sessies per bezoeker, en toont onderaan
  dat ze niet van HPE is en niets bewaart.
- **Wat de server ziet.** De gegevens die gebruikers uit Central lezen of opladen, gaan door het geheugen van de
  container, maar worden nergens bewaard of gelogd. De logs bevatten enkel methode, pad, status en duur.

## Vooraf

- Een Azure-abonnement waarin je resources mag aanmaken (rol **Contributor** of **Owner** op het abonnement of op een
  resourcegroep). Een gratis Azure-account werkt ook.
- Windows met PowerShell (zit erin).
- De **Azure CLI**. Installeer ze en open daarna een **nieuw** PowerShell-venster:

```powershell
winget install -e --id Microsoft.AzureCLI
```

- Deze repository op je pc (of enkel het bestand `deploy/azure-containerapps.ps1`):

```powershell
git clone https://github.com/levicaers1-pixel/cnx-toolkit-web.git
```

## Installeren

1. Open PowerShell in de map van de repository.
2. Probeer eerst een proefrun: die toont de commando's en maakt niets aan.

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\azure-containerapps.ps1 -Proef
```

3. Voer het script echt uit. Ben je nog niet aangemeld bij Azure, dan opent er een browservenster.

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\azure-containerapps.ps1
```

   Heb je meer dan een abonnement, geef dan aan welk: `-Abonnement "<naam of id>"`.

4. Na een paar minuten toont het script: `Klaar. De CNX Toolkit staat op: https://cnx-toolkit....azurecontainerapps.io`.

Wat het script doet, in volgorde:

| Stap | Commando |
|---|---|
| Aanmelden en abonnement tonen | `az login`, `az account show` |
| Uitbreiding en provider | `az extension add --name containerapp`, `az provider register --namespace Microsoft.App` |
| Resourcegroep | `az group create` |
| Omgeving (enkel de eerste keer) | `az containerapp env create --logs-destination none` |
| App aanmaken of bijwerken | `az containerapp create` of `az containerapp update` met `--min-replicas 0 --max-replicas 1` |
| Nakijken | `https://.../gezond` moet `{"ok": true}` geven |

Het script zet ook de omgevingsvariabele `CNX_HOSTS` op het adres van de app: andere hostnamen worden geweigerd.

## Nakijken

1. Open de URL. Je ziet de toolkit, met onderaan de vermelding "niet gemaakt of ondersteund door HPE".
2. Klik **Aanmelden** en vul de API-URL van new Central in (bv. `https://de1.api.central.arubanetworks.com`), met een
   client-ID en secret. Gebruik een API-client met enkel de rechten die je nodig hebt.
3. Probeer **Onboarden** met een device group, en **AP-migratie** met een inventaris.

## Pilotcode (besloten toegang)

Tijdens een pilot kan je de app afschermen met een code. Bezoekers krijgen dan eerst een pagina die erom vraagt;
zonder de juiste code zien ze niets van de toolkit. De code staat als geheim in Azure, nooit in de repository.

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\azure-containerapps.ps1 -Pilot
```

Het script vraagt de code (minstens 8 tekens) zonder ze te tonen. Opnieuw uitvoeren met `-Pilot` zet een nieuwe code;
wie al binnen was, moet na de herstart de nieuwe code geven. Weer open voor iedereen:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\azure-containerapps.ps1 -GeenPilot
```

Na 10 foute codes binnen een kwartier weigert de app die bezoeker een kwartier lang.

## Bijwerken naar een nieuwe versie

Elke versie (tag `v*` in de repository) komt als image op GHCR. Voer het script opnieuw uit met die versie:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\azure-containerapps.ps1 -Versie 0.2.0
```

Gebruik altijd een vaste versie, niet `latest`: zolang de naam van het image niet verandert, maakt Container Apps
geen nieuwe revisie en blijft de oude versie draaien. Bij het bijwerken verdwijnen de lopende sessies.

## Logs bekijken

```powershell
az containerapp logs show --name cnx-toolkit --resource-group rg-cnx-toolkit --follow
```

Je ziet enkel regels als `24/Nov/2026 20:14:38 GET /api/status 200 1ms`. Slaapt de container, dan zie je pas iets na
de volgende aanvraag.

## Budgetwaarschuwing (aanbevolen)

In de Azure-portal: **Cost Management** > **Budgets** > **Add**. Kies de resourcegroep `rg-cnx-toolkit`, een bedrag van
bv. 5 euro per maand, en een e-mail bij 80 %. Zo hoor je het als het gratis tegoed ooit niet meer volstaat.

## Eigen domeinnaam (optioneel)

Bv. `cnx.voorbeeld.be` in plaats van `cnx-toolkit....azurecontainerapps.io`, met een gratis certificaat van Azure dat
zichzelf vernieuwt. Het publieke exemplaar draait zo op [cnx.caersultancy.com](https://cnx.caersultancy.com) (DNS bij
Cloudflare).

1. Voer het script uit met je domein. Staan de DNS-records er nog niet, dan toont het welke je moet maken (met de
   juiste waarden) en stopt het:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\azure-containerapps.ps1 -Domein cnx.voorbeeld.be
```

2. Maak die twee records bij de beheerder van je domein:

| Type | Naam | Waarde |
|---|---|---|
| CNAME | `cnx` (dus `cnx.voorbeeld.be`) | het adres van de app, `cnx-toolkit.<omgeving>.<regio>.azurecontainerapps.io` |
| TXT | `asuid.cnx` | de verificatie-ID van de omgeving (een lange reeks letters en cijfers) |

   Bij Cloudflare: zet de CNAME op **DNS only** (grijze wolk), niet op Proxied. Anders kan Azure het certificaat niet
   uitreiken.
3. Wacht een paar minuten en voer het script opnieuw uit met `-Domein`. Het koppelt het domein, vraagt het
   certificaat aan en zet het domein bij de toegelaten hostnamen. Daarna werkt ook het oude adres nog.

Bij een volgende update hoef je `-Domein` niet meer mee te geven: het script neemt gekoppelde domeinen zelf mee.

## Verwijderen

Alles weg, in een keer (vraagt geen bevestiging meer):

```powershell
az group delete --name rg-cnx-toolkit --yes
```

## Problemen oplossen

| Wat je ziet | Oorzaak en oplossing |
|---|---|
| `{"fout": "geen toegang"}` (403) | De hostnaam staat niet in `CNX_HOSTS`. Voer het script opnieuw uit; bij een nieuw eigen domein met `-Domein` |
| "Te veel gebruikers tegelijk" (503) | Het maximum aantal sessies is bereikt, of je opende de pagina meer dan 20 keer in een minuut. Wacht even |
| "Je sessie is verlopen. Herlaad de pagina." | De container sliep of werd bijgewerkt, of je was 30 minuten (10 zonder aanmelding) niet actief |
| "Geef de API-URL van new Central" bij aanmelden | Enkel `https://...arubanetworks.com` mag. Een ander domein: zet `CNX_CENTRAL_DOMEINEN` op de app |
| "The selected region is currently not accepting new customers" | Die regio neemt nu geen nieuwe abonnementen aan. Opnieuw met een andere regio: `-Regio northeurope` (of `swedencentral`, `francecentral`, `germanywestcentral`) |
| De eerste keer laden duurt lang | De container start (inslapen). Na enkele seconden werkt het |
| Het script stopt met "De Azure CLI ontbreekt" | Installeer de Azure CLI (zie Vooraf) en open een nieuw venster |

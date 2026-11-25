# Privacyverklaring

*English: [PRIVACY.md](PRIVACY.md).*

Deze verklaring beschrijft wat de webapp van de CNX Toolkit met gegevens doet. Ze geldt voor de gehoste versie
(`cnx web --server`, bijvoorbeeld op Azure) en voor de lokale app op je eigen pc. Wie een exemplaar van de toolkit
draait, is verantwoordelijk voor dat exemplaar; de toolkit zelf is zo gebouwd dat de server niets bewaart.

## Kort

- **Geen account, geen database, niets bewaard op de server.** De server houdt gegevens enkel in het geheugen, zolang
  hij ze nodig heeft, en schrijft niets op schijf.
- **Geen analytics, geen trackers, geen reclame.** De pagina laadt niets van andere sites.
- **Je Central-gegevens** (API-URL, client-ID, secret) staan enkel in het geheugen van je sessie en verdwijnen bij
  afmelden, na 30 minuten zonder activiteit, of als de server herstart.

## Wat waar verwerkt wordt

| Gegevens | Waar | Hoe lang |
|---|---|---|
| API-URL, client-ID en secret van Central, en het toegangstoken | Geheugen van de server, in je sessie | Tot je afmeldt, 30 minuten zonder activiteit, of een herstart |
| Gegevens die de toolkit uit je Central leest (toestellen, serienummers, IP-adressen, hostnames, aliassen, profielen) | Geheugen van de server, om de schermen en bestanden te maken die je vraagt | Voor de sessie; resultaten van lange taken hoogstens voor de sessie |
| Bestanden die je oplaadt (AOS-8-inventaris, CSV) | Geheugen van de server, enkel tijdens de verwerking | Enkele seconden |
| AP-migratie: inventaris, afgevinkte stappen, gekozen clusters | Je browser (local storage), per klantnaam | Tot je ze wist (browserinstellingen) |
| Voorkeuren: laatste API-URL (niet het secret), device group, site, prefix, open tabblad, filters van tabellen | Je browser (local storage) | Tot je ze wist |
| Je IP-adres | Geheugen van de server, enkel om nieuwe sessies per bezoeker (1 minuut) en foute pilotcodes (15 minuten) te begrenzen | Hoogstens 15 minuten; nooit gelogd |
| Logs | Console-uitvoer van de server: datum en tijd, methode, pad zonder parameters, statuscode en duur | Zolang het hostingplatform de console-uitvoer bijhoudt |

De logs bevatten geen IP-adressen, geen parameters (zoals device groups, serienummers of tokens) en geen inhoud.

## Cookies

| Cookie | Waarvoor | Hoe lang |
|---|---|---|
| `cnx_sessie` | Koppelt je browser aan je sessie op de server (HttpOnly, Secure, SameSite=Strict) | Tot je de browser sluit; de sessie zelf stopt na 30 minuten zonder activiteit |
| `cnx_taal` | Je taalkeuze (NL of EN) | 1 jaar |

Beide zijn strikt nodig om de app te laten werken; er zijn geen andere cookies.

## Wie gegevens krijgt

- **HPE (je eigen new Central en HPE GreenLake):** de toolkit stuurt je client-ID en secret naar de aanmeldservice van
  HPE en roept daarna, in jouw naam, de API aan van de Central die je opgaf. Die gegevens blijven in je eigen
  HPE-omgeving.
- **De hostingprovider** (voor het publieke exemplaar: Microsoft Azure Container Apps, regio North Europe) draait de
  server en het netwerk. Azure houdt technische platformcijfers bij, zoals het aantal aanvragen en het CPU-gebruik.
  Log Analytics staat niet aan.
- **Niemand anders.** De server stuurt niets naar andere partijen.

## Wat je zelf kan doen

- Meld af (rechtsboven) om je gegevens meteen van de server te halen.
- Wis de sitegegevens in je browser om de bewaarde AP-migratie en voorkeuren te verwijderen. Exporteer eerst een
  migratiebestand als je het nog nodig hebt.
- Gebruik voor de toolkit een aparte API-client van Central, met enkel de rechten die nodig zijn, en trek hem in als
  je klaar bent. De server bewaart het secret nooit, maar wie een exemplaar draait, kan in principe het geheugen van
  de eigen server lezen. Gebruik enkel een exemplaar dat je vertrouwt, of draai de toolkit zelf.

## Vragen

Stel een vraag of meld een probleem op [GitHub](https://github.com/levicaers1-pixel/cnx-toolkit-web/issues) (zonder
klantgegevens). Een beveiligingsprobleem meld je privé: zie [SECURITY.md](SECURITY.md).

*Laatst bijgewerkt: 25 november 2026. Deze verklaring beschrijft hoe de software werkt; ze is geen juridisch advies.*

# Plan: van lokale app naar webapp

Doel: collega's gebruiken de toolkit via een URL, zonder installatie, en de server bewaart geen klantgegevens.
Na elke fase blijft de lokale app (`cnx web`) werken.

## Fase 1: elke gebruiker een eigen Central-verbinding (klaar)

Aan te zetten met `web.PER_SESSIE = True` (de vlag komt in fase 3 bij de servermodus). Sessie per browser via een
cookie `cnx_sessie`; tests in `tests/test_sessies.py`.

- `alias_api.py`: sessie, token, gegevens en URL samen in een object `Verbinding`, in plaats van de globale `S`,
  `_GEGEVENS` en `BASE`.
- De verbinding van een aanvraag via een `contextvar`, zodat `cx.api(...)` in configapi, monitor en overrides blijft
  werken. CLI en lokale app gebruiken een standaardverbinding.
- Achtergrondtaken nemen de verbinding van hun gebruiker mee (`cx.gebruik(verbinding)`).
- `ov.CACHE`, `OPHALINGEN` en `WISPLANNEN` per sessie.
- Test: twee gelijktijdige sessies op twee nep-Centrals zien elkaars data nooit.

## Fase 2: niets op schijf (`--zonder-opslag`) (klaar)

Tests in `tests/test_zonder_opslag.py`: elke schrijfpoging naar een bestand doet de test falen.

- Onboarden: importbestand rechtstreeks als download, geen kopie in `cnx-web/onboarding`.
- Overrides wissen: logboek in het antwoord, met een knop Logboek downloaden.
- AP-migratie (ook lokaal): inventaris en voortgang in de browser (localStorage, per klant), met Exporteren en
  Migratiebestand laden (JSON). De server krijgt ze bij elke aanvraag mee en bewaart niets.
- Instellingen (klantconfig, ook het voorstel uit een bulk-download): niet zonder opslag; enkel nodig voor `cnx alias`.
- De route die bestanden uit de werkmap gaf (`/api/web/bestand`) is weg.

## Fase 3: servermodus (klaar)

```bash
cnx web --server --host-naam cnx.voorbeeld.be        # luistert op 0.0.0.0, poort $PORT of 8080
```

| Instelling | Hoe |
|---|---|
| Toegelaten hostnamen | `--host-naam` (meermaals) of `CNX_HOSTS` (komma's). Verplicht; `*` schakelt de controle uit |
| Domeinen voor Central | `CNX_CENTRAL_DOMEINEN`, standaard `arubanetworks.com` (enkel https, poort 443) |
| Gezondheidscheck | `GET` of `HEAD /gezond` |

Een sessie ontstaat enkel bij het openen van de pagina; losse aanvragen zonder sessie krijgen 401. Tests in
`tests/test_server.py`.

- Luisteren achter een reverse proxy; Host-controle via een lijst van toegelaten hosts.
- Sessiecookie (HttpOnly, Secure, SameSite=Strict) en CSRF-token per sessie in plaats van een vast token.
- Sessie en secret weg na 30 minuten zonder activiteit, en bij Afmelden.
- Logs enkel technisch (route, status, duur), nooit IP's, hostnames, serials of inhoud.
- Limieten op uploadgrootte en aantal sessies.

## Fase 4: verpakking (klaar)

```bash
docker run -d -p 8080:8080 -e CNX_HOSTS=cnx.voorbeeld.be --read-only ghcr.io/levicaers1-pixel/cnx-toolkit-web:latest
```

- `Dockerfile`: Python 3.12 slim, draait als gebruiker 10001 (geen root), werkt met `--read-only`, gezondheidscheck op
  `/gezond`. Start `cnx web --server`; hostnamen via `CNX_HOSTS`, poort via `PORT`.
- `.github/workflows/docker.yml`: bouwt en test het image bij elke push (alleen-lezen, zonder root, cookie, Host-controle).
  Bij een tag `v*` komt het op GHCR als `:<versie>` en `:latest`. De eerste keer staat het pakket op GHCR privé:
  zet het in de pakketinstellingen op publiek.

## Fase 5: hosting (klaar om uit te voeren)

Publiek en zonder login op Azure Container Apps, gratis binnen het maandelijkse tegoed: script
`deploy/azure-containerapps.ps1`, handleiding [AZURE.md](AZURE.md). Elke bezoeker meldt enkel aan bij de eigen
Central. Voor publiek gebruik: nieuwe sessies per bezoeker begrensd, anonieme sessies na 10 minuten weg, vermelding
onderaan de pagina.

Nog te doen: het script uitvoeren op een echt abonnement en de app testen tegen een echte Central.

## Fase 6: afwerking open source

- Oude onderdelen weg: `cnx overrides` (aparte server) en `cnx invoer`.
- Webapp ook in het Engels (later).

# Plan: van lokale app naar webapp

Doel: collega's gebruiken de toolkit via een URL, zonder installatie, en de server bewaart geen klantgegevens.
Na elke fase blijft de lokale app (`cnx web`) werken.

## Fase 1: elke gebruiker een eigen Central-verbinding

- `alias_api.py`: sessie, token, gegevens en URL samen in een object `Verbinding`, in plaats van de globale `S`,
  `_GEGEVENS` en `BASE`.
- De verbinding van een aanvraag via een `contextvar`, zodat `cx.api(...)` in configapi, monitor en overrides blijft
  werken. CLI en lokale app gebruiken een standaardverbinding.
- Achtergrondtaken nemen de verbinding van hun gebruiker mee (`contextvars.copy_context()`).
- `ov.CACHE`, `OPHALINGEN` en `WISPLANNEN` per sessie.
- Test: twee gelijktijdige sessies op twee nep-Centrals zien elkaars data nooit.

## Fase 2: niets op schijf (`--zonder-opslag`)

- Onboarden: importbestand rechtstreeks als download, geen kopie in `cnx-web/onboarding`.
- Overrides wissen: logboek in het antwoord, met een downloadknop.
- AP-migratie: inventaris en voortgang in de browser (IndexedDB), met "Plan exporteren" en "Plan laden" (JSON).
- Voorstel: in het geheugen in plaats van een tijdelijk bestand.
- Instellingen (klantconfig): niet in servermodus; enkel nodig voor `cnx alias`.
- Test: alles werkt met een alleen-lezen bestandssysteem.

## Fase 3: servermodus

- Luisteren achter een reverse proxy; Host-controle via een lijst van toegelaten hosts.
- Sessiecookie (HttpOnly, Secure, SameSite=Strict) en CSRF-token per sessie in plaats van een vast token.
- Sessie en secret weg na 30 minuten zonder activiteit, en bij Afmelden.
- Logs enkel technisch (route, status, duur), nooit IP's, hostnames, serials of inhoud.
- Limieten op uploadgrootte en aantal sessies.

## Fase 4: verpakking

- Dockerfile (Python slim), image via GitHub Actions naar GitHub Container Registry bij elke tag.
- Zelf hosten: `docker run -p 8080:8080 ghcr.io/<eigenaar>/cnx-toolkit-web`.

## Fase 5: hosting voor collega's

- Azure App Service (Linux-container), een instantie, enkel HTTPS.
- Aanmelden via App Service Authentication (Easy Auth) met Microsoft Entra ID.
- Test op een echte Central: Onboarden, Overrides en AP-migratie geven hetzelfde als de lokale app.

## Fase 6: afwerking open source

- Oude onderdelen weg: `cnx overrides` (aparte server) en `cnx invoer`.
- Webapp ook in het Engels (later).

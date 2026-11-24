# Changelog

Versienummers volgen MAJOR.MINOR.PATCH.

## Nog niet uitgebracht

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

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

# Ontwikkeling

Voor gebruikers: zie [LEESMIJ.md](../LEESMIJ.md). Dit bestand is voor wie de toolkit bouwt of aanpast.

## Structuur

| Pad | Inhoud |
|---|---|
| `src/cnx_api/__main__.py` | Startpunt `cnx`: zonder argumenten de webapp, `cnx menu` voor het menu, en de subcommando's |
| `src/cnx_api/aliassen.py` | `cnx alias`: uploadbestanden, controle, Classic-import, vergelijken, globaliseer. Enkel standaardbibliotheek |
| `src/cnx_api/alias_api.py` | `cnx api`: API van new Central (aanmaken, toewijzen, opkuisen, VLAN's doorzetten) |
| `src/cnx_api/monitor.py` | Tabbladen Switches en Overzicht: vaste lijst van API-aanvragen (monitoring, events, audit, CX-probleemoplossing) |
| `src/cnx_api/configapi.py` | Configuratie-API lezen: alle aliassen per scope, gereedheid voor migratie, snapshots en vergelijken |
| `src/cnx_api/web.py` | `cnx web`: lokale webapp met alle functies; draait de bestaande commando's per taak in een eigen map; projecten van de assistent |
| `src/cnx_api/overrides.py` | `cnx overrides`: lokale webserver met scherm (127.0.0.1, token per sessie) |
| `src/cnx_api/data/` | Invulpagina, webapp (`web.html`), standaardconfig, sjablonen. `LEESMIJ.html` wordt gegenereerd |
| `build/` | PyInstaller-spec, startbestand, bouwhulp (`maak.py`) |
| `tests/` | Rooktests en webapp-tests zonder API (pytest) |
| `.github/workflows/release.yml` | Test, bouwt `cnx.exe` op Windows, ondertekent optioneel, maakt een release |

## Lokaal werken

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
cnx --version
```

## Een release maken

1. `__version__` in `src/cnx_api/__init__.py` verhogen en `CHANGELOG.md` aanvullen.
2. Committen, taggen en pushen: `git tag v1.0.1 && git push --tags`.
3. GitHub Actions test, bouwt `cnx.exe` op Windows en zet `CNX-Toolkit-<versie>.zip` bij de release.
   De tag moet gelijk zijn aan `__version__`, anders stopt de bouw.

Zelf bouwen op Windows:

```powershell
pip install -e ".[dev]"
python build/maak.py leesmij
python build/maak.py versie
pyinstaller --noconfirm --clean build/cnx.spec
python build/maak.py zip
```

## Ondertekenen

Zonder handtekening toont Windows SmartScreen een waarschuwing bij de eerste start, en sommige antivirusprogramma's
wantrouwen PyInstaller-bestanden. Met een code signing-certificaat (OV of EV):
zet het `.pfx` base64-gecodeerd in de secret `SIGN_PFX_BASE64` en het wachtwoord in `SIGN_PFX_PASSWORD`.
De workflow ondertekent dan automatisch.

## Regels voor wijzigingen

- Alles wat schrijft naar Central: standaard proefrun, `--apply` of "Echt uitvoeren" om te schrijven, logboek met versie.
- Geen klantgegevens in de code. Alles wat per klant verschilt, gaat in `klantconfig.json`.
- Geheimen nooit wegschrijven.
- Nieuwe vaststellingen over Central: in `docs/TECHNISCH.md`.

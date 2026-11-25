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
| `src/cnx_api/data/` | Webapp (`web.html`), modellenlijst AOS-10, standaardconfig, sjablonen. `LEESMIJ.html` wordt gegenereerd |
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

## Vertaling (NL/EN)

- **Webpagina** (`data/web.html`): elke tekst gaat door `vt()` (in `el()`, en waar tekst rechtstreeks gezet wordt). De
  Engelse versie staat in `data/en-web.json`, met de Nederlandse tekst als sleutel. Ook stukken van samengestelde zinnen
  ("5 toestellen gekozen") worden vertaald. Een zin met invulplaatsen: `t("neemt de waarde van {0} over", waarde)`.
- **Server**: `from .taal import _` en `_("Nederlandse tekst met {naam}", naam=...)`; de Engelse versie staat in
  `data/en-server.json`. De taal komt per aanvraag uit de cookie `cnx_taal` (anders Accept-Language), ook in
  achtergrondtaken. De commandolijn blijft Nederlands.
- Korte statuswaarden waar de pagina mee vergelijkt ("klaar", "gewist", "gelijk"), blijven Nederlands in de gegevens;
  de pagina vertaalt ze enkel bij het tonen.
- `tests/test_i18n.py` faalt bij een tekst zonder Engelse versie. Overzicht van wat ontbreekt:
  `python tests/i18n_web.py` en `python tests/i18n_server.py`.
- Handleiding: `LEESMIJ.md` (Nederlands) en `MANUAL.md` (Engels); `python build/maak.py leesmij` maakt de HTML voor het
  tabblad Handleiding.


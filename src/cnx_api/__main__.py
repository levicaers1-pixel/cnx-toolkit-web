"""Startpunt van CNX Toolkit: cnx.exe of python -m cnx_api.

  cnx                       de webapp (ook bij dubbelklikken op cnx.exe), zelfde als 'cnx web'
  cnx web                   alles in een scherm in de browser: invoer, aliasbestanden, API en overrides
  cnx menu                  menu in dit venster
  cnx overrides             scherm: lokale overrides per switch bekijken en wissen
  cnx invoer                invulpagina voor toestelwaarden (opent in de browser)
  cnx alias <commando>      uploadbestanden maken, controleren, vergelijken, Classic omzetten, globaliseren
  cnx api <commando>        via de API: aliassen aanmaken, toewijzen, opkuisen, VLAN's doorzetten
  cnx sjablonen             klantconfig.json en toestellen-sjabloon.csv in de huidige map zetten
  cnx hulp                  de handleiding openen
  cnx --version
"""
import os
import shutil
import sys
import tempfile
import webbrowser

from . import __version__, resource

COMMANDO_S = {
    "web": "Alles in de browser: invoer, aliasbestanden, API en overrides",
    "overrides": "Scherm: lokale overrides per switch bekijken en wissen",
    "invoer": "Invulpagina voor toestelwaarden (browser)",
    "alias": "Uploadbestanden maken, controleren, vergelijken, Classic omzetten, globaliseren",
    "api": "Via de API: aliassen aanmaken, toewijzen, opkuisen, VLAN's doorzetten",
    "sjablonen": "klantconfig.json en toestellen-sjabloon.csv in de huidige map zetten",
    "hulp": "Handleiding openen",
}


def open_bestand(naam, doelnaam=None):
    """Kopieer een meegeleverd bestand naar een tijdelijke map en open het (de .exe pakt uit in een tijdelijke map)."""
    doel = os.path.join(tempfile.gettempdir(), doelnaam or naam)
    shutil.copyfile(resource(naam), doel)
    webbrowser.open("file://" + os.path.abspath(doel).replace("\\", "/"))
    return doel


def cmd_invoer(_):
    pad = open_bestand("invoer.html", "cnx-alias-invoer.html")
    print(f"Invulpagina geopend: {pad}")
    print("Je werk blijft in de browser bewaard. Exporteer toestellen.csv om het echt te bewaren.")
    return 0


def cmd_hulp(_):
    pad = open_bestand("LEESMIJ.html", "cnx-api-leesmij.html")
    print(f"Handleiding geopend: {pad}")
    return 0


def cmd_sjablonen(_):
    for bron, doel in (("klantconfig.json", "klantconfig.json"), ("toestellen-sjabloon.csv", "toestellen-sjabloon.csv")):
        if os.path.exists(doel):
            print(f"  {doel} bestaat al, niet overschreven")
            continue
        shutil.copyfile(resource(bron), doel)
        print(f"  {doel} aangemaakt in {os.getcwd()}")
    print("Vul klantconfig.json in met de profielnamen van deze klant. 'cnx alias' gebruikt het automatisch.")
    return 0


def doorgeven(module, naam, args):
    sys.argv = [f"cnx {naam}"] + args
    try:
        return module.main() or 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else (print(e.code) or 1))


def uitvoeren(argv):
    if not argv:
        return None
    cmd, rest = argv[0], argv[1:]
    if cmd in ("-V", "--version", "versie"):
        print(f"CNX Toolkit {__version__}")
        return 0
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if cmd == "alias":
        from . import aliassen
        return doorgeven(aliassen, "alias", rest)
    if cmd == "api":
        from . import alias_api
        return doorgeven(alias_api, "api", rest)
    if cmd == "menu":
        return menu()
    if cmd == "web":
        from . import web
        return doorgeven(web, "web", rest)
    if cmd == "overrides":
        from . import overrides
        return doorgeven(overrides, "overrides", rest)
    if cmd == "invoer":
        return cmd_invoer(rest)
    if cmd == "hulp":
        return cmd_hulp(rest)
    if cmd == "sjablonen":
        return cmd_sjablonen(rest)
    print(f"Onbekend commando '{cmd}'.\n{__doc__}")
    return 2


def toon_menu(keuzes):
    print(f"\nCNX Toolkit {__version__}\n")
    for i, k in enumerate(keuzes, 1):
        print(f"  {i}. {k:10} {COMMANDO_S[k]}")
    print("  0. stoppen\n")
    print("Commando's met opties ('alias', 'api') werken het best vanuit PowerShell, bv.: cnx alias --help\n")


def menu_keuze(keuze, keuzes):
    """Voer een menukeuze uit: een nummer of een volledig commando. None betekent stoppen."""
    if keuze in ("", "0"):
        return None
    if keuze.isdigit() and 1 <= int(keuze) <= len(keuzes):
        k = keuzes[int(keuze) - 1]
        return uitvoeren([k, "--help"] if k in ("alias", "api") else [k])
    if keuze.isdigit():
        print(f"Kies een nummer van 0 tot {len(keuzes)}.")
        return 2
    return uitvoeren(keuze.split())


def menu():
    """Menu in een lus: na elke keuze kom je terug in het menu, tot je 0 kiest."""
    keuzes = list(COMMANDO_S)
    code = 0
    while True:
        toon_menu(keuzes)
        try:
            keuze = input("Keuze: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return code
        try:
            resultaat = menu_keuze(keuze, keuzes)
        except KeyboardInterrupt:
            resultaat = 130
            print("\nOnderbroken.")
        except Exception as e:  # het menu blijft draaien, ook als een commando faalt
            resultaat = 1
            print(f"\nFout: {e}")
        if resultaat is None:
            return code
        code = resultaat
        try:
            input("\nDruk op Enter om terug te gaan naar het menu.")
        except (EOFError, KeyboardInterrupt):
            print()
            return code


def main():
    argv = sys.argv[1:]
    try:
        code = uitvoeren(argv or ["web"])
    except KeyboardInterrupt:
        code = 130
    if not argv and code not in (0, 130, None):
        # bij dubbelklikken sluit het venster meteen: laat de fout eerst lezen
        try:
            input("\nDruk op Enter om te sluiten.")
        except (EOFError, KeyboardInterrupt):
            pass
    return code or 0


if __name__ == "__main__":
    sys.exit(main())

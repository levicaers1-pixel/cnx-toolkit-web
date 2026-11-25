"""Hulp voor de vertaaltest: alle Nederlandse teksten die de server via taal._() vertaalt.

Vaste teksten: elke aanroep _("...") in src/cnx_api. Dynamische teksten (een variabele in _()): de waarden die daar
kunnen komen, zoals de statuslabels, de opmerkingen uit aos10-modellen.json en de kolomnamen van de rapporten."""
import ast
import json
import os

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "cnx_api")


def vaste_sleutels():
    uit = {}
    for naam in sorted(os.listdir(SRC)):
        if not naam.endswith(".py"):
            continue
        boom = ast.parse(open(os.path.join(SRC, naam), encoding="utf-8").read())
        for k in ast.walk(boom):
            if isinstance(k, ast.Call) and isinstance(k.func, ast.Name) and k.func.id == "_" and k.args:
                if isinstance(k.args[0], ast.Constant) and isinstance(k.args[0].value, str):
                    uit.setdefault(k.args[0].value, f"{naam}:{k.lineno}")
            # kop("Soort", "Model", ...) in aos8.rapport_html en de kolommen in migratieplan.plan_html
            if isinstance(k, ast.Call) and isinstance(k.func, ast.Name) and k.func.id == "kop":
                for a in k.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        uit.setdefault(a.value, f"{naam}:{k.lineno}")
    return uit


def dynamische_sleutels():
    import sys
    sys.path.insert(0, os.path.join(SRC, ".."))
    from cnx_api import aos8, configapi
    uit = {}
    for w in aos8.STATUS_LABEL.values():
        uit[w] = "aos8.STATUS_LABEL"
    for w in configapi.WIS_GEVOLG.values():
        uit[w] = "configapi.WIS_GEVOLG"
    m = json.load(open(os.path.join(SRC, "data", "aos10-modellen.json"), encoding="utf-8"))
    for soort in ("ap", "controller"):
        for r in m[soort]:
            if r.get("opmerking"):
                uit[r["opmerking"]] = "aos10-modellen.json"
    if m.get("bron"):
        uit[m["bron"]] = "aos10-modellen.json"
    for k in ("Naam", "Model", "AP-groep", "Serienummer", "AOS-10", "Omgezet"):   # kolommen van plan_html
        uit[k] = "migratieplan.plan_html"
    return uit


def alle_sleutels():
    return {**dynamische_sleutels(), **vaste_sleutels()}


def ontbrekend():
    en = json.load(open(os.path.join(SRC, "data", "en-server.json"), encoding="utf-8"))
    return {k: w for k, w in alle_sleutels().items() if k not in en}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for k, w in sorted(ontbrekend().items(), key=lambda x: x[1]):
        print(json.dumps(k, ensure_ascii=False) + "\t" + w)

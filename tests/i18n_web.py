"""Hulp voor de vertaaltest: alle tekst-literals uit de JavaScript van web.html, en welke daarvan geen Engelse
vertaling hebben. Code-strings (CSS, ids, sleutels, selectors) staan in GEEN_TEKST of vallen weg door de regels."""
import json
import os
import re

DATA = os.path.join(os.path.dirname(__file__), "..", "src", "cnx_api", "data")
LIT = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`((?:[^`\\]|\\.)*)`')

# Strings in de code die geen tekst voor de gebruiker zijn (of in beide talen gelijk blijven).
GEEN_TEKST = {
    "__TOKEN__", "POST", "Content-Type", "X-Token", "X-Tijd", "Enter", "VUL-IN", "{vlan}", "sys_vlan_ipv4_{vlan}", "Modified", "Yes",
    "Access Switch", "Aggregation Switch", "Core Switch", "Mobility Gateway", "ACCESS_SWITCH", "IP", "VLAN", "AP", "AP-",
    "MAC", "Up", "Down", "AOS-10", "ONLINE", "FOUT", "LET OP", "Hostname", "Site", "Switch", "Object", "Model", "Status",
    "Cluster", "Clusters", "Controller", "Controllers", "Download", "APs", "Device group", "Device groups", "Sites",
    "Device function", "Redundant", "Parameters", "CNX Toolkit", "English", "Nederlands", "NL", "EN", "nl", "en",
    "Client ID", "Client secret", "deviceGroupName", "siteName", "AOS10-gereedheid", "Migratie", "Clusters (",
    "prefix /", "monitoring + /", "Download klantconfig.json", "Stand-by", "Stand", "Soort",
    # sleutels, ids, waarden en stukjes code (geen tekst voor de gebruiker)
    ' + t.replace(/"/g, ',
    ",;\n]/.test(t) ? '",
    '/hulp',
    '120px',
    '140px',
    '260px',
    '56px',
    '; Path=/; Max-Age=31536000; SameSite=Strict',
    '; Secure',
    ';charset=utf-8',
    'Detail',
    'aanmeldknop',
    'aanpak',
    'afwijkingen',
    'alias',
    'alleen',
    'alt',
    'application/json',
    'ascending',
    'base',
    'beforeunload',
    'blokkade',
    'chip',
    'chips',
    'cluster',
    'clusters',
    'cnx_taal=',
    'config',
    'controllers',
    'datalist',
    'descending',
    'dlg',
    'down',
    'enkel lokaal',
    'es',
    'fout',
    'geerfd',
    'gelijk',
    'groepen',
    'header',
    'hulp',
    'ib',
    'input[type=search]',
    'inventaris',
    'item',
    'item swit',
    'keydown',
    'klant',
    'klik',
    'lokaal',
    'max-height:',
    'mgmt',
    'modellen',
    'null',
    'objecten',
    'on',
    'onboard',
    'oordeel',
    'opkuis',
    'overrides',
    'ovrscan',
    'pane',
    'panes',
    'patroon',
    'per switch',
    'placeholder',
    'profiel',
    'redundant',
    'regex',
    'samen',
    'scan',
    'show ap database long',
    'show switches',
    'stand',
    'standby',
    'stat',
    'step',
    'subnav',
    'switch',
    'systeemprofiel',
    'taalknop',
    'tabel',
    'tabs',
    'text/csv',
    'text/html',
    'tiles',
    'title',
    'tools',
    'uitleg',
    'up',
    'van',
    'veld',
    'verschilt',
    'vlan',
    'voorstel',
    'voortgang',
    'wisplan',
    ' · GreenLake',
    'ws',
    'glp',
    'glpplan',
    'glpuitvoeren',
    'greenlake-onboarding-voorbeeld.csv',
    'serial;mac;soort;site;device group;device function;subscription;naamr\n',
    'off',
    'textarea',
    'rij',
    'srt',
    'fn',
    'subscription',
    'melding',
    'danger',
    ' · eval',
    'GreenLake Onboarding',
    'Gateway',
    'Campus AP',
    'Branch Gateway',
    'snap',
    'radio',
    'voor',
    'na',
    'wat',
    'koppeling',
    'applan',
    'apuitvoeren',
    'snapshot',
    'snapshot.json',
    'ap-hernoemen.csv',
    'netwerk',
    'wissen',
}


def letterlijk(t):
    """Een JS-literal zoals hij in de pagina staat, met de escapes (\\n, \\', \\") omgezet."""
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), t)


def is_code(t):
    if not re.search(r"[A-Za-z]{2}", t):
        return True
    if t.startswith(("/api/", "http", "cnx-web-", "aos8-", "#", ".", "&", "?", "^", "[", "M", "translate")) and not re.match(r"^(Migratie|Model|Modellen|MAC)\b", t):
        if not re.match(r"^(Migratie|Model|Modellen|MAC|Meld|Maak|Mislukt|Minder|Migratiebestand|Migratieplan|Meestal|Moet)", t):
            return True
    if re.fullmatch(r"[a-z0-9_\-\.:#/\[\]=\"' ]+", t) and re.search(r"(^|\s)(btn|pill|banner|row|card|hint|mono|small|primary|sp|ok|warn|bad|neu|info|dot|log|lead|field|lbl|gekozen|bestand|gevuld|tile|tegels|tabelbox|blok|cmdline|pad|err|muted|vak)(\s|$)", t):
        return True                                       # css-klassen
    if re.search(r"[a-z\-]+:[^;]+(;|$)", t) and not re.search(r"\s[a-z]+:\s", t[:3]):
        if ":" in t and (";" in t or re.fullmatch(r"[a-z\-]+:[^ ]+", t) or "px" in t or "var(" in t):
            return True                                   # inline-stijl
    if re.fullmatch(r"[a-z][a-zA-Z0-9]*", t) and not re.fullmatch(r"[a-z]+", t):
        return True                                       # camelCase-sleutels
    if re.fullmatch(r"[a-z0-9_\-]+", t) and ("_" in t or "-" in t) and " " not in t:
        return True                                       # ids en sleutels
    if re.fullmatch(r"[a-z]+", t) and t in {"div", "span", "button", "input", "label", "table", "thead", "tbody", "tr", "td", "th",
                                             "select", "option", "details", "summary", "progress", "iframe", "aside", "section",
                                             "dialog", "pre", "ol", "ul", "li", "nav", "strong", "code", "file", "text", "checkbox",
                                             "search", "tab", "tabpanel", "img", "note", "true", "false", "click", "change", "input",
                                             "number", "password", "open", "selected", "disabled", "checked", "value", "string",
                                             "object", "function", "undefined", "img", "ok", "warn", "bad", "neu", "info", "end",
                                             "start", "center", "auto", "none", "block", "flex", "grid", "hidden", "a", "p", "b",
                                             "h1", "h2", "h3", "h4", "em", "small", "id", "t", "n", "s", "r", "k", "v", "x", "lijst",
                                             "naam", "serial", "groep", "model", "ip", "status", "hostname", "site", "klaar", "einde",
                                             "aos10", "aantal", "opmerking", "type", "versie", "aps", "rol", "mac", "flags", "controller",
                                             "detail", "soort", "fasen", "stappen", "data", "cmd", "titel", "tekst", "fase", "id", "let_op"}:
        return True
    return False


def literals(pad=None):
    s = open(pad or os.path.join(DATA, "web.html"), encoding="utf-8").read()
    js = s[s.index("<script>"):]
    uit = {}
    for m in LIT.finditer(js):
        t = m.group(1) if m.group(1) is not None else (m.group(2) if m.group(2) is not None else (m.group(3) or ""))
        if "${" in t:
            continue
        t = letterlijk(t)
        if not is_code(t) and t not in GEEN_TEKST:
            uit.setdefault(t, s.count("\n", 0, s.index("<script>") + m.start()) + 1)
    return uit


def ontbrekend():
    en = json.load(open(os.path.join(DATA, "en-web.json"), encoding="utf-8"))
    return {t: r for t, r in literals().items() if t not in en and t.strip() not in en}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for t, r in sorted(ontbrekend().items(), key=lambda x: x[1]):
        print(f"{r}\t{t!r}")

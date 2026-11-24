"""Bouwhulp: LEESMIJ.html genereren, Windows-versie-info schrijven, release-zip maken.

  python build/maak.py leesmij      data/LEESMIJ.html uit LEESMIJ.md (nodig voor 'cnx hulp')
  python build/maak.py versie       build/versie.txt voor de eigenschappen van cnx.exe
  python build/maak.py zip          dist/CNX-Toolkit-<versie>.zip met cnx.exe, documentatie en sjablonen
"""
import os
import re
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
from cnx_api import __version__  # noqa: E402

DATA = os.path.join(ROOT, "src", "cnx_api", "data")


# Zelfde vormgeving als de webapp (cnx web), met donkere modus volgens het systeem.
LEESMIJ_STIJL = """
:root{color-scheme:light;--paper:#f4f6f9;--panel:#fff;--panel2:#f8fafc;--ink:#122033;--ink2:#2b3a4f;--muted:#5f6c7f;--line:#e2e7ee;--accent:#2457d6;--soft:#eaf0fd}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--paper:#0e131a;--panel:#161d27;--panel2:#1a2230;--ink:#e7ecf3;--ink2:#c9d2df;--muted:#93a0b4;--line:#253042;--accent:#7aa2ff;--soft:#1c2943}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:920px;margin:28px auto 60px;padding:28px 36px 36px;background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:0 1px 2px rgba(18,32,51,.04),0 2px 6px rgba(18,32,51,.05)}
.kop{display:flex;align-items:center;gap:12px;padding-bottom:18px;margin-bottom:8px;border-bottom:1px solid var(--line)}
.logo{width:34px;height:34px;border-radius:9px;display:grid;place-items:center;background:linear-gradient(135deg,#2457d6,#5b8cff);color:#fff;font-weight:700;font-size:11px;letter-spacing:.04em}
.versie{color:var(--muted);font-size:12.5px}
h1,h2,h3{line-height:1.25;letter-spacing:-.01em;font-weight:650}
h1{font-size:28px;margin:22px 0 8px}h2{font-size:20px;margin:34px 0 10px;padding-top:6px}h3{font-size:16px;margin:24px 0 8px}
p,li{color:var(--ink2)}a{color:var(--accent)}
table{border-collapse:separate;border-spacing:0;width:100%;margin:14px 0 18px;border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:14px}
th,td{padding:8px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}tr:last-child td{border-bottom:0}
th{background:var(--panel2);font-size:11.5px;color:var(--muted);font-weight:650;text-transform:uppercase;letter-spacing:.05em}
td:first-child code{white-space:nowrap}
code{font-family:"Cascadia Mono",Consolas,monospace;font-size:.88em;background:var(--soft);color:var(--ink);padding:1px 5px;border-radius:5px}
pre{background:var(--panel2);border:1px solid var(--line);padding:14px 16px;border-radius:10px;overflow:auto}pre code{background:none;padding:0}
@media (max-width:700px){main{margin:0;border-radius:0;padding:20px 16px}}
"""


def leesmij():
    import markdown
    with open(os.path.join(ROOT, "LEESMIJ.md"), encoding="utf-8") as f:
        body = markdown.markdown(f.read(), extensions=["tables", "fenced_code"])
    html = ("<!DOCTYPE html><html lang=\"nl\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>CNX Toolkit {__version__}</title><style>{LEESMIJ_STIJL}</style></head>\n<body><main>"
            f"<div class=\"kop\"><span class=\"logo\" aria-hidden=\"true\">CNX</span><div><strong>Handleiding</strong>"
            f"<div class=\"versie\">CNX Toolkit, versie {__version__}</div></div></div>\n{body}</main></body></html>")
    with open(os.path.join(DATA, "LEESMIJ.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("data/LEESMIJ.html geschreven")


def versie():
    v = tuple(int(x) for x in re.findall(r"\d+", __version__)[:3]) + (0,)
    tekst = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('041304b0', [
    StringStruct('FileDescription', 'CNX Toolkit'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('ProductName', 'CNX Toolkit'),
    StringStruct('ProductVersion', '{__version__}'),
    StringStruct('OriginalFilename', 'cnx.exe')])]),
    VarFileInfo([VarStruct('Translation', [0x0413, 1200])])])
"""
    with open(os.path.join(ROOT, "build", "versie.txt"), "w", encoding="utf-8") as f:
        f.write(tekst)
    print("build/versie.txt geschreven")


def maak_zip():
    exe = next((os.path.join(ROOT, "dist", n) for n in ("cnx.exe", "cnx") if os.path.exists(os.path.join(ROOT, "dist", n))), None)
    if not exe:
        sys.exit("dist/cnx.exe niet gevonden. Eerst: pyinstaller build/cnx.spec")
    doel = os.path.join(ROOT, "dist", f"CNX-Toolkit-{__version__}.zip")
    map_ = f"CNX Toolkit {__version__}"
    with zipfile.ZipFile(doel, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(exe, f"{map_}/{os.path.basename(exe)}")
        for naam in ("LEESMIJ.md", "LICENSE", "NOTICE", "CHANGELOG.md"):
            z.write(os.path.join(ROOT, naam), f"{map_}/{naam}")
        z.write(os.path.join(DATA, "LEESMIJ.html"), f"{map_}/LEESMIJ.html")
        z.write(os.path.join(ROOT, "docs", "TECHNISCH.md"), f"{map_}/docs/TECHNISCH.md")
        for naam in ("klantconfig.json", "toestellen-sjabloon.csv"):
            z.write(os.path.join(DATA, naam), f"{map_}/sjablonen/{naam}")
        # broncode mee
        for r, _, fs in os.walk(os.path.join(ROOT, "src")):
            for n in fs:
                if "__pycache__" in r or n.endswith(".pyc"):
                    continue
                p = os.path.join(r, n)
                z.write(p, f"{map_}/broncode/{os.path.relpath(p, ROOT)}")
        for n in ("pyproject.toml", "build/cnx.spec", "build/start.py", "build/maak.py"):
            z.write(os.path.join(ROOT, n), f"{map_}/broncode/{n}")
    print(f"{doel} ({os.path.getsize(doel) // 1024} kB)")


if __name__ == "__main__":
    {"leesmij": leesmij, "versie": versie, "zip": maak_zip}[sys.argv[1]]()

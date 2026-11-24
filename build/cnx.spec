# PyInstaller-spec voor cnx.exe. Gebruik: pyinstaller build/cnx.spec (vanuit de hoofdmap)
import os
root = os.path.abspath(os.path.join(SPECPATH, ".."))
src = os.path.join(root, "src")

a = Analysis(
    [os.path.join(root, "build", "start.py")],
    pathex=[src],
    datas=[(os.path.join(src, "cnx_api", "data"), os.path.join("cnx_api", "data"))],
    hiddenimports=["cnx_api.aliassen", "cnx_api.alias_api", "cnx_api.overrides", "cnx_api.web", "cnx_api.monitor", "cnx_api.configapi"],
    excludes=["tkinter", "unittest", "pydoc_data"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="cnx",
    console=True,
    upx=False,
    icon=os.path.join(root, "build", "cnx.ico") if os.path.exists(os.path.join(root, "build", "cnx.ico")) else None,
    version=os.path.join(root, "build", "versie.txt") if os.path.exists(os.path.join(root, "build", "versie.txt")) else None,
)

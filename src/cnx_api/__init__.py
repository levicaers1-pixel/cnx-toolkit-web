"""CNX Toolkit: hulpmiddelen om access switches naar HPE Aruba Networking Central (new Central) te brengen."""
import os
import sys

__version__ = "0.2.3"


def resource(naam):
    """Pad naar een meegeleverd databestand, ook in de .exe (PyInstaller)."""
    basis = getattr(sys, "_MEIPASS", None)
    if basis:
        return os.path.join(basis, "cnx_api", "data", naam)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", naam)

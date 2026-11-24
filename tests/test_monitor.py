"""Tabbladen Switches en Overzicht van cnx web, tegen een nagemaakte Central (tests/nep_central.py)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import nep_central  # noqa: E402
from cnx_api import alias_api as cx  # noqa: E402
from cnx_api import monitor  # noqa: E402
from test_web import server, vraag  # noqa: E402,F401  (fixture en hulpfunctie)


@pytest.fixture
def central(monkeypatch):
    nep_central.AANROEPEN.clear()
    monkeypatch.setattr(cx, "api", nep_central.api)
    monkeypatch.setitem(cx.S.headers, "Authorization", "Bearer test")
    return nep_central.AANROEPEN


def j(antwoord):
    return json.loads(antwoord[1])


def test_aanmelden_nodig(server, monkeypatch):
    monkeypatch.delitem(cx.S.headers, "Authorization", raising=False)
    s, b = vraag(server + "/api/web/sw/overrides-lijst")
    assert s == 401 and b"aanmelden" in b


def test_paginering(monkeypatch):
    paginas = {None: {"items": [1, 2], "next": "2", "total": 3}, "2": {"items": [3], "next": None, "total": 3}}
    monkeypatch.setattr(cx, "api", lambda m, p, params=None, body=None: nep_central.Antwoord(200, paginas[params.get("next")]))
    assert monitor.alles_next("/x", {"limit": 2})["items"] == [1, 2, 3]
    offsets = []

    def api(m, p, params=None, body=None):
        offsets.append(params["offset"])
        return nep_central.Antwoord(200, {"items": list(range(params["offset"], min(params["offset"] + 2, 5))), "total": 5})
    monkeypatch.setattr(cx, "api", api)
    assert monitor.alles_offset("/x", {"limit": 2})["items"] == [0, 1, 2, 3, 4] and offsets == [0, 2, 4]

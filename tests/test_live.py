"""For maintainers: a real quote on makepartsnow.com (or MPN_BASE_URL), never a checkout link or a payment.
Skipped unless MPN_LIVE=1. It uploads a 20 mm cube, quotes it in PA12 Black, revises it to PETG, and deletes it."""

from __future__ import annotations

import os
import struct

import pytest

from makepartsnow import state

from .conftest import run

pytestmark = pytest.mark.skipif(os.environ.get("MPN_LIVE") != "1", reason="set MPN_LIVE=1 to quote on the live service")


def cube_stl(path, size=20.0):
    v = [(x, y, z) for x in (0, size) for y in (0, size) for z in (0, size)]
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    data = b"\0" * 80 + struct.pack("<I", len(faces))
    for a, b, c in faces:
        data += struct.pack("<12fH", 0, 0, 0, *v[a], *v[b], *v[c], 0)
    path.write_bytes(data)


def test_quote_revise_and_delete(tmp_path):
    cube = tmp_path / "cube20.stl"
    cube_stl(cube)
    quoted = run(None, "quote", f"{cube}:2", "--units", "mm", "--zip", "89101", "--finish", "black", "--yes", "--json")
    assert quoted.code == 0, quoted.err
    quote = quoted.json["quote"]
    assert quote["parts"][0]["dimensions_mm"] == [20.0, 20.0, 20.0] and quote["totals"]["total_price"] > 0
    revised = run(None, "requote", quote["quote_id"], "--material", "fdm_petg", "--finish", "black", "--json")
    assert revised.code == 0 and revised.json["quote"]["parts"][0]["material"] == "fdm_petg"
    deleted = run(None, "delete", "--all")
    assert deleted.code == 0 and state.uploads() == []

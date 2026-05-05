"""Unit tests for the silks module — CID derivation, SVG sanitisation,
and message attachment. Live network calls are stubbed; the renderer
integration test (test_svg_to_png_renders_real_silk_fixture) is gated on
resvg_py being importable so it skips cleanly when the wheel isn't
available."""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

from dailybreezeup import silks

FIX = Path(__file__).parent / "fixtures" / "racingpost"


def test_cid_for_url_is_deterministic_and_url_safe():
    a = silks._cid_for_url("https://www.rp-assets.com/svg/d/1/5/361251d.svg")
    b = silks._cid_for_url("https://www.rp-assets.com/svg/d/1/5/361251d.svg")
    c = silks._cid_for_url("https://www.rp-assets.com/svg/5/4/8/49845.svg")
    assert a == b
    assert a != c
    assert a.startswith("silk-")
    assert all(ch.isalnum() or ch == "-" for ch in a)


def test_assign_silk_cids_only_sets_cid_when_url_present():
    rows = [
        {"silk_url": "https://x/y.svg"},
        {"silk_url": None},
        {},
    ]
    silks.assign_silk_cids(rows)
    assert rows[0]["silk_cid"].startswith("silk-")
    assert "silk_cid" not in rows[1]
    assert "silk_cid" not in rows[2]


def test_assign_silk_cids_dedups_same_url_to_same_cid():
    rows = [
        {"silk_url": "https://x/a.svg"},
        {"silk_url": "https://x/a.svg"},
        {"silk_url": "https://x/b.svg"},
    ]
    silks.assign_silk_cids(rows)
    assert rows[0]["silk_cid"] == rows[1]["silk_cid"]
    assert rows[0]["silk_cid"] != rows[2]["silk_cid"]


def test_attach_silks_skips_when_no_html_part(monkeypatch):
    # Plain-text-only message has no text/html — attach_silks must no-op
    # rather than raise.
    msg = EmailMessage()
    msg.set_content("hi")
    rows = [{"silk_url": "https://x/y.svg"}]
    monkeypatch.setattr(silks, "_fetch_svg", lambda url, session=None: b"<svg/>")
    monkeypatch.setattr(silks, "_svg_to_png", lambda svg: b"\x89PNG\r\n")
    assert silks.attach_silks(msg, rows) == 0


def test_attach_silks_attaches_each_unique_url_inline(monkeypatch):
    msg = EmailMessage()
    msg.set_content("plain")
    msg.add_alternative("<html><body><img src='cid:foo'></body></html>", subtype="html")
    rows = [
        {"silk_url": "https://x/a.svg"},
        {"silk_url": "https://x/a.svg"},  # duplicate; should fetch once
        {"silk_url": "https://x/b.svg"},
        {"silk_url": None},
    ]
    fetched: list[str] = []

    def fake_fetch(url, session=None):
        fetched.append(url)
        return b"<svg/>"

    monkeypatch.setattr(silks, "_fetch_svg", fake_fetch)
    monkeypatch.setattr(silks, "_svg_to_png", lambda svg: b"\x89PNG\r\n")
    n = silks.attach_silks(msg, rows)
    assert n == 2
    assert fetched == ["https://x/a.svg", "https://x/b.svg"]
    # The two PNG parts should now exist in the message tree.
    image_parts = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(image_parts) == 2
    cids = {p["Content-ID"].strip("<>") for p in image_parts}
    assert silks._cid_for_url("https://x/a.svg") in cids
    assert silks._cid_for_url("https://x/b.svg") in cids


def test_attach_silks_skips_failed_fetch(monkeypatch):
    msg = EmailMessage()
    msg.set_content("plain")
    msg.add_alternative("<html></html>", subtype="html")
    rows = [{"silk_url": "https://x/a.svg"}]
    monkeypatch.setattr(silks, "_fetch_svg", lambda url, session=None: None)
    assert silks.attach_silks(msg, rows) == 0


def test_sanitise_svg_strips_pt_suffixed_dims():
    raw = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="98.45pt" '
        b'height="70.53pt" viewBox="0 0 98.45 70.53"></svg>'
    )
    out = silks._sanitise_svg(raw)
    assert 'pt"' not in out
    assert 'viewBox="0 0 98.45 70.53"' in out


def test_svg_to_png_renders_real_silk_fixture():
    """Integration test: actually rasterise a captured RP silk via resvg-py.

    This is the single test that would have caught the production bug —
    the unit tests all stub the renderer, so swapping cairosvg → resvg
    only leaves the failure mode in this path. Skipped if resvg-py isn't
    importable so unrelated dev environments stay green.
    """
    pytest.importorskip("resvg_py")
    svg = (FIX / "silk_efsixteen.svg").read_bytes()
    png = silks._svg_to_png(svg)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 200

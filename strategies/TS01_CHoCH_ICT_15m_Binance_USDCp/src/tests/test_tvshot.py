"""Chart capture (v1.25). No network and no TradingView: the browser paths run against a
local file, and are skipped where Playwright or its Chromium is not installed."""
from pathlib import Path

import pytest

from common.charts import tvshot

CFG = {"tradingview": {"layout_id": "1pkR5u3W", "exchange": "BINANCE", "suffix": ".P"}}
PAGE = ('<body style="margin:0"><div class="layout__area--center" style="width:900px;height:500px;'
        'background:#131722"><canvas width="900" height="500"></canvas></div></body>')


def test_chart_url_uses_the_layout_and_the_perp_suffix():
    assert tvshot.chart_url(CFG, "AVAXUSDC") == \
        "https://www.tradingview.com/chart/1pkR5u3W/?symbol=BINANCE:AVAXUSDC.P&interval=15"
    assert "/chart/?symbol=" in tvshot.chart_url({}, "AVAXUSDC")
    assert tvshot.chart_url(CFG, "AVAXUSDC", "60").endswith("interval=60")


def test_permalink_pattern_matches_tradingview_snapshots():
    m = tvshot.PERMALINK_RE.search("copied: https://www.tradingview.com/x/d1jKXOlk/ ok")
    assert m and m.group(0) == "https://www.tradingview.com/x/d1jKXOlk/"
    assert not tvshot.PERMALINK_RE.search("https://www.tradingview.com/chart/1pkR5u3W/")


def test_out_path_is_named_for_the_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(tvshot, "SHOT_DIR", tmp_path)
    p = tvshot.out_path("AVAXUSDC", when=1_757_000_000_000)
    assert p.name.endswith("-AVAXUSDC.png") and p.parent == tmp_path


def test_try_capture_never_raises():
    r = tvshot.try_capture("AVAXUSDC", url="http://127.0.0.1:1/nope", settle=0.1, permalink=False)
    assert r["png"] is None and r["error"]


def test_png_size_reads_the_header(tmp_path):
    assert tvshot.png_size(tmp_path / "missing.png") is None
    (tmp_path / "not.png").write_bytes(b"nope")
    assert tvshot.png_size(tmp_path / "not.png") is None


def test_captures_the_chart_pane_and_reports_the_selector(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    monkeypatch.setattr(tvshot, "PROFILE_DIR", tmp_path / "profile")
    page = tmp_path / "chart.html"
    page.write_text(PAGE, encoding="utf-8")
    out = tmp_path / "shot.png"
    try:
        r = tvshot.capture("FAKEUSDC", cfg=CFG, out=out, url=page.as_uri(), settle=0.5,
                           permalink=False)
    except tvshot.ShotError as e:
        pytest.skip(f"no browser available here: {e}")
    assert Path(r["png"]).is_file() and r["size"] == (900, 500)
    assert "layout__area--center" in r["element"] and not r["warnings"]

"""Runner smoke test: one PAPER cycle on synthetic bars with klines and Telegram mocked.
Checks the mode prefix, the tier line, the exchange line, dedupe across cycles, and that
nothing is sent twice."""
import json
import shutil
import sys
from pathlib import Path

import pytest

from strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src import runner
from strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.tests.test_engine_equivalence import synth

STRAT = Path(runner.__file__).resolve().parent.parent


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    here = tmp_path / "TS01_CHoCH_ICT_15m_Binance_USDCp"
    shutil.copytree(STRAT / "config", here / "config")
    monkeypatch.setattr(runner, "HERE", here)
    monkeypatch.setattr(runner.Path, "home", staticmethod(lambda: tmp_path))   # no ~/.choch-watch seed
    sent = []
    monkeypatch.setattr(runner.telegram, "send", lambda text, to=None, book=None, **kw: sent.append((to, text)))
    monkeypatch.setattr(runner, "exchange_snapshot", lambda params: None)
    # seeds chosen because they carry a completed setup inside the last 400 bars
    bars = {"SYMA": synth(6), "SYMB": synth(51), "SYMC": synth(0)}
    monkeypatch.setattr(runner.data, "klines_paged", lambda sym, total, interval="15m": bars[sym])
    return here, sent


def _run(symbols, stdout=False, backfill=0):
    class A: pass
    a = A(); a.symbols = symbols; a.stdout = stdout; a.backfill = backfill
    params, tiers = runner.load_config()
    return runner.cycle(params, tiers, "PAPER", a)


def test_cycle_sends_prefixed_messages_and_dedupes(sandbox):
    here, sent = sandbox
    s1 = _run("SYMA,SYMB,SYMC", backfill=400)
    assert s1["symbols"] == 3
    setups = [t for _, t in sent if "· SETUP ·" in t]
    assert len(setups) == 2, [t.splitlines()[0] for _, t in sent]
    for to, text in sent:
        head = text.splitlines()[0]
        assert head.startswith("PAPER · ") and head.endswith("· TS01"), head
    for text in setups:
        assert "tier 1 × $20.00 ceiling" in text and "exchange  not checked" in text and "(limit, maker)" in text
    assert (here / "results" / "state.json").is_file()
    n_first = len(sent)
    # cycle 2: the same historical setups are now announced, so their closures are reported once
    _run("SYMA,SYMB,SYMC", backfill=400)
    closes = [t for _, t in sent[n_first:] if "STOPPED (paper)" in t or "TARGET HIT (paper)" in t]
    assert len(closes) == 2, [t.splitlines()[0] for _, t in sent[n_first:]]
    assert all("result  " in t for t in closes)
    n_second = len(sent)
    # cycle 3: nothing new
    _run("SYMA,SYMB,SYMC", backfill=400)
    new = [t.splitlines()[0] for _, t in sent[n_second:] if "HEARTBEAT" not in t]
    assert new == [], new
    log = (here / "logs" / "TS01-runner.jsonl").read_text().splitlines()
    assert len(log) >= 2 and json.loads(log[-1])["event"] == "cycle"


def test_mode_guard():
    with pytest.raises(SystemExit):
        runner.assert_mode({"mode": "LIVE"})
    assert runner.assert_mode({"mode": "paper"}) == "PAPER"


def test_ceiling_rule():
    book, cap = runner.ceiling({"risk": {"book_usd": 356, "unit_usd": 20}})
    assert cap == 20.0
    assert runner.ceiling({"risk": {"book_usd": 5000, "unit_usd": 20}})[1] == 50.0

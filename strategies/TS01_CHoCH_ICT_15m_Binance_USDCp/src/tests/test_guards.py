"""Guards on Ed's real orders (v1.11): matching, NO STOP alert, CANCEL NOW, opt-in auto-cancel.
The exchange is a fake snapshot; the cancel call is captured, never sent."""
import shutil
from pathlib import Path

import pytest

from strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src import runner
from strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.tests.test_engine_equivalence import synth

STRAT = Path(runner.__file__).resolve().parent.parent


def _setup_from(bars):
    """The most recent expired/closed setup on this series, with its ticket prices."""
    evs = runner.engine.live_state(bars, report_all=True)
    tk = [e for e in evs if e["status"] in ("expired", "closed")][-1]
    return tk


@pytest.fixture
def env(tmp_path, monkeypatch):
    here = tmp_path / "TS01_CHoCH_ICT_15m_Binance_USDCp"
    shutil.copytree(STRAT / "config", here / "config")
    monkeypatch.setattr(runner, "HERE", here)
    monkeypatch.setattr(runner.Path, "home", staticmethod(lambda: tmp_path))
    sent, cancelled = [], []
    monkeypatch.setattr(runner.telegram, "send", lambda text, to=None, book=None, **kw: sent.append((to, text)))
    monkeypatch.setattr(runner, "cancel_entry_order", lambda params, sym, oid: cancelled.append((sym, oid)) or {"status": "CANCELED"})
    monkeypatch.setattr(runner.data, "symbol_filters", lambda *a, **k: {"SYMA": {"tick": 0.01, "step": 0.001}})
    bars = synth(6)
    monkeypatch.setattr(runner.data, "klines_paged", lambda sym, total, interval="15m": bars)
    tk = _setup_from(bars)
    params, tiers = runner.load_config()
    T = runner.Ticket(params, {"SYMA": {"tick": 0.01, "step": 0.001}}, "SYMA", tk, 20.0, 1.0, 20.0)
    side = "SELL" if tk["d"] == -1 else "BUY"
    opp = "BUY" if side == "SELL" else "SELL"
    return dict(here=here, sent=sent, cancelled=cancelled, params=params, tiers=tiers, tk=tk, T=T, side=side, opp=opp, mp=monkeypatch)


def _run(env, snap, backfill=400):
    env["mp"].setattr(runner, "exchange_snapshot", lambda params: snap)
    class A: symbols = "SYMA"; stdout = False
    A.backfill = backfill
    return runner.cycle(env["params"], env["tiers"], "PAPER", A())


def test_matching_recognises_entry_position_and_stop(env):
    T, side, opp = env["T"], env["side"], env["opp"]
    snap = {"positions": [{"symbol": "SYMA", "qty": -T.qty if side == "SELL" else T.qty, "entry": T.price, "mark": T.price, "uPnl": 0.0}],
            "open_orders": [{"symbol": "SYMA", "side": opp, "type": "STOP_MARKET", "qty": T.qty, "price": 0.0, "stop": T.sl_trigger, "id": 7}]}
    m = runner.matching(snap, "SYMA", side, T.price, T.sl_trigger, T.tp_limit)
    assert m["position"] and m["stop_orders"] and not m["entry_orders"]
    line = runner.exchange_line(snap, "SYMA", m)
    assert "your position" in line and "matches this ticket" in line and "stop on exchange" in line


def test_no_stop_alert_goes_to_alerts_topic(env):
    T, side = env["T"], env["side"]
    snap = {"positions": [{"symbol": "SYMA", "qty": -T.qty if side == "SELL" else T.qty, "entry": T.price, "mark": T.price, "uPnl": -1.0}],
            "open_orders": []}
    _run(env, snap)
    alerts = [(to, t) for to, t in env["sent"] if "NO STOP ON EXCHANGE" in t]
    assert alerts and alerts[0][0] == "alerts", [t.splitlines()[1] for _, t in env["sent"]]
    assert "Place it now" in alerts[0][1]


def test_expired_matching_order_gets_cancel_now_by_default(env):
    T, side = env["T"], env["side"]
    snap = {"positions": [], "open_orders": [{"symbol": "SYMA", "side": side, "type": "LIMIT", "qty": T.qty, "price": T.price, "stop": 0.0, "id": 42}]}
    _run(env, snap)
    now = [t for to, t in env["sent"] if "CANCEL NOW" in t and to == "alerts"]
    assert now and "your order 42" in now[0]
    assert env["cancelled"] == []                       # default: the runner does not touch the exchange
    n = len(env["sent"])
    _run(env, snap)                                     # same state again: no repeat
    assert not [t for _, t in env["sent"][n:] if "CANCEL NOW" in t]


def test_auto_cancel_when_enabled_cancels_once(env):
    T, side = env["T"], env["side"]
    env["params"]["manage"]["auto_cancel_expired"] = True
    snap = {"positions": [], "open_orders": [{"symbol": "SYMA", "side": side, "type": "LIMIT", "qty": T.qty, "price": T.price, "stop": 0.0, "id": 43}]}
    _run(env, snap)
    assert env["cancelled"] == [("SYMA", 43)]
    assert [t for _, t in env["sent"] if "CANCELLED (auto)" in t and "your order 43" in t]
    _run(env, snap)
    assert env["cancelled"] == [("SYMA", 43)]           # not cancelled twice


def test_unrelated_order_is_not_touched(env):
    T, side = env["T"], env["side"]
    env["params"]["manage"]["auto_cancel_expired"] = True
    far = T.price * 1.05
    snap = {"positions": [], "open_orders": [{"symbol": "SYMA", "side": side, "type": "LIMIT", "qty": 1.0, "price": far, "stop": 0.0, "id": 99}]}
    _run(env, snap)
    assert env["cancelled"] == []
    assert not [t for _, t in env["sent"] if "CANCEL" in t]

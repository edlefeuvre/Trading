"""The living per-setup trade file (v1.13 / v1.24).

Nothing here touches Drive: `publish` is stubbed and every call is captured, so the tests
check the two properties the design rests on — one document per setup for its whole life,
and the human half of it (Ed's notes, his snapshot link) surviving every rewrite.
"""
import pytest

from common.reports import trade_file as tf
from strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src import runner
from strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.tests.test_guards import env, _run  # noqa: F401

CFG = {"drive": {"enabled": True, "trade_reports_folder": "FOLDER"},
       "tradingview": {"layout_id": "1pkR5u3W", "exchange": "BINANCE", "suffix": ".P"}}
T0 = 1_757_000_000_000


def _rec():
    return {"ts": "TS01", "sym": "AVAXUSDC", "side": "SELL", "t": T0,
            "expires": T0 + 32 * 900_000, "ticket": ["Price:   7.162  (limit, maker, post-only)"]}


@pytest.fixture
def calls(monkeypatch):
    """Capture publish() instead of writing to Drive."""
    seen = []

    def fake(cfg, name, markdown, file_id=None):
        seen.append({"name": name, "md": markdown, "file_id": file_id})
        return "DOC1", "https://docs.google.com/document/d/DOC1/edit", None

    monkeypatch.setattr(tf, "publish", fake)
    return seen


# ---------------------------------------------------------------- document ----
def test_doc_name_carries_no_status_so_the_link_never_breaks():
    a = tf.doc_name("TS01", "AVAXUSDC", "SELL", T0)
    assert a == tf.doc_name("TS01", "AVAXUSDC", "SELL", T0)
    assert "CLOSED" not in a and "OPEN" not in a
    assert a.startswith("2025") and a.endswith("TS01-AVAXUSDC-SELL")


def test_chart_link_uses_the_layout_from_config():
    live, sym = tf.chart_urls(CFG, "AVAXUSDC")
    assert "/chart/1pkR5u3W/?symbol=BINANCE:AVAXUSDC.P&interval=15" in live and sym == "BINANCE:AVAXUSDC.P"
    plain, _ = tf.chart_urls({"tradingview": {}}, "AVAXUSDC")
    assert "/chart/?symbol=" in plain


def test_splice_keeps_ed_notes_and_his_snapshot_link():
    new = tf.build("TS01", "AVAXUSDC", "SELL", "Paper", tf.OPEN, ["Price: 7.162"], T0,
                   T0 + 32 * 900_000, [], "exchange: nothing", CFG)
    old = ("# whatever the runner wrote last time\n\n"
           "- Snapshot: https://www.tradingview.com/x/d1jKXOlk/\n\n"
           f"{tf.NOTES_MARKER}\n\nfelt \\-rushed on the entry\n")
    out = tf.splice(new, old)
    assert "https://www.tradingview.com/x/d1jKXOlk/" in out
    assert tf.SNAP_PLACEHOLDER not in out
    assert "felt -rushed on the entry" in out          # Docs' export escaping stripped
    assert out.count(tf.NOTES_MARKER) == 1


def test_splice_survives_a_document_with_no_notes_yet():
    new = tf.build("TS01", "AVAXUSDC", "SELL", "Paper", tf.OPEN, [], T0, T0, [], "", CFG)
    assert tf.splice(new, "") == new
    assert tf.NOTES_MARKER in tf.splice(new, "# nothing familiar here\n")


# -------------------------------------------------------------------- sync ----
def test_sync_appends_events_once_and_keeps_the_same_document(calls):
    rec = _rec()
    tf.sync(CFG, rec, "SETUP", "ticket issued", when="Thu 04 Sep 15:33 UTC")
    tf.sync(CFG, rec, "SETUP", "ticket issued", when="Thu 04 Sep 15:33 UTC")   # replayed cycle
    tf.sync(CFG, rec, "FILLED (paper)", "entry touched", when="Thu 04 Sep 16:33 UTC")
    assert [e[1] for e in rec["events"]] == ["SETUP", "FILLED (paper)"]
    assert calls[0]["file_id"] is None and calls[1]["file_id"] == "DOC1" and calls[2]["file_id"] == "DOC1"
    assert len({c["name"] for c in calls}) == 1
    assert rec["report_url"].endswith("/DOC1/edit")


def test_sync_never_raises_when_drive_is_down(monkeypatch):
    monkeypatch.setattr(tf, "publish", lambda *a, **k: (None, None, "HttpError: 503"))
    rec = _rec()
    assert tf.sync(CFG, rec, "SETUP") is None
    assert rec["report_error"].startswith("HttpError")
    assert rec["events"]                                    # the event is still recorded for the next try


def test_closing_status_reflects_whether_a_trade_reached_the_exchange(calls):
    rec = _rec()
    tf.sync(CFG, rec, "WINDOW CLOSED", status=tf.CLOSED_PAPER, outcome="No fill within the 32-bar window.")
    assert "CLOSED (Paper)" in calls[-1]["md"]
    tf.sync(CFG, rec, "", status=tf.CLOSED_TRADED)
    assert "CLOSED (Traded)" in calls[-1]["md"]


# ------------------------------------------------------------------ runner ----
def _drive_on(env, calls):
    env["mp"].setattr(runner.trade_file, "load_book", lambda *a, **k: CFG)
    return calls


def test_setup_message_carries_the_report_link(env, calls):
    _drive_on(env, calls)
    _run(env, None)
    setups = [t for _, t in env["sent"] if "· SETUP ·" in t]
    assert setups and all("Report: https://docs.google.com/document/d/DOC1/edit" in t for t in setups)
    assert calls[0]["file_id"] is None                      # created once
    assert all(c["file_id"] == "DOC1" for c in calls[1:])   # updated thereafter


def test_window_close_fires_once_and_marks_the_file_paper(env, calls):
    _drive_on(env, calls)
    _run(env, None)
    closed = [t for _, t in env["sent"] if "REPORT CLOSED" in t]
    assert len(closed) == 1
    assert "CLOSED (Paper)" in closed[0] and "Report: https://docs.google.com" in closed[0]
    assert "CLOSED (Paper)" in calls[-1]["md"]
    env["sent"].clear()
    _run(env, None)                                          # replayed cycle: nothing repeats
    assert not [t for _, t in env["sent"] if "REPORT CLOSED" in t]


def test_a_position_of_eds_closes_the_file_as_traded(env, calls):
    _drive_on(env, calls)
    T, side, opp = env["T"], env["side"], env["opp"]
    snap = {"positions": [{"symbol": "SYMA", "qty": -T.qty if side == "SELL" else T.qty,
                           "entry": T.price, "mark": T.price, "uPnl": 0.0}],
            "open_orders": [{"symbol": "SYMA", "side": opp, "type": "STOP_MARKET", "qty": T.qty,
                             "price": 0.0, "stop": T.sl_trigger, "id": 7, "algo": True,
                             "working": "mark", "close_all": False}],
            "conditional_ok": True}
    _run(env, snap)
    assert [t for _, t in env["sent"] if "REPORT CLOSED" in t and "CLOSED (Traded)" in t]


def test_stdout_runs_do_not_write_to_drive(env, calls):
    _drive_on(env, calls)
    env["mp"].setattr(runner, "exchange_snapshot", lambda params: None)

    class A:
        symbols = "SYMA"; stdout = True; backfill = 400
    runner.cycle(env["params"], env["tiers"], "PAPER", A())
    assert not calls

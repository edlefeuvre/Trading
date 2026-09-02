r"""TS01 CHoCH ICT 15m Binance USDCp — runner (v0, PAPER).

choch_watch.py migrated into the repo on 2 Sep 2026. Detection logic is unchanged
(common.engine.ict_base); what changed is everything around it:

  * config from config/params.yaml + config/universe.yaml, not ~/.choch-watch/*.json
  * every message carries the MODE and the strategy ID: "PAPER · SETUP · TS01"
  * new events: FILLED (paper), STOPPED, TARGET HIT, WINDOW EXPIRED — the old watcher
    only ever said SETUP and IN TRADE
  * sends through common.alerts.telegram by destination name (alerts.to / critical_to /
    syslog), no token in this folder
  * reconciliation READ via the SERVER_RO Binance key when present: exchange positions
    and open orders go to results/holdings.json and are quoted in every paper-position
    message, so a paper fill can never read as a real one
  * one JSON line per cycle in logs/TS01-runner.jsonl; an hourly heartbeat to syslog
  * LIVE and SHADOW refuse to start in v0 — order placement is not implemented

Run one cycle (what Task Scheduler does every 15 minutes, from the repo root):
    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.runner
Options: --stdout (print, don't send)  --symbols BTCUSDC,ETHUSDC  --backfill N  --test
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

from common.alerts import telegram
from common.data import binance_klines as data
from common.engine import ict_base as engine

__version__ = "1.8"
HERE = Path(__file__).resolve().parent.parent           # strategy folder
REPO = HERE.parent.parent
SLUG = HERE.name
TS = SLUG.split("_")[0]                                  # "TS01"
TZ = dt.timezone.utc


# ------------------------------------------------------------ config ------
def load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.exit("pyyaml is required:  python -m pip install pyyaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config():
    params = load_yaml(HERE / "config" / "params.yaml")
    universe = load_yaml(HERE / "config" / "universe.yaml")
    tiers = {}
    for row in universe.get("symbols", []):
        if isinstance(row, dict):
            tiers[str(row["symbol"]).upper()] = float(row.get("tier", 0) or 0)
        else:
            tiers[str(row).upper()] = 1.0
    for s, v in list(tiers.items()):
        if v > 1.0:
            print(f"note: {s} tier {v} clamped to 1.0 (charter ceiling)", file=sys.stderr)
            tiers[s] = 1.0
    return params, tiers


def assert_mode(params) -> str:
    mode = str(params.get("mode", "PAPER")).upper()
    if mode != "PAPER":
        sys.exit(f"refusing to start: mode {mode} is not implemented in runner v{__version__} "
                 f"(order placement does not exist yet). Set mode: PAPER.")
    return mode


def ceiling(params) -> tuple[float, float]:
    risk = params.get("risk", {})
    book = float(risk.get("book_usd", 0) or 0)
    floor = float(risk.get("unit_usd", 20))
    return book, max(book * 0.01, floor)


# -------------------------------------------------------------- state -----
def state_path() -> Path:
    return HERE / "results" / "state.json"


def load_state() -> dict:
    p = state_path()
    if p.is_file():
        return json.load(open(p, encoding="utf-8"))
    # first run: inherit the old watcher's dedupe keys so nothing is re-announced
    old = Path.home() / ".choch-watch" / "state.json"
    if old.is_file():
        st = json.load(open(old, encoding="utf-8"))
        st["_seeded_from"] = str(old)
        return st
    return {}


def save_state(st: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if len(st) > 4000:
        st = dict(list(st.items())[-2000:])
    tmp = p.with_suffix(".tmp")
    json.dump(st, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, p)


def log_line(record: dict) -> None:
    p = HERE / "logs" / f"{TS}-runner.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": dt.datetime.now(TZ).isoformat(timespec="seconds"), **record}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ------------------------------------------------------ reconciliation ----
def exchange_snapshot(params) -> dict | None:
    """Read positions and open orders with the read-only key, if configured. Never raises."""
    name = str(params.get("credentials", {}).get("exchange_ro", "binance/SERVER_RO")).split("/")[-1]
    try:
        from common.exchange import binance
        if name not in binance.list_keys():
            return None
        c = binance.Client(name)
        c.sync_time()
        snap = {
            "ts": dt.datetime.now(TZ).isoformat(timespec="seconds"),
            "key": name,
            "positions": [{"symbol": p["symbol"], "qty": float(p["positionAmt"]), "entry": float(p["entryPrice"]),
                           "mark": float(p["markPrice"]), "uPnl": float(p["unRealizedProfit"]),
                           "margin": p.get("marginType"), "leverage": p.get("leverage")} for p in c.positions()],
            "open_orders": [{"symbol": o["symbol"], "side": o["side"], "type": o["type"], "qty": float(o["origQty"]),
                             "price": float(o["price"]), "stop": float(o.get("stopPrice", 0)), "id": o["orderId"]}
                            for o in c.open_orders()],
        }
        out = HERE / "results" / "holdings.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(snap, open(out, "w", encoding="utf-8"), indent=1)
        return snap
    except Exception as e:  # noqa: BLE001
        log_line({"event": "reconcile_failed", "error": str(e)})
        return {"error": str(e)}


def exchange_line(snap: dict | None, sym: str) -> str:
    if snap is None:
        return "exchange  not checked (no SERVER_RO key)"
    if "error" in snap:
        return f"exchange  read failed: {snap['error'][:80]}"
    pos = [p for p in snap["positions"] if p["symbol"] == sym]
    oo = [o for o in snap["open_orders"] if o["symbol"] == sym]
    if not pos and not oo:
        return f"exchange  no position, no orders in {sym}  (paper only)"
    parts = []
    if pos:
        parts.append(f"position {pos[0]['qty']:+g} @ {pos[0]['entry']:g}")
    if oo:
        parts.append(f"{len(oo)} open order(s)")
    return "exchange  " + ", ".join(parts) + "  — NOT placed by this runner (PAPER)"


# ------------------------------------------------------------ messages ----
def fmt(x: float) -> str:
    return f"{x:,.2f}" if x >= 1000 else f"{x:,.6f}".rstrip("0").rstrip(".")


def when(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, TZ).strftime("%a %d %b %H:%M UTC")


def ticket(mode: str, event: str, sym: str, tk: dict, risk_usd: float, tier: float, cap: float,
           snap: dict | None, extra: list[str] | None = None) -> str:
    side = "LONG" if tk["d"] == 1 else "SHORT"
    qty = risk_usd / tk["risk"]
    flag = "" if tk["poolR"] >= 1.0 else "   [!] pool < 1R"
    lines = [
        f"{mode} · {event} · {TS}",
        f"{sym} · {side} · 15m · signal {when(tk['t_placed'])}",
        "",
        f"entry   {fmt(tk['mid'])}   (limit, maker)",
        f"stop    {fmt(tk['stop'])}   ({tk['stop_pct']:.2f}%)",
        f"target  {fmt(tk['target'])}",
        f"pool    {tk['poolR']:.2f} R{flag}",
        "",
        f"qty     {qty:,.4f}",
        f"risk    ${risk_usd:,.2f}   (tier {tier:g} × ${cap:,.2f} ceiling)",
        f"notion  ${qty * tk['mid']:,.0f}",
    ]
    lines += extra or []
    lines += ["", exchange_line(snap, sym)]
    return "\n".join(lines)


# --------------------------------------------------------------- cycle ----
def cycle(params, tiers, mode: str, a) -> dict:
    alerts = params.get("alerts", {})
    book = alerts.get("book", "trading")
    to_main = alerts.get("to", "trading")
    to_sys = alerts.get("syslog_to", "syslog")
    hb_min = int(alerts.get("heartbeat_minutes", 60))

    book_usd, cap = ceiling(params)
    entry, structure, dcfg = params.get("entry", {}), params.get("structure", {}), params.get("data", {})
    k = int(structure.get("pivot_k", engine.K))
    live_bars = int(entry.get("gtc_window_bars", engine.LIVE_BARS))
    sweep_reclaim = int(entry.get("sweep_reclaim_bars", engine.SWEEP_RECLAIM))
    fvg_window = int(entry.get("gap_window_bars", engine.FVG_WINDOW))
    discount_only = bool(entry.get("discount_only", True))
    history_bars = int(dcfg.get("history_bars", 1500))

    watch = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else [s for s, t in tiers.items() if t > 0]
    st = load_state()
    snap = exchange_snapshot(params)
    sent: list[str] = []
    errors: list[str] = []

    def emit(text: str, to: str = to_main):
        if a.stdout:
            print(text + "\n" + "-" * 40)
            return
        try:
            telegram.send(text, to=to, book=book)
        except telegram.TelegramError as e:
            errors.append(f"telegram: {e}")
            print(text, file=sys.stderr)

    for sym in watch:
        tier = tiers.get(sym, 1.0 if a.symbols else 0.0)
        if tier <= 0:
            continue
        risk_usd = cap * tier
        try:
            need = max(history_bars, a.backfill + 200) if a.backfill else history_bars
            bars = data.klines_paged(sym, need)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sym}: {e}")
            continue
        if len(bars) < k * 4:
            continue
        n = len(bars)
        evs = engine.live_state(bars, k=k, live_bars=live_bars, report_all=True,
                                sweep_reclaim=sweep_reclaim, fvg_window=fvg_window, discount_only=discount_only)
        for tk in evs:
            key = f"{sym}:{tk['t_placed']}"
            announced = bool(st.get(key))
            age = (n - 1) - tk["fvg_bar"]
            status = tk["status"]

            if status == "placed" or (a.backfill and age <= a.backfill and not announced and status != "open"):
                if not announced:
                    emit(ticket(mode, "SETUP", sym, tk, risk_usd, tier, cap, snap,
                                [f"window  {live_bars} bars from the FVG bar (paper limit; nothing placed)"]))
                    st[key] = True; sent.append(f"SETUP {sym}")
                continue

            if status == "resting":
                if not announced:                      # first seen mid-window (e.g. after downtime)
                    emit(ticket(mode, "SETUP", sym, tk, risk_usd, tier, cap, snap,
                                [f"resting  {tk['bars_left']} bars left in the window"]))
                    st[key] = True; sent.append(f"SETUP {sym}")
                elif tk["bars_left"] <= 2 and not st.get(key + ":expiring"):
                    emit(ticket(mode, "EXPIRING", sym, tk, risk_usd, tier, cap, snap,
                                [f"window closes in {tk['bars_left']} bar(s); unfilled → cancel"]))
                    st[key + ":expiring"] = True; sent.append(f"EXPIRING {sym}")
                continue

            if status == "open":
                fkey = f"{sym}:fill:{tk['t_filled']}"
                if not st.get(fkey):
                    emit(ticket(mode, "FILLED (paper)", sym, tk, risk_usd, tier, cap, snap,
                                [f"filled  {when(tk['t_filled'])} — price touched the paper limit",
                                 f"unrealised {tk['unreal_R']:+.2f} R"]))
                    st[fkey] = True; st.setdefault(key, True); sent.append(f"FILLED {sym}")
                continue

            if status == "closed" and announced:
                ckey = f"{sym}:closed:{tk['t_exit']}"
                if not st.get(ckey):
                    ev = "STOPPED (paper)" if tk["outcome"] == "stop" else "TARGET HIT (paper)"
                    emit(ticket(mode, ev, sym, tk, risk_usd, tier, cap, snap,
                                [f"filled  {when(tk['t_filled'])}", f"exit    {when(tk['t_exit'])}",
                                 f"result  {tk['net_R']:+.2f} R   ({'stop, taker fee included' if tk['outcome']=='stop' else 'pool reached'})"]))
                    st[ckey] = True; sent.append(f"{ev.split()[0]} {sym}")
                continue

            if status == "expired" and announced:
                xkey = f"{sym}:expired:{tk['t_expired']}"
                if not st.get(xkey):
                    emit(ticket(mode, "WINDOW EXPIRED · CANCEL", sym, tk, risk_usd, tier, cap, snap,
                                [f"no fill within {live_bars} bars of the FVG bar; the paper limit is cancelled"]))
                    st[xkey] = True; sent.append(f"EXPIRED {sym}")
                continue

    # heartbeat to syslog
    now = time.time()
    if not a.stdout and now - float(st.get("_last_heartbeat", 0)) >= hb_min * 60:
        ex = ("no key" if snap is None else snap.get("error", f"{len(snap.get('positions', []))} position(s), "
                                                      f"{len(snap.get('open_orders', []))} open order(s) via SERVER_RO"))
        emit(f"{mode} · HEARTBEAT · {TS}\n{dt.datetime.now(TZ):%a %d %b %H:%M UTC} · {len(watch)} symbols scanned · "
             f"{len(sent)} event(s) this cycle · book ${book_usd:,.0f} → ceiling ${cap:,.2f}\nexchange: {ex}"
             + (f"\nerrors: {'; '.join(errors)[:300]}" if errors else ""), to=to_sys)
        st["_last_heartbeat"] = now

    if not a.stdout:
        save_state(st)
    summary = {"event": "cycle", "mode": mode, "symbols": len(watch), "sent": sent, "errors": errors,
               "exchange": (None if snap is None else ("error" if "error" in snap else
                            {"positions": len(snap["positions"]), "open_orders": len(snap["open_orders"])}))}
    log_line(summary)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default=None, help="override the universe for this run (comma list)")
    ap.add_argument("--stdout", action="store_true", help="print messages instead of sending")
    ap.add_argument("--backfill", type=int, default=0, help="also report setups placed in the last N bars")
    ap.add_argument("--test", action="store_true", help="send one test line to the strategy's topic and exit")
    a = ap.parse_args(argv)

    params, tiers = load_config()
    mode = assert_mode(params)
    if a.test:
        telegram.send(f"{mode} · TEST · {TS}\nrunner v{__version__} alive · {len([t for t in tiers.values() if t > 0])} symbols funded",
                      to=params.get("alerts", {}).get("to", "trading"), book=params.get("alerts", {}).get("book", "trading"))
        print("sent")
        return 0
    s = cycle(params, tiers, mode, a)
    print(f"# {mode} cycle: {s['symbols']} symbols, {len(s['sent'])} event(s)"
          + (f", {len(s['errors'])} error(s)" if s["errors"] else ""), file=sys.stderr)
    return 0 if not s["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())

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

__version__ = "1.12"
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
                             "price": float(o["price"]), "stop": float(o.get("stopPrice", 0)), "id": o["orderId"],
                             "algo": False, "working": "", "close_all": False}
                            for o in c.open_orders()],
        }
        # Conditional orders (Binance's "Conditional" tab: stop-market, take-profit …) live in the Algo
        # Order service, not in openOrders. Same shape, so matching() treats both alike.
        try:
            snap["open_orders"] += [
                {"symbol": o["symbol"], "side": o["side"], "type": o.get("orderType", ""),
                 "qty": float(o.get("quantity") or 0), "price": float(o.get("price") or 0),
                 "stop": float(o.get("triggerPrice") or 0), "id": o["algoId"], "algo": True,
                 "working": "mark" if o.get("workingType") == "MARK_PRICE" else "last",
                 "close_all": str(o.get("closePosition", "")).lower() == "true"}
                for o in c.open_algo_orders()]
            snap["conditional_ok"] = True
        except Exception as e:  # noqa: BLE001 — never claim NO STOP when we could not see the stops
            snap["conditional_ok"] = False
            log_line({"event": "algo_orders_failed", "error": str(e)})
        out = HERE / "results" / "holdings.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(snap, open(out, "w", encoding="utf-8"), indent=1)
        return snap
    except Exception as e:  # noqa: BLE001
        log_line({"event": "reconcile_failed", "error": str(e)})
        return {"error": str(e)}


TOL_PCT = 0.15   # price tolerance (%) for matching an exchange order/position to a ticket


def _near(a: float, b: float) -> bool:
    return bool(a and b) and abs(a - b) / b * 100 <= TOL_PCT


def matching(snap: dict | None, sym: str, side: str, entry: float, stop: float | None, target: float | None) -> dict:
    """Ed's exchange items that match this ticket: entry order(s), position, stop order(s), target order(s).
    Read-only; used to tell the truth in the exchange line and to guard a position without a stop."""
    out = {"entry_orders": [], "position": None, "stop_orders": [], "target_orders": []}
    if not snap or "error" in snap:
        return out
    opp = "BUY" if side == "SELL" else "SELL"
    for o in snap["open_orders"]:
        if o["symbol"] != sym:
            continue
        price = o["price"] or o["stop"]
        if o["side"] == side and o["type"] == "LIMIT" and _near(price, entry):
            out["entry_orders"].append(o)
        elif o["side"] == opp and stop and _near(o["stop"] or price, stop):
            out["stop_orders"].append(o)
        elif o["side"] == opp and target and (_near(price, target) or _near(o["stop"], target)):
            out["target_orders"].append(o)
    for p in snap["positions"]:
        if p["symbol"] == sym and ((p["qty"] < 0) == (side == "SELL")) and _near(p["entry"], entry):
            out["position"] = p
    return out


def exchange_line(snap: dict | None, sym: str, m: dict | None = None) -> str:
    if snap is None:
        return "exchange: not checked (no SERVER_RO key)"
    if "error" in snap:
        return f"exchange: read failed — {snap['error'][:60]}"
    pos = [p for p in snap["positions"] if p["symbol"] == sym]
    oo = [o for o in snap["open_orders"] if o["symbol"] == sym]
    if not pos and not oo:
        return f"exchange: nothing in {sym} (paper only)"
    if m and (m["position"] or m["entry_orders"]):
        bits = []
        if m["position"]:
            p = m["position"]
            bits.append(f"your position {p['qty']:+g} @ {p['entry']:g} (uPnL {p['uPnl']:+.2f})")
        for o in m["entry_orders"]:
            bits.append(f"your order {o['id']} · {o['qty']:g} @ {o['price']:g}")
        guard = []
        if m["position"]:
            if m["stop_orders"]:
                w = m["stop_orders"][0].get("working")
                guard.append("stop on exchange" + (f" ({w} trigger)" if w else ""))
            elif snap.get("conditional_ok") is False:
                guard.append("stop unknown (conditional orders not readable this cycle)")
            else:
                guard.append("⚠ NO STOP ON EXCHANGE")
            guard.append("target on exchange" if m["target_orders"] else "no target order")
        return "exchange: " + ", ".join(bits) + " — matches this ticket" + (f" · {' · '.join(guard)}" if guard else "")
    parts = []
    if pos:
        parts.append(f"position {pos[0]['qty']:+g} @ {pos[0]['entry']:g}")
    if oo:
        parts.append(f"{len(oo)} open order{'s' if len(oo) > 1 else ''}")
    return "exchange: " + ", ".join(parts) + " — does not match this ticket"


# ------------------------------------------------------------ messages ----
def when(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, TZ).strftime("%a %d %b %H:%M UTC")


class Ticket:
    """Everything needed to key the trade into the Binance USD-M futures form, rounded to the
    symbol's tick and lot size. Built once per event; rendered by `render`."""

    def __init__(self, params: dict, filters: dict, sym: str, tk: dict, risk_usd: float, tier: float, cap: float):
        f = filters.get(sym, {})
        self.tick, self.step = float(f.get("tick", 0) or 0), float(f.get("step", 0) or 0)
        orders, stop, target, risk = (params.get("orders", {}), params.get("stop", {}),
                                      params.get("target", {}), params.get("risk", {}))
        self.sym, self.tk, self.tier, self.cap = sym, tk, tier, cap
        self.side = "Buy" if tk["d"] == 1 else "Sell"
        self.pos = "LONG" if tk["d"] == 1 else "SHORT"
        d = tk["d"]
        self.price = data.round_to(tk["mid"], self.tick)
        # size: risk / (entry - stop), rounded DOWN to the lot step so risk never exceeds the unit
        raw_qty = risk_usd / abs(self.price - tk["stop"]) if self.price != tk["stop"] else 0.0
        self.qty = data.round_to(raw_qty, self.step, "down")
        self.notional = self.qty * self.price
        self.risk_usd_actual = self.qty * abs(self.price - tk["stop"])
        # take profit: trigger one tick the right side of entry, limit at the pool
        off = int(target.get("trigger_offset_ticks", 1)) * (self.tick or 0)
        self.tp_trigger = data.round_to(self.price + d * off, self.tick) if off else None   # profit side of entry
        self.tp_limit = data.round_to(tk["target"], self.tick)
        # stop: market on trigger, or limit buffered on the far side
        self.sl_trigger = data.round_to(tk["stop"], self.tick)
        self.sl_type = str(stop.get("order_type", "stop_market"))
        buf = int(stop.get("limit_buffer_ticks", 3)) * (self.tick or 0)
        self.sl_limit = data.round_to(tk["stop"] + (-d) * buf, self.tick) if self.sl_type == "stop_limit_buffered" else None
        self.trigger = str(orders.get("trigger_price", "mark")).capitalize()
        self.tif = str(orders.get("time_in_force", "GTC"))
        self.post_only = bool(params.get("entry", {}).get("post_only", True))
        self.reduce_only = bool(orders.get("reduce_only", True))
        self.margin = str(risk.get("margin_mode", "isolated"))
        self.lev = risk.get("leverage_cap", 20)
        self.base = sym.replace("USDC", "").replace("USDT", "")

    def p(self, x):  # price
        return data.fmt_inc(x, self.tick)

    def q(self, x):  # quantity
        return data.fmt_inc(x, self.step)

    def block(self) -> list[str]:
        """Ed's layout (3 Sep 2026): one field per line in the order of the Binance form."""
        trig = self.trigger.lower()
        sl_kind = f"limit {self.p(self.sl_limit)}" if self.sl_limit is not None else "market"
        lines = [f"Price:   {self.p(self.price)}  (limit, maker{', post-only' if self.post_only else ''})",
                 f"Size:    {self.q(self.qty)} {self.base}"]
        if self.tp_trigger:
            lines.append(f"TProfit: {self.p(self.tp_trigger)}  (trigger, {trig})")
        lines.append(f"TProfit: {self.p(self.tp_limit)}  (price)")
        lines.append(f"StopL:   {self.p(self.sl_trigger)}  ({self.tk['stop_pct']:.2f}%, {trig} → {sl_kind})")
        return lines

    def footer(self) -> list[str]:
        tk = self.tk
        rounding = "" if abs(self.risk_usd_actual - self.tier * self.cap) < 0.005 else f"  (${self.risk_usd_actual:,.2f} after lot rounding)"
        return [f"Notional: ${self.notional:,.0f}",
                f"R: {self.tier:g}xCaR = ${self.tier * self.cap:,.2f}{rounding}",
                f"Pool: {tk['poolR']:.2f} R{'' if tk['poolR'] >= 1 else '   [!] pool < 1R'}"]


def render(mode: str, event: str, t: Ticket, snap: dict | None, extra: list[str] | None = None,
           with_ticket: bool = True, m: dict | None = None) -> str:
    """Plain text in Ed's order: time, mode/event/strategy, symbol, form fields, risk, notes, exchange."""
    tk = t.tk
    lines = [when(tk["t_placed"]),
             f"{mode} · {event} · {TS} · 15m",
             "",
             f"{t.sym} · {t.pos}"]
    if with_ticket:
        lines += t.block()
    lines += [""] + t.footer()
    if extra:
        lines += [""] + extra
    lines += ["", exchange_line(snap, t.sym, m)]
    return "\n".join(lines)


def short(mode: str, event: str, t: Ticket, body: list[str]) -> str:
    """A notice without the full ticket: time, header, symbol, then the body lines."""
    return "\n".join([when(t.tk["t_placed"]), f"{mode} · {event} · {TS} · 15m", "", f"{t.sym} · {t.pos}"] + body)


def cancel_entry_order(params: dict, sym: str, order_id: int) -> dict:
    """The runner's only write to the exchange: cancel one of Ed's entry orders that matches a
    ticket whose window has passed. Uses the trading key named in credentials.exchange."""
    from common.exchange import binance
    rw = str(params.get("credentials", {}).get("exchange", "binance/SERVER_TRADING_RW")).split("/")[-1]
    if rw not in binance.list_keys():
        raise RuntimeError(f"{rw}.env not present — cannot cancel; do it by hand")
    c = binance.Client(rw)
    c.sync_time()
    return c.cancel_order(sym, order_id)


def gtc_line(tk: dict, live_bars: int, bar_ms: int = 900_000) -> str:
    return "Expires: " + dt.datetime.fromtimestamp((tk["t_placed"] + live_bars * bar_ms) / 1000, TZ).strftime("%a %d %b %H:%M UTC")


# --------------------------------------------------------------- cycle ----
def cycle(params, tiers, mode: str, a) -> dict:
    alerts = params.get("alerts", {})
    manage = params.get("manage", {})
    book = alerts.get("book", "trading")
    to_main = alerts.get("to", "trading")
    to_crit = alerts.get("critical_to", "alerts")
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

    sent: list[str] = []
    errors: list[str] = []
    watch = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else [s for s, t in tiers.items() if t > 0]
    st = load_state()
    snap = exchange_snapshot(params)
    filters = data.symbol_filters()
    if not filters:
        errors.append("exchangeInfo unavailable: prices/sizes shown unrounded")
    import re as _re

    def emit(text: str, to: str = to_main, html: bool = False):
        if a.stdout:
            print(text + "\n" + "-" * 34)
            return
        try:
            telegram.send(text, to=to, book=book, html=html)
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

            T = Ticket(params, filters, sym, tk, risk_usd, tier, cap)
            side = "SELL" if tk["d"] == -1 else "BUY"
            record = dict(sym=sym, side=side, entry=T.price, stop=T.sl_trigger,
                          target=T.tp_limit, qty=T.qty, t=tk["t_placed"], ts=TS)   # what a report needs to recognise Ed's order
            m = matching(snap, sym, side, T.price, T.sl_trigger, T.tp_limit)

            # ---- guards on Ed's real orders (read-only unless manage.auto_cancel_expired) ----
            stops_visible = bool(snap) and snap.get("conditional_ok", True)   # never alert on what we could not read
            if m["position"] and manage.get("check_missing_stop", True) and not m["stop_orders"] and stops_visible:
                wkey = f"{key}:nostop:{int(time.time() // 900)}"      # at most once per cycle
                if not st.get(wkey):
                    p = m["position"]
                    emit(short(mode, "⚠ NO STOP ON EXCHANGE", T,
                               [f"your position {p['qty']:+g} @ {p['entry']:g} has no stop order.",
                                f"Ticket stop: {T.p(T.sl_trigger)}  ({T.trigger.lower()} → market). Place it now."]), to=to_crit)
                    st[wkey] = True; sent.append(f"NOSTOP {sym}")
            window_passed = age >= live_bars
            if m["entry_orders"] and not m["position"] and window_passed:
                for o in m["entry_orders"]:
                    if manage.get("auto_cancel_expired", False):
                        ckey = f"{key}:cancelled:{o['id']}"
                        if st.get(ckey):
                            continue
                        try:
                            cancel_entry_order(params, sym, o["id"])
                            emit(short(mode, "CANCELLED (auto)", T,
                                       [f"your order {o['id']} · {o['qty']:g} @ {o['price']:g} cancelled —",
                                        f"window of {live_bars} bars passed unfilled."]))
                            st[ckey] = True; sent.append(f"CANCELLED {sym}")
                            log_line({"event": "auto_cancel", "symbol": sym, "order_id": o["id"]})
                        except Exception as e:  # noqa: BLE001
                            errors.append(f"cancel {sym} {o['id']}: {e}")
                            emit(short(mode, "⚠ CANCEL FAILED", T, [f"order {o['id']}: {str(e)[:120]}", "Cancel it by hand."]), to=to_crit)
                    else:
                        xkey = f"{key}:cancelnow:{o['id']}"
                        if not st.get(xkey):
                            emit(short(mode, "CANCEL NOW", T,
                                       [f"your order {o['id']} · {o['qty']:g} @ {o['price']:g} is still resting",
                                        f"after the {live_bars}-bar window. Cancel it.",
                                        "(manage.auto_cancel_expired: true lets the runner do this)"]), to=to_crit)
                            st[xkey] = True; sent.append(f"CANCELNOW {sym}")

            if status == "placed" or (a.backfill and age <= a.backfill and not announced and status != "open"):
                if not announced:
                    emit(render(mode, "SETUP", T, snap,
                                [f"Window: {live_bars} bars from the FVG bar (paper limit, nothing placed)", gtc_line(tk, live_bars)], m=m))
                    st[key] = record; sent.append(f"SETUP {sym}")
                continue

            if status == "resting":
                if not announced:                      # first seen mid-window (e.g. after downtime)
                    emit(render(mode, "SETUP", T, snap, [f"Window: resting, {tk['bars_left']} bars left", gtc_line(tk, live_bars)], m=m))
                    st[key] = record; sent.append(f"SETUP {sym}")
                elif tk["bars_left"] <= 2 and not st.get(key + ":expiring"):
                    emit(render(mode, "EXPIRING", T, snap,
                                [f"Window: closes in {tk['bars_left']} bar(s) — cancel if unfilled", gtc_line(tk, live_bars)], m=m))
                    st[key + ":expiring"] = True; sent.append(f"EXPIRING {sym}")
                continue

            if status == "open":
                fkey = f"{sym}:fill:{tk['t_filled']}"
                if not st.get(fkey):
                    emit(render(mode, "FILLED (paper)", T, snap,
                                [f"Filled: {when(tk['t_filled'])} (paper)",
                                 f"Unrealised: {tk['unreal_R']:+.2f} R"], m=m))
                    st[fkey] = True; st.setdefault(key, record); sent.append(f"FILLED {sym}")
                continue

            if status == "closed" and announced:
                ckey = f"{sym}:closed:{tk['t_exit']}"
                if not st.get(ckey):
                    ev = "STOPPED (paper)" if tk["outcome"] == "stop" else "TARGET HIT (paper)"
                    emit(render(mode, ev, T, snap,
                                [f"Filled: {when(tk['t_filled'])}", f"Exit: {when(tk['t_exit'])}",
                                 f"Result: {tk['net_R']:+.2f} R  ({'stop, taker fee included' if tk['outcome']=='stop' else 'pool reached'})"], m=m))
                    st[ckey] = True; sent.append(f"{ev.split()[0]} {sym}")
                continue

            if status == "expired" and announced:
                xkey = f"{sym}:expired:{tk['t_expired']}"
                if not st.get(xkey):
                    emit(render(mode, "WINDOW EXPIRED · CANCEL", T, snap,
                                [f"Window: no fill within {live_bars} bars of the FVG bar — cancel the limit", gtc_line(tk, live_bars)], m=m))
                    st[xkey] = True; sent.append(f"EXPIRED {sym}")
                continue

    # heartbeat to syslog
    now = time.time()
    if not a.stdout and now - float(st.get("_last_heartbeat", 0)) >= hb_min * 60:
        ex = ("no key" if snap is None else snap.get("error", f"{len(snap.get('positions', []))} position(s), "
                                                      f"{len(snap.get('open_orders', []))} open order(s) via SERVER_RO"))
        emit(f"{mode} · HEARTBEAT · {TS}\n{dt.datetime.now(TZ):%a %d %b %H:%M UTC} · {len(watch)} symbols scanned · "
             f"{len(sent)} event(s) this cycle · book ${book_usd:,.0f} → ceiling ${cap:,.2f}\nexchange: {ex}"
             + (f"\nerrors: {'; '.join(errors)[:300]}" if errors else ""), to=to_sys, html=False)
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

---
id: TS04
name: TS04 Breakout Qulla 1D Binance USDCp
slug: TS04_Breakout_Qulla_1D_Binance_USDCp
version: 0.2
status: draft            # draft | backtesting | paper | shadow | live | retired
mode: PAPER              # must match config/params.yaml
live_approved:           # date, set by Ed only, must also appear in the change log
owner: Ed Le Feuvre
created: 2026-09-14
---

# TS04 Breakout Qulla 1D Binance USDCp

A daily-bar momentum-breakout entry in the form Kristjan Kullamägi
("Qullamaggie") trades in US equities, encoded for Binance USDC-margined
perpetuals. After a large prior advance and a tight multi-week consolidation, a
daily close above the consolidation high is bought with the stop at the breakout
bar's low; there is no target. Half the position is taken off on the first burst
of strength, the remainder is trailed on the 10-day moving average and closed on
the first daily close below it. Long-only, gated by a trend filter on BTC. The
counterparty is the range-bound seller who sold the top of the consolidation and
the short who faded the breakout; the edge, if any, is the fat right tail of
trend continuation that an open-ended exit harvests and a fixed-R bracket sells.

This strategy is logged from the strategy video review funnel (entry 10,
14 Sep 2026). It is the first trend-following entry in the standardised layout;
TS01 is a pool-to-pool mean-reversion trade and the two are structural opposites
by design.

## 1. Hypothesis

_Written 14 Sep 2026, before any test on crypto data. The only prior art seen is
third-party: millerrh's open-source "Qullamaggie Breakout V2" Pine script and a
Substack post reporting 87 trades / 8 years on BTC; both are single-asset,
in-sample, no multiplicity control, and are recorded as prior art in §9, not as
evidence._

Large winners move in stair-steps: a 30–100% advance, a sideways consolidation
while early buyers distribute and late buyers accumulate, then another leg.
The consolidation compresses range and positioning; the break of its high forces
the range seller to cover and pulls in momentum capital, and the move then
persists for weeks because the position-building is slow. The edge is not in
the entry's hit rate (Kullamägi reports 25–30%) but in the exit: an MA trail on
daily bars holds through the 5–20R runs that occur in bull regimes, which is
exactly the tail a 3R bracket sold in the EMA-crossover study
(`claude/ema-crossover-results.md`, "Variant: 1R/3R brackets").

Expected outcome, stated now: on 3 majors at daily resolution the sample will be
a handful of signals per symbol per year. The realistic result is a bull-regime
allocation rule that underperforms holding in strong years and earns its keep by
being flat in bears — the same shape as the EMA daily long-only finding — not a
levered edge that clears the t≈3.7 bar. If the result lands there, that is the
finding, and the strategy is filed with that label rather than refined.

## 2. Specification (the tested rules)

Any change here is a **MAJOR** version bump and invalidates §9.

| Element | Rule |
|---|---|
| Timeframe | 1D, Binance USDC-margined perpetual klines, UTC day (`fapi` live; `data.binance.vision` archive for history). The in-progress candle is always dropped. |
| Universe | BTCUSDC, ETHUSDC, SOLUSDC (`config/universe.yaml`). The other 18 TS01 symbols are a **declared secondary look** (§10), not part of the tested universe. |
| Session / hours | Daily close (00:00 UTC). |
| Market filter | BTCUSDC 10-day SMA above 20-day SMA at the signal close. Longs only when true. No short leg (parabolic short not encoded — see §10). |
| Prior move | Close on the signal bar ≥ 1.30× the lowest low of the prior 20–60 bars (a 30%+ advance inside 1–3 months). |
| Consolidation | The 10–40 bars before the signal bar (2–8 weeks) have a high-to-low range ≤ 25% of the consolidation high, and the consolidation high is below or equal to the prior-move high (a base, not a new leg). |
| Setup / entry | Daily **close** above the consolidation high, with the bar's close in the upper half of its range. Entry at that close (market/taker, next-bar open in the engine). |
| Stop | Low of the breakout bar. Setup rejected if (entry − stop) > 1.0 × ADR(20), where ADR = mean of (high − low)/close over the prior 20 bars. |
| Target / exit | No target. Half the position exits at the first of: close ≥ entry + 2R, or the 5th daily close after entry (if in profit; otherwise held). Stop on the remainder then moves to entry. Remainder exits on the first daily close below the 10-day SMA. |
| Management | As above; nothing else. No re-entry into the same consolidation. |
| Order validity | Not applicable — entry on close. |
| Cancel rules | Not applicable. |
| One-trade rules | One position per symbol. A symbol is blocked until its position closes. |
| Intrabar ambiguity | Stop checked before the 2R partial on the same bar, so a bar touching both is a loss. The trail exit is on close only; the hard stop is intrabar. |

### Encoding choices (judgement calls, so they are visible)

Kullamägi trades this discretionarily from a screener; every number below is
an encoding with no canonical value in his writing except where marked.

- Prior move ≥ 30% over 20–60 bars — his stated "30–100%+ in 1–3 months"; lower
  bound taken, upper bound not enforced.
- Consolidation length 10–40 bars — his "2–8 weeks" in trading days, kept in
  calendar days for a 7-day market (so 2–8 weeks = 14–56 days; **first variant
  worth declaring: crypto trades 7 days, equities 5**). Primary uses 10–40.
- Consolidation range ≤ 25% of its high — no canonical number; third-party
  scripts use 10% on equities; crypto ADR is ~2× equity ADR.
- Entry at daily close, not the opening-range high — there is no opening range
  in a 24/7 market. Stop at breakout-bar low replaces "low of day".
- ADR cap 1.0× — his stated rule.
- Partial: half at +2R or day 5 — his "1/3 to 1/2 after 3–5 days or 2–3R";
  midpoints taken.
- Trail: 10-day SMA close-only — his beginner default; 20-day is the declared
  secondary look.
- Market filter: BTC 10/20-day SMA — his "10-day vs 20-day on the indexes",
  BTC used as the index.

## 3. Parameters

The only place numbers are allowed to be explained. `config/params.yaml` must
match this table; `make check` diffs them.

| Key (params.yaml) | Value | Range allowed without MAJOR | Where used |
|---|---|---|---|
| `mode` | PAPER | PAPER / SHADOW (LIVE needs `live_approved`) | runner |
| `credentials.exchange` | binance/futures-trade | none | runner |
| `credentials.telegram` | telegram/rickyassist_bot | none | runner, weekly |
| `timeframe` | 1D | none — a new timeframe is a new strategy | engine, runner, pine |
| `risk_unit_usd` | 20 | set by charter: max(1% book, 20) | runner |
| `alerts.book` | trading | none | runner, weekly |
| `alerts.to` | trading | any name in the book | runner |
| `alerts.critical_to` | alerts | any name in the book | runner |
| `alerts.weekly_to` | digest | any name in the book | weekly |
| `filter.ma_fast` | 10 | none — MAJOR | engine, runner |
| `filter.ma_slow` | 20 | none — MAJOR | engine, runner |
| `setup.prior_move_pct` | 30 | none — MAJOR | engine |
| `setup.prior_move_bars_min` | 20 | none — MAJOR | engine |
| `setup.prior_move_bars_max` | 60 | none — MAJOR | engine |
| `setup.base_bars_min` | 10 | none — MAJOR | engine |
| `setup.base_bars_max` | 40 | none — MAJOR | engine |
| `setup.base_range_pct` | 25 | none — MAJOR | engine |
| `stop.adr_cap` | 1.0 | none — MAJOR | engine, runner |
| `stop.adr_bars` | 20 | none — MAJOR | engine |
| `exit.partial_r` | 2.0 | none — MAJOR | engine, runner |
| `exit.partial_bars` | 5 | none — MAJOR | engine, runner |
| `exit.trail_ma` | 10 | none — MAJOR (20 is the declared secondary) | engine, runner |

## 4. Execution & risk

| | |
|---|---|
| Risk unit (1R) | `risk_unit_usd` per charter; two half-lots of R/2 so the partial is a clean half. |
| Sizing rule | qty = R / (entry − stop). Rejected if stop > 1.0× ADR(20). |
| Order type — entry | Market at the daily close (taker). |
| Order type — stop | Stop-market, reduce-only, at the breakout-bar low; moved to entry after the partial. |
| Order type — target | Partial: reduce-only limit at entry + 2R (maker). Trail: market at close (taker). |
| Margin mode / leverage cap | Isolated; notional cap per charter. |
| Fee assumptions (maker / taker / funding) | Live tier verified for TS01: maker 0.00%, taker 0.0397%. **Funding must be modelled** — median hold is expected to be weeks, so funding is the dominant cost, unlike TS01. Use realised 8h funding from `fapi` history. |
| Slippage assumption | 0.02% on taker legs (daily close on majors). |
| Hard caps (notional, open positions, daily loss) | Max 3 open (one per symbol); notional and loss caps per charter. |

## 5. Alerting & lifecycle

Standard contract in `common/alerts/README.md`. Strategy-specific events:
`FILTER_ON` / `FILTER_OFF` (BTC 10/20 cross), `SETUP` (base qualified, high to
watch), `ENTRY`, `PARTIAL`, `STOP_TO_BE`, `TRAIL_EXIT`, `STOP_HIT`.

## 6. Artefact register

| Path | Role | Version | Notes |
|---|---|---|---|
| `config/params.yaml` | parameters | 0.1 | all §3 keys present |
| `config/universe.yaml` | symbol list | 0.1 | BTC, ETH, SOL |
| `pine/…` | TradingView scripts | | none yet; millerrh V2 is prior art, not an artefact |
| `src/runner.py` | live/paper runner | 0.1 | template |
| `src/backtest.py` | backtest engine | 0.1 | §2 on daily bars; archive klines + funding; `--trail`, `--base` for the declared secondaries |
| `results/2026-09-15-primary.json` | primary run | | trades, params, version |
| `src/weekly.py` | Sunday programme | 0.1 | template |
| `src/tests/test_replay.py` | acceptance | 0.1 | template |
| `systemd/TS04-runner.service` | long-running runner | 0.1 | |
| `systemd/TS04-weekly.service` | Sunday programme | 0.1 | |
| `systemd/TS04-weekly.timer` | Sun 06:00 UTC | 0.1 | |

## 7. Gate to live

| # | Condition | Cleared | Evidence |
|---|---|---|---|
| 1 | Out-of-sample result holds | | |
| 2 | Walk-forward consistent | | |
| 3 | Costs modelled at the account's real fee tier, incl. funding | | funding is material here — see §4 |
| 4 | ±20% parameter perturbation behaves | | |
| 5 | Enough trades (n and t stated) | | t≈3.7 bar inherited from the method notes. Stated now: 3 symbols × daily is unlikely to reach it. |
| 6 | 20 paper trades logged, within the validation band | | at this signal rate, 20 paper trades is 1–2 years — the gate may need a shadow-on-history substitute, to be agreed before testing |
| 7 | Sizing and max drawdown written in advance | | |
| 8 | Runner passes the replay acceptance tests | | |
| 9 | Trade-only API key, withdrawals off, IP-allowlisted, hard caps set | | |

## 8. Operations

| | |
|---|---|
| Runner unit | `TS04-runner.service` |
| Scheduled jobs | `TS04-weekly.timer` |
| Env file | `/etc/trading/TS04.env` |
| Logs | journald + `logs/` |
| Data dependencies | `common/data` daily klines + funding history |
| Restart policy | on-failure |

## 9. Evidence (backtests & paper results)

Variants tried so far: **3** (primary + the two declared secondaries).

### 2026-09-15 — primary run (§10 item 1) and declared secondaries (items 2, 3)

`src/backtest.py` v0.1. USDT-perp daily bars 2020-01 → 2026-09-14 (USDC perps
list Jan 2024; the two books track to bps, per the Aug 2026 venue test). Real
funding, taker 0.0397%, slip 0.02%, maker 0. IS to 2023-12, OOS 2024-01 on.
Result file `results/2026-09-15-primary.json`.

| Run | n | R/trade | t | win | ΣR | OOS R/trade (n) | median hold | rejected by ADR cap |
|---|---|---|---|---|---|---|---|---|
| Primary (trail 10, base 10–40) | 60 | +0.29 | 0.60 | 33% | +17.5 | −0.29 (25) | 3 d | 122 |
| Trail 20 | 56 | +0.32 | 0.70 | 36% | +17.6 | −0.21 (23) | 4 d | 121 |
| Base 14–56 | 46 | −0.12 | −0.54 | 35% | −5.6 | −0.15 (21) | 3 d | 104 |

Per symbol, primary: BTC −0.13R (n 18), ETH −0.07R (n 25), SOL +1.27R (n 17).

Reading:

1. **One trade is the result.** SOL 10 Aug 2021, +26.7R, held 34 days. Without
   it: n 59, −0.16R/trade, t −0.77. OOS is negative in all three runs.
2. **The stop does not transfer.** Breakout-bar low, capped at 1×ADR, stops out
   47 of 60 trades in a median of 3 days; the trail engaged 13 times. His
   "low of day" stop is tight relative to equity daily ranges; crypto daily
   ranges (median ADR 5.9%) chew through it before the trend can show.
3. **The ADR cap is doing most of the selecting.** 122 of 182 qualifying
   breakouts were rejected (median stop 8.0%). What survives is the quiet
   breakout, which is also the one least likely to run.
4. Funding cost 0.07R/trade — small only because the holds are short.
5. Lands where §1 said it would: a trend-continuation entry whose return in
   crypto majors is the asset's, not the setup's (B&H over the window: BTC
   +986%, ETH +1,825%, SOL +3,039%).

Status stays **draft**. Items 4 and 5 of §10 not yet run. The one structural
observation worth a new pre-registered hypothesis (not a tune): a stop at the
base low rather than the breakout-bar low changes the trade's shape from
"tight stop, rare tail" to "wide stop, fewer R per winner" — a different trade,
to be declared as such before running.

Prior art (not evidence): millerrh, "Qullamaggie Breakout V2", TradingView
open-source Pine; Substack "I tested Minervini's & Qullamaggie's strategy on
Bitcoin" (Oct 2025) — 87 trades / 8 years / BTC only / in-sample / no costs
stated. Kullamägi's own rules: qullamaggie.com, "3 timeless setups" (Apr 2021)
and "How to master a setup: Episodic Pivots" (Nov 2021).

## 10. Open questions & pre-registered research

Write the question and the expected answer **before** running.

1. **Primary run.** Spec as written, BTC/ETH/SOL, 2020-01 to present, split
   in-sample to 2023-12 / out-of-sample 2024-01 on. Expected: positive gross
   expectancy driven by 2020–21 and 2024; net of funding materially lower;
   t below 2 on n ≈ 40–80.
2. **Trail 20-day SMA** (declared secondary). Expected: fewer whipsaws, similar
   total R, larger drawdown per trade.
3. **Consolidation length 14–56 bars** (7-day-week variant). Expected: fewer
   signals, no change in expectancy sign.
4. **Universe — the other 18 TS01 symbols.** Expected, per the TS01 universe
   finding: dilution toward zero. Recorded as one look with multiplicity 18.
5. **Benchmark.** Same-period buy-and-hold and the EMA 20/50 daily long-only
   filter on the same symbols. The question is whether the base + ADR cap adds
   anything over the simpler trend filter already studied.
6. **Not encoded, not to be tested without a new hypothesis:** the episodic
   pivot (needs a news/earnings catalyst — no crypto analogue defined) and the
   parabolic short (a separate entry family; would be its own TSnn).

## Change log

| Date | Version | Section | Change | Files |
|---|---|---|---|---|
| 2026-09-15 | 0.2 | §6, §9 | Backtest engine written; primary and two declared secondaries run and recorded. No spec change. | `src/backtest.py`, `results/2026-09-15-primary.json`, `STRATEGY.md` |
| 2026-09-14 | 0.1 | all | Created from template; §1–§4, §7 notes, §9 prior art, §10 pre-registration written before any test | `STRATEGY.md`, `config/universe.yaml`, `config/params.yaml` |

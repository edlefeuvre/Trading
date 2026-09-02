---
id: TS01
name: TS01 CHoCH ICT 15m Binance USDCp
slug: TS01_CHoCH_ICT_15m_Binance_USDCp
version: 1.9
status: paper            # draft | backtesting | paper | shadow | live | retired
mode: PAPER              # must match config/params.yaml
live_approved:           # date, set by Ed only, must also appear in the change log
mandate:                 # Paperclip project this system reports into, e.g. CRYPTO-binance-<Type> (Board naming convention)
owner: Ed Le Feuvre
created: 2026-09-02
---

# TS01 CHoCH ICT 15m Binance USDCp

The ICT variant of the change-of-character entry — **sweep → CHoCH → FVG** — on
Binance USDC-margined perpetuals, 15-minute bars. After a liquidity sweep and a
CHoCH confirmed on close, a Fair Value Gap (FVG, the displacement gap) printing in
the CHoCH direction gives the entry: a resting limit at the gap, the stop at the
sweep extreme, and the exit at the next liquidity pool. The engine that produced the evidence in §9 is
the **locked ICT base with pool exit**; this document is the contract between
that engine, the Pine alerts, and the runner ("Ricky AI") on the server.

This is the first strategy in the standardised layout. Its folder name is the
naming convention: `TS01` (strategy number) · `CHoCH_ICT` (entry family and
variant) · `15m` (timeframe) · `Binance` (platform) · `USDCp` (product universe —
USDC perps). The same entry on another timeframe would be a new strategy with a
new number, e.g. `TS05_CHoCH_ICT_1H_Binance_USDCp`.

## 1. Hypothesis

_Written 28–31 Aug 2026, before the pool-exit evidence in §9 was run; the
CHoCH→FVG bracket variants tested earlier (see `claude/choch-fvg-15m-results.md`)
had all landed at zero._

After a sweep of a resting liquidity pool, the side that was stopped out is
absent and the side that triggered the sweep is positioned; a change of
character in the 15m structure marks the moment their positioning starts to be
unwound toward the *next* pool. The counterparty is the trader whose stops were
just run and the late-breakout entrant who bought the sweep. The exit is not a
fixed R multiple but the visible resting size on the other side — "resting size
*is* the draw" — so the strategy is a pool-to-pool transfer, not a trend bet.

Corollary tested 31 Aug: if price reaches the target pool **before** the resting
entry fills, the draw is gone and the setup is void (pool-consumed cancel).

## 2. Specification (the tested rules)

Any change here is a **MAJOR** version bump and invalidates §9.

| Element | Rule |
|---|---|
| Timeframe | 15m, Binance USDC-margined perpetual klines (`fapi` live; `data.binance.vision` archive for history). The in-progress candle is always dropped. |
| Universe | The 21 USDC.p symbols in `config/universe.yaml` — the `SYMBOLS` list of `choch_sizes.py`. Each carries a **tier multiplier** 1.0 / 0.5 / 0 set by the Sunday programme (§8a); 0 = not traded and not scanned. |
| Session / hours | All hours. |
| Structure | Fractal pivots, width k = 5, strict unique extreme over the 2k+1 window, usable only k bars after they print. Bullish CHoCH: two descending pivot highs (A then lower B) and a **close** above B; bearish mirrored. |
| Sweep | Between pivot B and the CHoCH bar, the extreme L (lowest low for a long) must break the last pivot low *before* it, and price must **close back through that level within 4 bars** of the sweep bar. No sweep → no setup. |
| FVG (entry level) | The first Fair Value Gap printing on the CHoCH bar or the two after it: for a long, `low[j] > high[j-2]`. Entry = gap midpoint `(high[j-2] + low[j]) / 2`. |
| Discount filter | Locked. The FVG midpoint must lie in the **discount half** of the range from the sweep extreme L to the highest high between the sweep bar and the FVG bar (long; mirrored for short). Otherwise no setup. |
| Entry | Resting limit at the FVG midpoint, **maker, Post-Only** (the watcher assumes a fill when price touches it). |
| Stop | At the sweep extreme L. |
| Target / exit | **Pivot A** — the swing that began the structure — is the pool. Resting reduce-only limit. Setup discarded if A is not beyond the entry. Exit is stop or target, nothing else. |
| Management | None. No breakeven, no partials, no trail. |
| Order validity (GTC window, anchor) | 32 bars from the **FVG bar**. Unfilled at expiry → cancel. |
| Cancel rules | Window expired → cancel. **Pool-consumed cancel: researched 31 Aug (§9), NOT implemented in the live watcher; to be added in the runner and then flipped on in `params.yaml`.** |
| One-trade rules | One position per symbol: a filled setup blocks new setups until it closes (`busy_until`). |
| Intrabar ambiguity | Stop checked before target on every bar, so a bar touching both is a loss. The fill bar itself can stop out. |
| Costs in the engine | 0.04% taker on stop-outs only (`fee = 0.0004 × L / risk` in R); maker entry and target free; **funding not modelled**. |

### Encoding choices (judgement calls, so they are visible)

Each is an encoding of an ICT idea with no canonical number, so each is a hidden
variant. Read from `choch_watch.py` / `choch_sizes.py` on 2 Sep 2026:

- Pivot width **k = 5**, strict unique extreme (ties disqualify a pivot).
- Sweep reclaim window **4 bars**; FVG window **CHoCH bar + 2**; GTC **32 bars**
  from the FVG bar (encoding choices, not ICT numbers — the late-fill study in §10
  tests the last).
- **Discount-only** entries — the single largest filter after the sweep.
- Target = pivot A, the structural origin, not a book-depth reading.
- Tier rule (Sunday programme): 1.0 if mean net R > 0 in both the prior period
  and the last 12 months; 0.5 if in one; 0 if neither or < 12 months of history.
  This selects 21 symbols on the sign of two small-sample means — a look with
  multiplicity 21 × 2 that the method notes warn about. Kept because it only
  ever sizes *down* from the charter ceiling; recorded as a variant.
- Engine functions are **copied verbatim** between watcher and sizing script
  today; migration replaces the copies with one `common/engine` import.

## 3. Parameters

The only place numbers are allowed to be explained. `config/params.yaml` must
match this table; `make check` diffs them.

| Key (params.yaml) | Value | Range allowed without MAJOR | Where used |
|---|---|---|---|
| `mode` | PAPER | PAPER / SHADOW (LIVE needs `live_approved`) | runner |
| `credentials.exchange` | binance/SERVER_TRADING_RW | none | runner — order placement; unused in PAPER (v0 cannot place orders) |
| `credentials.exchange_ro` | binance/SERVER_RO | none | runner — reconciliation read → `results/holdings.json` |
| `credentials.telegram` | telegram/rickyassist_bot | none | runner, weekly — `.config\telegram\rickyassist_bot.env` |
| `timeframe` | 15m | none — MAJOR | engine, runner, pine |
| `poll_seconds` | 30 | 10–60 | runner |
| `entry.gap_window_bars` | 2 | none — MAJOR | engine, runner, pine — FVG must print on CHoCH bar or +2 |
| `entry.sweep_reclaim_bars` | 4 | none — MAJOR | engine, runner |
| `entry.discount_only` | true | none — MAJOR | engine, runner |
| `entry.gtc_anchor_bar` | fvg | none — MAJOR | engine, runner |
| `structure.pivot_k` | 5 | none — MAJOR | engine, runner, pine |
| `data.history_bars` | 1500 | 1000–3000 | runner |
| `entry.gtc_window_bars` | 32 | none until §10 study reports | engine, runner |
| `entry.post_only` | true | none | runner |
| `exit.type` | pool | none — MAJOR | engine, runner |
| `exit.pool_consumed_cancel` | false | flip to true only when the runner implements it (MAJOR) | runner — researched, not live |
| `exit.breakeven` | false | none — MAJOR | engine, runner |
| `orders.time_in_force` | GTC | none | runner — ticket |
| `orders.trigger_price` | mark | mark / last | runner — TP/SL trigger price type on the ticket |
| `orders.reduce_only` | true | none | runner — ticket |
| `stop.order_type` | stop_market | stop_market / stop_limit_buffered | runner |
| `stop.limit_buffer_ticks` | 3 | 1–10 (only if stop_limit_buffered) | runner |
| `target.order_type` | take_profit_limit | none | runner — ticket |
| `target.trigger_offset_ticks` | 1 | 1–2 | runner |
| `risk.unit_usd` | 20 | set by charter: max(1% book, 20) | runner, journal |
| `risk.symbol_scale` | see config/universe.yaml | 0 / 0.5 / 1.0 per symbol, set by the Sunday programme, applied by Ed | runner — tier multipliers of the ceiling |
| `risk.book_usd` | 356 | updated at the Sunday review | runner — ceiling = max(1% × book, 20) |
| `weekly.tier_rule` | sign_two_periods | none — MAJOR | weekly |
| `weekly.lookback_months` | 12 | none — MAJOR | weekly |
| `risk.leverage_cap` | 20 | 5–20 | runner |
| `risk.margin_mode` | isolated | none | runner |
| `risk.max_open_positions` | 3 | 1–3 | runner |
| `risk.max_notional_usd` | 6000 | ≤ 6000 | runner |
| `risk.daily_loss_stop_r` | 3 | 2–3 | runner |
| `fees.maker` | 0.0000 | re-run required if account tier differs | engine |
| `fees.taker` | 0.0004 | re-run required if account tier differs | engine |
| `fees.funding` | none | model it before any LIVE decision | engine — **not modelled today** |
| `alerts.recompute_r_on_fill` | true | none | runner |
| `alerts.book` | trading | none | runner, weekly — `.config\telegram\trading.env`, from Bitwarden item `telegram/trading` |
| `alerts.to` | trading | any name in the book | runner — lifecycle alerts (`TELEGRAM_TO_TRADING`) |
| `alerts.critical_to` | alerts | any name in the book | runner — CANCEL NOW / STATE MISMATCH / STOPPED / BLOCKED also here |
| `alerts.weekly_to` | digest | any name in the book | weekly — Sunday R-factor review |
| `alerts.approvals_to` | approvals | any name in the book | runner — requests for Ed's decision |
| `alerts.syslog_to` | syslog | any name in the book | runner — heartbeat and errors to Ricky Logs / Systems |
| `alerts.heartbeat_minutes` | 60 | 30–240 | runner |
| `coverage.max_age_days` | 7 | 7–14 | runner (refuses symbols with stale coverage) |
| `weekly.min_trades_for_r` | 30 | 20–50 | weekly report (R factor shown as provisional below this) |

## 4. Execution & risk

| | |
|---|---|
| Risk unit (1R) | $20 ceiling per the charter (greater of 1% of the ring-fenced book and $20, so $20 binds until the book passes $2,000). Per-symbol scale may size **down** (ETH 50% → $10), never up. |
| Sizing rule | `qty = unit × scale / |entry − stop|`, computed from the **planned** entry. On any taker fill, recompute `qty = unit / |fill − stop|` and adjust before walking away. Journal the **actual** R, never the intended $20. |
| Order type — entry | Limit, Post-Only, GTC. An order that would cross the book is one the strategy never asked for. |
| Order type — stop | Stop-market, reduce-only (what the 0.04% taker charge in the backtest models). If stop-limit is used, the limit sits on the **far** side of the trigger (short: limit above trigger) so a gap cannot leave it unfilled. |
| Order type — target | Reduce-only limit resting from fill. TP trigger one tick the right side of entry (short: entry − 1 tick) so the limit is armed from the start, not parked beyond the market. |
| Margin mode / leverage cap | Isolated. Leverage capped so liquidation sits well beyond the widest stop — ~10–20x at 0.5–1.5% stops. R is set by the stop, not the leverage. |
| Fee assumptions (maker / taker / funding) | Backtest: maker 0% / taker 0.04% / actual funding. **Open item:** verify the account's real tier; if maker is 0.02%, entry + TP cost ≈ 0.055R against a 0.72% stop, roughly half the filtered edge — re-run §9 at 0.02 / 0.05 before any LIVE decision. |
| Slippage assumption | Zero on maker fills (Post-Only guarantees price); stop-market pays taker and may gap. |
| Hard caps (notional, open positions, daily loss) | max 3 open, max $6,000 total notional, stop for the day at −3R. Trade-only API key, withdrawals disabled, IP-allowlisted. |

Ticket fields are emitted in Binance's own order and labels (`Trigger Price`
then `Price`) so the ticket can be keyed without translation.

## 5. Alerting & lifecycle

Full contract: `common/alerts/README.md` (the Ricky AI Telegram spec of 2 Sep
2026). Today's watcher sends `SETUP` and `IN TRADE` only, with no mode prefix,
and computes "IN TRADE" from price passing its hypothetical limit — it has never
spoken to the exchange, so every position it has reported was paper. Strategy-
specific summary of what the runner must do instead:

**The one rule:** a message must never assert a position that has not been
confirmed against the exchange in the same cycle. Reconcile first, every cycle;
on mismatch emit `⚠ STATE MISMATCH`, adopt the exchange's answer, do nothing
else that cycle.

Every message: `MODE · EVENT · TS01 <variant>` then symbol, side, timeframe and
the **signal timestamp**. Events, in lifecycle order:

`SETUP` → `ARMED` (LIVE only, after exchange ack) → `FILLED` (R recomputed on
actual fill, role and drift stated) → `IN POSITION` heartbeat (unrealised R from
the fill; omitted, not zeroed, if no fill) → one of `TARGET HIT` / `STOPPED` /
`POOL CONSUMED · CANCEL` (before fill only) / `WINDOW EXPIRED · CANCEL`.
Also `EXPIRING` (30 min before window end) and `BLOCKED` (margin insufficient at
ticket time).

Stop, target, pool and window are evaluated on **every bar close**, not on a
timer and not on request.

Acceptance replays (must pass before the runner is trusted — cases live in
`results/acceptance/`):

1. 31 Aug UNI — `STOPPED` at 16:43, never `IN TRADE` afterwards.
2. 31 Aug SOL — `POOL CONSUMED · CANCEL`, then `WINDOW EXPIRED`, never a fill.
3. 1 Sep LINK — `ARMED`, `FILLED` MAKER drift 0.00%, `STOPPED` −1.031R with the mixed-role fee breakdown.
4. 1 Sep AVAX — `POOL CONSUMED · CANCEL` on the signal bar; any continued papering reads `PAPER`.
5. 2 Sep ETH — `POOL CONSUMED · CANCEL` at 11:15 and **no message asserting a live position thereafter**. If only one test passes, it is this one.

## 6. Artefact register

Every file that implements this strategy. If a file is not in this table it is
not part of the strategy. "Migrate from" marks code that exists on the server
today under another name and must be moved here in one commit with a change-log
row.

| Path | Role | Version | Notes |
|---|---|---|---|
| `config/params.yaml` | parameters | 1.0 | §3 is its documentation |
| `config/universe.yaml` | the 21 symbols with tier multipliers | 1.7 | adding a symbol is MAJOR; tiers change only via the Sunday programme + Ed |
| `pine/TS01_CHoCH_alerts.pine` | TradingView indicator: sweep → CHoCH → gap bar, alert on bar close | — | **migrate from:** current TradingView script(s). Header comment must carry `TS01 v<version>`. Alerts are for eyes and the journal; the runner detects independently. |
| `src/runner.py` | PAPER runner, one cycle per invocation | 1.8 | `choch_watch.py` migrated 2 Sep 2026. Detection unchanged (imports `common/engine`); adds MODE prefix, FILLED/STOPPED/TARGET HIT/EXPIRING/WINDOW EXPIRED events, SERVER_RO reconciliation read, `results/holdings.json`, `results/state.json` (seeded from `~/.choch-watch/state.json` on first run), `logs/TS01-runner.jsonl`, hourly HEARTBEAT to syslog. Refuses LIVE/SHADOW. |
| `src/weekly.py` | the Sunday programme (§8a) | 1.8 | `choch_sizes.py` migrated 2 Sep 2026 on `common/engine` + `common/data`. Writes `results/weekly/<date>/r_factors.csv` + `summary.md`, sends to Digest, proposes tier changes; `--apply` rewrites `universe.yaml` tiers for Ed to commit. |
| `src/backtest.py` | backtest entry point | 1.0 skeleton | calls `common/engine` with this folder's config |
| `src/tests/…` | tests | 1.8 | `test_engine_equivalence.py` proves `common/engine` reproduces the pre-migration functions bar-for-bar on 40 synthetic series; `test_runner_smoke.py` runs three PAPER cycles with mocked data (prefix, tier line, exchange line, dedupe, closures once); `test_replay.py` awaits the five acceptance cases |
| `systemd/TS01-runner.service` | Linux variant (not used on the Windows PC) | 1.0 | |
| `systemd/TS01-weekly.service` | Linux variant | 1.1 | |
| `systemd/TS01-weekly.timer` | Linux variant | 1.1 | |
| `../../deploy/windows/register-ts01-runner.ps1` | Task Scheduler task `TS01-runner`, every 15 min at :00:30 | 1.8 | replaces `CHoCH watcher` once both agree for a few days |
| `../../deploy/windows/register-ts01-weekly.ps1` | Task Scheduler task `TS01-weekly`, Sundays 08:00 local | 1.8 | |
| `results/` | `state.json` (dedupe + heartbeat clock), `holdings.json` (exchange snapshot), `weekly/YYYY-MM-DD/`, `coverage.csv`, `acceptance/` | | small JSON/CSV/MD only; klines cache lives in `%USERPROFILE%\.config\trading-data` |

Shared code this strategy depends on (documented in `common/*/README.md`, and
any behavioural change there adds a row to this file's change log):
`common/engine/ict_base.py` (the `ENGINE (verbatim)` block of `choch_watch.py`/`choch_sizes.py`, moved 2 Sep 2026 with the encoding choices as named parameters; equivalence test in `src/tests`), `common/exchange` (Binance
USDC-perp client, reconciliation), `common/alerts` (Telegram), `common/data/binance_klines.py` (live `klines`/`klines_paged` and archive `history`/`month`/`day`, moved 2 Sep 2026; cache under `%USERPROFILE%\.config\trading-data`), `common/exchange/binance.py` (read-only client, `--test` audit).

## 7. Gate to live

| # | Condition | Cleared | Evidence |
|---|---|---|---|
| 1 | Out-of-sample result holds | — | §9: pool-consumed filter is look #2 on the base case; OOS split not yet reported separately |
| 2 | Walk-forward consistent | — | not run |
| 3 | Costs modelled at the account's real fee tier, incl. funding | — | tier unverified; re-run at 0.02/0.05 pending |
| 4 | ±20% parameter perturbation behaves | — | not run (gtc window, gap window, k) |
| 5 | Enough trades (n and t stated) | — | n=351 kept, t=+1.2 — promising, not proven |
| 6 | 20 paper trades logged, within the validation band | — | phase 0 not cleared; band: worst −9.1 / 10th −2.8 / median +1.2 / 90th +16.6 / best +23.5 over 170 rolling windows; stop only below −9R |
| 7 | Sizing and max drawdown written in advance | 2026-08-30 | Charter clause 3; §4 above |
| 8 | Runner passes the replay acceptance tests | — | §5 cases 1–5 |
| 9 | Trade-only API key, withdrawals off, IP-allowlisted, hard caps set | — | caps in §3; key hygiene to confirm |

The live UNI short of 31 Aug and the LINK short of 1 Sep were taken **ahead of
this gate**. UNI had been run through the engine as one of the 21 pairs, but
its R factor was not in front of the trade at the time — which is what §9a fixes. Recorded as
deviations in the journal; they do not count toward row 6.

## 8. Operations

| | |
|---|---|
| Runner | Windows Task Scheduler task `TS01-runner`: `python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.runner` from `%USERPROFILE%\Repos\Trading`, every 15 min at hh:00:30 / 15:30 / 30:30 / 45:30 (30 s after bar close so the closed candle is final), 10-min limit, 3 restarts a minute apart. Registered by `deploy\windows\register-ts01-runner.ps1`. Runs alongside `CHoCH watcher` until they agree, then the old task is disabled. |
| Scheduled jobs | `TS01-weekly` task, Sun 06:00 UTC → `src/weekly.py` (§8a); `TS-secrets-sync` hourly (optional) |
| Credentials | by provider under `%USERPROFILE%\.config\`: `binance\SERVER_RO.env` (Enable Reading only — reconciliation, reports, Sunday programme), `binance\SERVER_TRADING_RW.env` (Enable Futures only — order placement, created only after the paper gate), `telegram\rickyassist_bot.env`. The Investment Book uses its own `SERVER_INVEST_RW` (margin loan / options), never shared with Trading. No server key has withdrawals or transfers. All IP-restricted. Bitwarden is the master; `sync-secrets.ps1` refreshes the files. |
| Logs | `logs/TS01-runner.jsonl` — one JSON line per cycle (symbols, events sent, errors, exchange counts) plus reconcile failures; Task Scheduler history for the process itself |
| Data dependencies | `common/data` cache of 15m klines + funding for every symbol in `universe.yaml`; the weekly job extends the cache to the latest complete Saturday 23:45 UTC bar |
| Restart policy | Each cycle is a fresh process: it reconciles (reads the exchange with SERVER_RO) before evaluating; `results/state.json` only remembers what has been announced |
| Paperclip (later) | The units are the contract: one process per strategy, one job per timer, env from `/etc/trading/TS01.env` |

Automation order, decided 31 Aug: detection → paper logging (no placement) →
lifecycle alerts (pool consumed, window expiring) → order placement only after
the paper gate.

### 8a. The Sunday programme (`TS01-weekly.timer` → `src/weekly.py`)

Exists today as `choch_sizes.py` (prints the tier table; `--write` applies it to
`sizes.json`). Migrates to `src/weekly.py`. Runs Sunday 06:00 UTC, before the
Sunday pass. It is the only process allowed to change §9a, and it never applies
multipliers itself: it **proposes** them to the Digest topic and Ed applies with
`weekly --apply`, which writes `results/sizes.json` and a change-log row. Steps:

1. **Roll the dataset forward** to the last complete bar of Saturday; record the
   dataset end date and bar count per symbol.
2. **Re-run the locked engine** on every symbol in `universe.yaml` at the
   current spec version and `params.yaml`, base case and pool-consumed-filtered
   case, real funding, fee model from §3.
3. **Write results** to `results/weekly/YYYY-MM-DD/`: `r_factors.csv` (one row
   per symbol — see columns below), `summary.md` (the review note), and
   `run.json` (engine version, params hash, dataset window, wall time).
4. **Diff against last week**: per symbol, change in net R/trade, n, t, and
   whether the symbol crossed any of the review thresholds below.
5. **Update the coverage register** (§9a) from `r_factors.csv` and append one
   line to the coverage history in `results/coverage.csv`.
6. **Send the review** to Ed: Telegram message `PAPER · WEEKLY · TS01` with the
   headline table (symbol, net R/trade filtered, n, t, Δ vs last week, flag),
   and mirror `summary.md` to the Trading project as `claude/TS01-weekly-latest.md`
   (the previous week's file is kept under its date).
7. **Fail loudly**: if any symbol's data is short, the engine errors, or the
   params hash differs from the one in the last change-log row, send
   `⚠ WEEKLY FAILED` with the reason and leave §9a untouched.

`r_factors.csv` columns: `symbol, dataset_start, dataset_end, bars, n_setups,
n_kept, n_discarded, net_r_base, net_r_kept, net_r_discarded, t_kept, win_pct,
median_stop_pct, median_bars_to_fill, funding_r_per_trade, provisional
(n_kept < weekly.min_trades_for_r), flag`.

Review flags (what Ed is being asked to look at, not decisions the job makes):
`NEW` first run for the symbol; `SIGN FLIP` net R kept changed sign;
`DEGRADED` net R kept fell by more than 0.10R or t fell below 1.0; `STALE DATA`
dataset end older than 8 days; `THIN` provisional. **The job never changes
`universe.yaml`, `params.yaml` or the spec.** Adding or removing a symbol is
Ed's decision at the Sunday pass, recorded in the change log.

### 8b. Holdings

The runner keeps `results/holdings.json`, rewritten after every reconciliation
cycle from the exchange's answer, never from internal belief: open positions
(symbol, side, qty, entry fill, stop and target order ids, 1R actual, unrealised
R, funding paid, bars held), open resting orders (symbol, side, price, qty,
window expiry, pool status), and margin (mode, used, available). The Sunday
programme reads it and puts a holdings block at the top of `summary.md`, so the
review starts from what is actually held. Investment-book positions (the
loans/BTC/hedge) are **not** in this file; they are not the strategy's.

## 9. Evidence (backtests & paper results)

Newest first. Running variant count for the CHoCH family: **~250
configurations** across the FVG-bracket, structure-exit, USDC/USDT and
pool-exit work (Aug 2026). Any future winner must clear well above t = 2.


### 9a. Coverage register (maintained by the Sunday programme only)

One row per symbol in `universe.yaml`. A symbol without a row, or with a run
older than `coverage.max_age_days`, is not tradeable and the runner will skip its
signals with a `BLOCKED · NO COVERAGE` alert. Tiers below are from
`.choch-watch/sizes.json` (written by `choch_sizes.py --write` on 31 Aug 2026);
the R columns are filled by the first run of `src/weekly.py`, which is
`choch_sizes.py` migrated.

| Symbol | Dataset window | Last run | Spec ver | Tier | Net R (prior / 12m) | n | Flag |
|---|---|---|---|---|---|---|---|
| SOLUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 1 | — / — (run `weekly` to fill) | — | positive both |
| UNIUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 1 | — / — (run `weekly` to fill) | — | positive both |
| LTCUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| BTCUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| WLDUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| XRPUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| LINKUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| DOGEUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| ETHUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| ADAUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| ORDIUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| AVAXUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| 1000PEPEUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| BCHUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| AAVEUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0.5 | — / — (run `weekly` to fill) | — | positive one |
| ZECUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0 | — / — (run `weekly` to fill) | — | under 12m history; eligible 19 Nov 2026 |
| BNBUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0 | — / — (run `weekly` to fill) | — | negative both periods |
| ENAUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0 | — / — (run `weekly` to fill) | — | negative both periods |
| NEARUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0 | — / — (run `weekly` to fill) | — | negative both periods |
| FILUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0 | — / — (run `weekly` to fill) | — | negative both periods |
| SUIUSDC | 2024-01 → 2026-08-31 | 2026-08-31 | 1.x (watcher) | 0 | — / — (run `weekly` to fill) | — | negative both periods |

**2026-09-02 · pool-consumed filter, later look** — reported in the Ricky AI
spec as kept **+0.163R** vs discarded −0.058R, n=522. Engine run not yet filed
under `results/`; reconcile with the 31 Aug figures below before citing either.

**2026-08-31 · pool-consumed filter, first look** — the nine symbols in the book
that day (later widened to 21), 764 setups, dataset 2024-01-04 → present, maker 0% / taker 0.04% on stops. Kept 351
at **+0.112R (t = +1.2)** vs discarded 413 at −0.058R; unfiltered baseline
+0.020R. ETH +0.148 → +0.527, SOL +0.222 → +0.450. No hindsight required.
**Verdict: promising, not proven.** Look #2 on the base case.

**2026-08-31 · time-to-fill context** — median 5 bars (75 min), 25th pct 2,
75th 12, 90th 22 bars. The 13–32 bar bucket is roughly the slowest quarter.

**2026-08-30 · validation band** — 170 rolling 20-trade windows of the base
case: worst −9.1R, 10th −2.8, median +1.2, 90th +16.6, best +23.5. 38% of
windows negative.

**2026-08-28/29 · CHoCH→FVG bracket family (superseded entry)** — seven exit /
venue variants, all within ±0.1R of zero at 0.04% taker; canonical
external-structure definition did not change the answer; USDC vs USDT identical
to noise. File closed on that entry; TS01 uses the pool exit instead. Detail:
`claude/choch-fvg-15m-results.md`.

**Paper / live rehearsal log** — 31 Aug SOL (never filled, pool consumed,
correctly skipped); 31 Aug UNI short LIVE outside universe, taker fill re-based
1R to $12.51, stopped; 1 Sep LINK short LIVE, maker fill, stopped −1.031R;
1 Sep AVAX pool consumed on signal bar; 2 Sep ETH pool consumed 11:15,
cancelled. Full records in the trading journal artifact.

## 10. Open questions & pre-registered research

**Late fills and the GTC window** (declared 31 Aug 2026, not yet run).
Question: does expectancy decay with bars-from-gap-to-fill, and is the decay
pool consumption rather than time? Primary: net R in buckets 0–2 / 3–5 / 6–12 /
13–32 bars. Secondary: same buckets after the pool-consumed filter. Tertiary:
net R and n at windows 2h / 4h / 8h / 12h / 24h. Declared expectation: decay
exists and is mostly pool consumption, so the window needs no change. Look #3.

**Fee tier** — verify, then re-run the filtered base case at maker 0.02% /
taker 0.05%.

**Round-number pools** — the 5.00 UNI worry logged at +1.1R. Under the
doctrine, thick resting size is the argument *for* the target. Revisit only
with a pre-registered test, not from one trade.

## Change log

Newest first. Every commit touching `pine/`, `src/`, `config/` or shared engine/
exchange code adds a row. The hook checks that this table changed.

| Date | Version | Section | Change | Files |
|---|---|---|---|---|
| 2026-09-03 | 1.9 | §3, §5 | Every notification now carries a Binance-form ticket block (Order / Price / Size / Take Profit trigger→Limit / Stop Loss trigger→Market, reduce-only, margin, leverage) with price and size rounded to the symbol's real tick and lot size from exchangeInfo (cached daily). `orders.*` parameters added. | `src/runner.py`, `common/data/binance_klines.py`, `config/params.yaml` |
| 2026-09-02 | 1.8 | §3, §6, §8 | Runner v0: `choch_watch.py` migrated into `src/runner.py` on top of `common/engine`, `common/data`, `common/alerts`, `common/exchange`. PAPER only; MODE prefix on every message; new lifecycle events; SERVER_RO reconciliation read and `holdings.json`; JSONL cycle log; hourly heartbeat. Engine equivalence proven by test. Task Scheduler registration script for Windows. | `src/runner.py`, `src/tests/*`, `config/params.yaml`, `common/engine/ict_base.py`, `common/data/binance_klines.py`, `common/exchange/binance.py`, `deploy/windows/register-ts01-runner.ps1` |
| 2026-09-02 | 1.7 | §2, §3, §5, §6, §8a, §9a, frontmatter | Spec rewritten from the live code (`choch_watch.py`, `choch_sizes.py`): sweep reclaim ≤4 bars, discount-only filter, target = pivot A, stop-before-target, fee on stops only, funding not modelled. Pool-consumed cancel marked researched-not-live and set false. Universe = the 21 `SYMBOLS` with tiers from `sizes.json`; coverage register populated with tiers. `mandate:` field added (Board naming convention). | `STRATEGY.md`, `config/params.yaml`, `config/universe.yaml`, `docs/conventions/*` |
| 2026-09-02 | 1.6 | name | Timeframe added to the naming convention: folder `TS01_CHoCH_ICT_15m_Binance_USDCp`. `make check` now requires the TF token to equal `params.timeframe`. | folder rename, `STRATEGY.md`, `config/params.yaml` |
| 2026-09-02 | 1.5 | name, §2 | Renamed to `TS01_CHoCH_ICT_15m_Binance_USDCp` (ICT variant: sweep → CHoCH → FVG); FVG vocabulary adopted from the live watcher; pivot width k=5 confirmed from `choch_watch.py`. | `STRATEGY.md`, folder rename, `systemd/*`, `config/*` |
| 2026-09-02 | 1.4 | §3, §5 | Telegram destinations now come from a purpose address book (`telegram/trading`) using Telegram's `<chat>_<topic>` notation; strategy names destinations (`trading`, `alerts`, `digest`, `approvals`), never numbers. | `config/params.yaml`, `common/alerts/telegram.py`, `common/alerts/README.md` |
| 2026-09-02 | 1.3 | §3, §5 | Alerts routed to Telegram forum topics in the single RickyAI group (lifecycle → 03 Crypto, critical also → 99 Alerts); sender gained topic support and `--topics` discovery. | `config/params.yaml`, `common/alerts/telegram.py` |
| 2026-09-02 | 1.2 | §3, §8 | Credentials referenced by provider/name (`binance/SERVER_TRADING_RW`, `telegram/rickyassist_bot`) instead of a per-strategy env file; Telegram sender added in `common/alerts/telegram.py` with Windows setup script. | `config/params.yaml`, `STRATEGY.md`, `common/alerts/telegram.py`, `common/alerts/README.md`, `deploy/windows/setup-telegram.ps1` |
| 2026-09-02 | 1.1 | §2, §3, §6, §7, §8a, §8b, §9a | Corrected the universe to the 21 liquid USDC.p pairs (UNI included); added the coverage register, holdings file and the Sunday programme that refreshes R factors and sends them for review. Coverage rows pending the existing 21-pair results being filed. | `STRATEGY.md`, `config/params.yaml`, `config/universe.yaml`, `src/weekly.py`, `systemd/TS01-weekly.*` |
| 2026-09-02 | 1.0 | all | Captured the tested spec, parameters, execution rules, alert contract, gate status and evidence from the 28 Aug–2 Sep notes into the standard document. Runner/backtest are skeletons pending migration of the Ricky AI bot and the locked engine. | `STRATEGY.md`, `config/params.yaml`, `config/universe.yaml`, `src/runner.py`, `src/backtest.py`, `src/tests/test_replay.py`, `systemd/*` |
| 2026-09-02 | 0.1 | all | Created from template | `STRATEGY.md` |

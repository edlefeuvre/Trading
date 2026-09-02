---
id: TS{{NN}}
name: TS{{NN}} {{NAME_SPOKEN}} {{TF}} {{PLATFORM}} {{UNIVERSE}}
slug: TS{{NN}}_{{NAME}}_{{TF}}_{{PLATFORM}}_{{UNIVERSE}}
version: 0.1
status: draft            # draft | backtesting | paper | shadow | live | retired
mode: PAPER              # must match config/params.yaml
live_approved:           # date, set by Ed only, must also appear in the change log
owner: Ed Le Feuvre
created: {{DATE}}
---

# TS{{NN}} {{NAME_SPOKEN}} {{TF}} {{PLATFORM}} {{UNIVERSE}}

> One paragraph. What the strategy does, on what, and why it should work — who
> is on the other side of the trade. If this paragraph cannot be written, stop.

## 1. Hypothesis

State the structural reason for the edge before any testing. Record the date it
was written and whether it was written before or after seeing results.

## 2. Specification (the tested rules)

Any change here is a **MAJOR** version bump and invalidates §9.

| Element | Rule |
|---|---|
| Timeframe | |
| Universe | (list symbols; changes here are MAJOR) |
| Session / hours | |
| Setup | |
| Entry | |
| Stop | |
| Target / exit | |
| Management | |
| Order validity (GTC window, anchor) | |
| Cancel rules | |
| One-trade rules | |

### Encoding choices (judgement calls, so they are visible)

List every place the written rule had to be made mechanical (pivot width,
close-vs-wick, how intrabar ambiguity resolves). Each one is a hidden variant.

## 3. Parameters

The only place numbers are allowed to be explained. `config/params.yaml` must
match this table; `make check` diffs them.

| Key (params.yaml) | Value | Range allowed without MAJOR | Where used |
|---|---|---|---|
| `mode` | PAPER | PAPER / SHADOW (LIVE needs `live_approved`) | runner |
| `credentials.exchange` | binance/futures-trade | none | runner |
| `credentials.telegram` | telegram/rickyassist_bot | none | runner, weekly |
| `timeframe` | {{TF}} | none — a new timeframe is a new strategy | engine, runner, pine |
| `risk_unit_usd` | 20 | set by charter: max(1% book, 20) | runner |
| `alerts.book` | trading | none | runner, weekly |
| `alerts.to` | trading | any name in the book | runner |
| `alerts.critical_to` | alerts | any name in the book | runner |
| `alerts.weekly_to` | digest | any name in the book | weekly |

## 4. Execution & risk

| | |
|---|---|
| Risk unit (1R) | |
| Sizing rule | |
| Order type — entry | |
| Order type — stop | |
| Order type — target | |
| Margin mode / leverage cap | |
| Fee assumptions (maker / taker / funding) | |
| Slippage assumption | |
| Hard caps (notional, open positions, daily loss) | |

## 5. Alerting & lifecycle

Events the runner must emit, in order, and the reconciliation rule. Reference
the shared contract in `common/alerts/README.md`; list anything strategy-
specific here.

## 6. Artefact register

Every file that implements this strategy. If a file is not in this table it is
not part of the strategy.

| Path | Role | Version | Notes |
|---|---|---|---|
| `config/params.yaml` | parameters | | |
| `config/universe.yaml` | symbol list | | |
| `pine/…` | TradingView scripts, one row per file | | register each file explicitly |
| `src/runner.py` | live/paper runner | | |
| `src/backtest.py` | backtest entry point | | |
| `src/weekly.py` | Sunday programme | | |
| `src/tests/…` | acceptance / unit tests | | |
| `systemd/TS{{NN}}-runner.service` | long-running runner | 0.1 | |
| `systemd/TS{{NN}}-weekly.service` | Sunday programme (data roll, engine re-run, R factors for review) | 0.1 | |
| `systemd/TS{{NN}}-weekly.timer` | Sun 06:00 UTC | 0.1 | |

## 7. Gate to live

Copied from the charter and `crypto-strategy-development-method` §9. Each row
is ticked with a date and a pointer to the evidence.

| # | Condition | Cleared | Evidence |
|---|---|---|---|
| 1 | Out-of-sample result holds | | |
| 2 | Walk-forward consistent | | |
| 3 | Costs modelled at the account's real fee tier, incl. funding | | |
| 4 | ±20% parameter perturbation behaves | | |
| 5 | Enough trades (n and t stated) | | |
| 6 | 20 paper trades logged, within the validation band | | |
| 7 | Sizing and max drawdown written in advance | | |
| 8 | Runner passes the replay acceptance tests | | |
| 9 | Trade-only API key, withdrawals off, IP-allowlisted, hard caps set | | |

## 8. Operations

| | |
|---|---|
| Runner unit | `TS{{NN}}-runner.service` |
| Scheduled jobs | `TS{{NN}}-<job>.timer` … |
| Env file | `/etc/trading/TS{{NN}}.env` |
| Logs | journald + `logs/` |
| Data dependencies | |
| Restart policy | |

## 9. Evidence (backtests & paper results)

Newest first. Each entry: date, engine version, dataset window, in/out-of-
sample, costs, n, net R/trade, t, verdict, **variants tried so far** (running
count), pointer to `results/`.

## 10. Open questions & pre-registered research

Write the question and the expected answer **before** running.

## Change log

Newest first. Every commit touching `pine/`, `src/`, `config/` or shared engine/
exchange code adds a row. The hook checks that this table changed.

| Date | Version | Section | Change | Files |
|---|---|---|---|---|
| {{DATE}} | 0.1 | all | Created from template | `STRATEGY.md` |

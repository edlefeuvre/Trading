# Migration — from the 31 Aug setup to the repo (Windows PC)

_v2, 2 Sep 2026. What exists, where it goes, and the exact steps. Companion to
`docs/server-setup-log.md` (the why) and `STRATEGY.md` (the what)._

## What runs today (Task Scheduler, all as Admin, logon type Interactive)

| Task | Runs | Becomes |
|---|---|---|
| `CHoCH watcher` | `python choch_watch.py` in `C:\Users\Admin\choch`, every 15 min | `TS01-runner` — `strategies\TS01_CHoCH_ICT_15m_Binance_USDCp\src\runner.py` (**done in code, v1.8**) |
| _(none — run by hand)_ | `choch_sizes.py --write` → `~\.choch-watch\sizes.json` | `TS01-weekly` — `src\weekly.py`, Sundays (**done in code, v1.8**) |
| `GarchDailyDeliver` | 07:00, `investment-portfolio\scripts\garch-deliver-launcher.ps1` | stays in the Investment Book repo; later reads `.config\telegram\` and `.config\binance\SERVER_RO.env` |
| `TelegramWebhookRickyAI` | Ricky's inbound receiver (Node) in `investment-portfolio\scripts` | stays; owned by Paperclip |
| `INV-SnapshotRefresh` (disabled) | Node from `OneDrive\INV\scripts` | retire — code in OneDrive |

State files to retire once the runner is trusted: `~\.choch-watch\telegram.json` (third
copy of the bot token — token rotated 2 Sep), `sizes.json` (→ `config\universe.yaml`
tiers), `state.json` (→ `results\state.json`, seeded automatically on the runner's first
run so nothing is re-announced), `data\` cache (→ `%USERPROFILE%\.config\trading-data`).

## Steps — TS01 runner (PAPER), ~10 minutes at the PC

```powershell
cd $env:USERPROFILE\Repos\Trading
git pull                                                   # or unzip the delta over Repos\
Get-ChildItem .\deploy\windows\*.ps1 | Unblock-File
python -m pip install pyyaml                               # the runner's one dependency
python bin\check-strategy --all                            # document and folder agree
python -m pytest -q strategies\TS01_CHoCH_ICT_15m_Binance_USDCp\src\tests   # needs: pip install pytest
python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.runner --stdout --symbols ETHUSDC,SOLUSDC --backfill 300
```

The last line prints what the runner *would* send (nothing is sent, nothing is saved).
Expect `PAPER · SETUP · TS01` blocks for recent setups, each ending with an
`exchange …` line from `SERVER_RO`. If that looks right:

```powershell
python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.runner --test     # one test line to the Crypto topic
.\deploy\windows\register-ts01-runner.ps1 -RunNow                           # TS01-runner every 15 min at :00:30
.\deploy\windows\register-ts01-weekly.ps1                                   # TS01-weekly, Sundays 08:00
git add -A; git commit -m "TS01 v1.8: runner and weekly migrated"; git push
```

Both `CHoCH watcher` and `TS01-runner` now post. For a few days compare: every SETUP
the old watcher sends should appear from the runner with the `PAPER ·` prefix (and the
runner will additionally report FILLED / STOPPED / TARGET HIT / EXPIRED). When satisfied:

```powershell
Disable-ScheduledTask 'CHoCH watcher'
Rename-Item C:\Users\Admin\choch C:\Users\Admin\_retired_choch      # delete after a week
```

## What the runner does and does not do (v1.8)

Does: detect exactly as before (`common\engine\ict_base.py`, equivalence-tested); read
`params.yaml` / `universe.yaml`; size by tier × charter ceiling; say PAPER on every line;
report the full paper lifecycle; read positions and open orders with `SERVER_RO` into
`results\holdings.json` and quote them in every message; log one JSON line per cycle;
heartbeat hourly to Ricky Logs / Systems.

Does not: place, amend or cancel any order; implement the pool-consumed cancel
(`exit.pool_consumed_cancel: false`, see STRATEGY.md §2); run in SHADOW or LIVE (refuses).

## Investment Book repo (`investment-portfolio`)

Safe commit done 2 Sep (scripts, docs, conventions; agent scratch ignore-listed). Still to
do: move under `Repos\` and update the three Task Scheduler paths; point the GARCH launcher
and the webhook receiver at `.config\telegram\rickyassist_bot.env`; first `STRATEGY.md`
for the hedge/GARCH work under mandate `BTC-binance-…`.

# Migrating what is on the server today (2 Sep 2026)

Three things exist and need to land in the layout. Do each as **one commit**
with a change-log row in `strategies/TS01_CHoCH_ICT_15m_Binance_USDCp/STRATEGY.md` and
the §6 artefact register updated. Nothing is deleted from its old location until
the new location passes `make check` and `make test TS=01`.

| What exists | Lands in | Notes |
|---|---|---|
| Ricky AI bot (Telegram alerts, paper log, monitor) | Binance/Telegram plumbing → `common/exchange`, `common/alerts`; detection + lifecycle → `strategies/TS01_*/src/runner.py` | Implement the reconciliation loop first (§5). Record the five acceptance replays in `results/acceptance/*.jsonl` from the 31 Aug–2 Sep logs before changing logic, so they can be tested. |
| Python backtest engine (locked ICT base, pool exit) | `common/engine/` | Do not modify while moving. Then diff the engine's constants against `config/params.yaml` and fix STRATEGY.md §2 "Encoding choices" (pivot k in particular). |
| Pine Script indicators / alerts | `strategies/TS01_*/pine/TS01_CHoCH_alerts.pine` | Add the `TS01 v1.0` header; align the inputs with params.yaml. One file per script; register each in §6. |

Steps on the server:

```bash
git clone <this repo> %USERPROFILE%\Trading && cd %USERPROFILE%\Trading
bin/install-server                 # trader user, /etc/trading/TS01.env, venv, hook
# fill /etc/trading/TS01.env
make check                         # STRATEGY.md vs folder
# copy the three code bases in as above, one commit each
make test TS=01
make install TS=01                 # PAPER mode; check `make logs TS=01`
```

Promotion path after migration: PAPER (now) → SHADOW when the runner composes
correct tickets for a week → LIVE only when §7 rows 1–9 all carry a date and Ed
has written `live_approved:` plus its change-log row. The runner refuses LIVE
otherwise.

# Instructions for Claude Code working in this repository

Read `README.md` first. The conventions there are not optional.

## Before editing anything under `strategies/<TSnn>/` or `common/{engine,exchange}/`

1. Open the affected `strategies/<TSnn>/STRATEGY.md`. Understand which section
   your change touches: §2 spec (MAJOR), §3 parameters, §4 execution, §5
   alerting, §6 artefact register, §8 ops.
2. Make the code change.
3. In the **same commit**, add one row to the change log at the bottom of
   `STRATEGY.md`: date, version, section, one-line summary, files touched. Bump
   `version:` in the frontmatter. MAJOR if the tested spec changed, else MINOR.
4. If you added, renamed or deleted a file, update the artefact register (§6).
5. Run `make check`. It must pass before you commit.

The pre-commit hook enforces step 3. Do not bypass it with `--no-verify`.

## Numbers live in one place

Every tunable — stop rule, window length, fee assumptions, risk unit, universe —
lives in `config/params.yaml`. Pine and Python both read their defaults from the
values documented in `STRATEGY.md` §3, and `bin/check-strategy` diffs the yaml
against the doc table. Never hard-code a parameter in a runner or a Pine script
that is not also in the yaml and the table.

## Modes

Never change `mode:` in `params.yaml` to `LIVE`. That is a human decision,
recorded in the change log by Ed, and the runner checks the frontmatter for
`live_approved:`. If asked to "go live", make the code ready and stop; say what
gate items in §7 are still open.

## Alerts

Every Telegram message begins with the mode token (`PAPER` / `SHADOW` / `LIVE`),
then the event, then the strategy ID. Never assert a position that was not
confirmed against the exchange in the same cycle. The full contract is
`strategies/TS01_CHoCH_ICT_15m_Binance_USDCp/STRATEGY.md` §5 and
`common/alerts/README.md`.

## Testing

`pytest strategies/<TSnn>/src/tests` must pass. Each strategy has replay
acceptance tests in `src/tests/test_replay.py` driven by
`results/acceptance/*.jsonl`; if you change lifecycle logic, run them.

## Don't

- Don't put secrets, `.env` files, or logs in git.
- Don't create a strategy folder by hand — use `make new`.
- Don't edit `deploy/systemd/*` directly; edit the strategy's `systemd/` and
  re-run `make install`.
- Don't modify `common/engine` "just for TS01". If a change is strategy-specific
  it belongs in the strategy's `src/`.

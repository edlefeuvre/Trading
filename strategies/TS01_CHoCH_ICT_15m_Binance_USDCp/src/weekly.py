"""TS01 — the Sunday programme. Spec: STRATEGY.md §8a.

roll data → re-run engine on every symbol in universe.yaml → results/weekly/<date>/
→ diff vs last week → update coverage register (§9a) + results/coverage.csv
→ Telegram `PAPER · WEEKLY · TS01` + mirror summary.md to the Trading project.
Never changes universe.yaml, params.yaml or the spec. Fails loudly (§8a step 7).
"""
from __future__ import annotations

import sys

__version__ = "1.1"

R_FACTOR_COLUMNS = [
    "symbol", "dataset_start", "dataset_end", "bars", "n_setups", "n_kept",
    "n_discarded", "net_r_base", "net_r_kept", "net_r_discarded", "t_kept",
    "win_pct", "median_stop_pct", "median_bars_to_fill", "funding_r_per_trade",
    "provisional", "flag",
]
FLAGS = ("NEW", "SIGN FLIP", "DEGRADED", "STALE DATA", "THIN")


def main(argv=None):
    raise NotImplementedError("wire to common.engine once migrated; see STRATEGY.md §8a")


if __name__ == "__main__":
    sys.exit(main())

"""TS04 — backtest entry point.

Reads config/params.yaml + config/universe.yaml, runs common.engine, writes a
dated result to results/ and prints the summary block to paste into
STRATEGY.md §9. `--refresh` is what the weekly timer calls.
"""
from __future__ import annotations

import argparse
import sys

__version__ = "0.1"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="roll dataset forward and re-run")
    ap.add_argument("--variant", default="base")
    args = ap.parse_args(argv)
    raise NotImplementedError("wire to common.engine; see STRATEGY.md §6 artefact register")


if __name__ == "__main__":
    sys.exit(main())

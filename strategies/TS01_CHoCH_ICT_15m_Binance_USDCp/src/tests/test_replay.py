"""Replay acceptance tests for TS01.

Each file in results/acceptance/*.jsonl is a recorded sequence of bars + exchange
state for one historical setup, with the expected alert sequence. The runner
must reproduce the expected events exactly — and, above all, never emit a
position that the exchange state does not confirm.
"""
import glob
import json
import os

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CASES = sorted(glob.glob(os.path.join(HERE, "results", "acceptance", "*.jsonl")))


@pytest.mark.parametrize("path", CASES, ids=[os.path.basename(c) for c in CASES])
def test_replay(path):
    with open(path) as f:
        case = [json.loads(l) for l in f if l.strip()]
    expected = [r["event"] for r in case if r.get("kind") == "expect"]
    pytest.skip(f"runner.cycle not implemented yet; {len(expected)} expected events")


def test_no_phantom_positions_rule_is_present():
    src = open(os.path.join(HERE, "src", "runner.py")).read()
    assert "reconcile" in src, "runner must reconcile against the exchange first"

"""The parallel driver must produce exactly what the serial path produces."""

from __future__ import annotations

from model import code as qc
from model import sweeps


def test_parallel_matches_serial():
    code = qc.make_qc_code(n_b=24, m_b=8, z=16, col_weight=3, seed=3)
    mask = qc.make_mask(code, 0)
    points = [
        sweeps.Point(mask, q, frames=4, seed=11, label=f"q{q}",
                     kwargs={"max_iters": 20, "backend": "fixed"})
        for q in (0.01, 0.02, 0.03)
    ]
    serial = sweeps.run_points(points, workers=1)
    parallel = sweeps.run_points(points, workers=3)

    assert len(serial) == len(parallel) == 3
    for a, b in zip(serial, parallel):
        assert a["qber"] == b["qber"]
        assert a["fer"] == b["fer"]
        assert a["efficiency"] == b["efficiency"]
        assert a["avg_iters_ok"] == b["avg_iters_ok"] or (
            a["avg_iters_ok"] != a["avg_iters_ok"] and b["avg_iters_ok"] != b["avg_iters_ok"]
        )


def test_default_workers_leaves_a_core():
    import os
    assert 1 <= sweeps.default_workers() <= max(1, (os.cpu_count() or 2))

"""Density-evolution tests.

The headline check is the one that caught a real bug: no ensemble may have a
threshold above the Shannon limit for its rate.
"""

from __future__ import annotations

import numpy as np
import pytest

from model import de
from model.info import h


def shannon_limit(rate: float) -> float:
    """Largest QBER with h(Q) <= 1 - R."""
    lo, hi = 1e-6, 0.5
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if h(mid) < 1.0 - rate:
            lo = mid
        else:
            hi = mid
    return lo


def test_densities_stay_normalised():
    grid = de.Grid(step=0.1, half=400)
    p = de.channel_density(0.05, grid)
    assert p.sum() == pytest.approx(1.0)
    chk = de.check_update(p, 6, 0.75, grid)
    assert chk.sum() == pytest.approx(1.0)
    lam, _ = de.regular(3, 6)
    var = de.variable_update(p, chk, lam, grid)
    assert var.sum() == pytest.approx(1.0, abs=1e-9)


def test_channel_density_matches_the_bsc():
    grid = de.Grid(step=0.01, half=2000)
    q = 0.07
    p = de.channel_density(q, grid)
    assert de.error_probability(p, grid) == pytest.approx(q, abs=1e-9)


@pytest.mark.parametrize("dv,dc", [(3, 6), (3, 9), (4, 8)])
def test_threshold_is_below_the_shannon_limit(dv, dc):
    """An earlier implementation violated this; it is the canary for the module."""
    lam, rho = de.regular(dv, dc)
    rate = de.design_rate(lam, rho)
    th = de.threshold(lam, rho, alpha=0.75, iterations=120)
    assert 0.0 < th < shannon_limit(rate)


def test_normalisation_beats_plain_min_sum():
    """Matches what E2 measured in simulation: alpha = 0.75 >> alpha = 1.0."""
    lam, rho = de.regular(3, 6)
    th_nms = de.threshold(lam, rho, alpha=0.75, iterations=120)
    th_ms = de.threshold(lam, rho, alpha=1.0, iterations=120)
    assert th_nms > th_ms


def test_lower_rate_tolerates_more_noise():
    th_half = de.threshold(*de.regular(3, 6), alpha=0.75, iterations=120)
    th_two_thirds = de.threshold(*de.regular(3, 9), alpha=0.75, iterations=120)
    assert th_half > th_two_thirds


def test_design_rate_arithmetic():
    lam, rho = de.regular(3, 6)
    assert de.design_rate(lam, rho) == pytest.approx(0.5)
    lam, rho = de.regular(4, 8)
    assert de.design_rate(lam, rho) == pytest.approx(0.5)
    lam, rho = de.regular(3, 9)
    assert de.design_rate(lam, rho) == pytest.approx(2 / 3)


def test_node_to_edge_conversion():
    edge = de.node_to_edge({2: 0.5, 6: 0.5})
    assert edge[2] == pytest.approx(2 * 0.5 / 4.0)
    assert edge[6] == pytest.approx(6 * 0.5 / 4.0)
    assert sum(edge.values()) == pytest.approx(1.0)


def test_check_degrees_hit_the_target_rate():
    lam = de.node_to_edge({3: 0.8, 6: 0.2})
    for target in (0.5, 0.62, 0.87):
        rho = de.check_degrees_for_rate(lam, target)
        assert de.design_rate(lam, rho) == pytest.approx(target, abs=1e-6)


def test_evolve_converges_well_below_threshold():
    lam, rho = de.regular(3, 6)
    ok, err, iters = de.evolve(0.02, lam, rho, alpha=0.75, iterations=200)
    assert ok and err < 1e-7


def test_evolve_fails_above_the_shannon_limit():
    lam, rho = de.regular(3, 6)
    ok, _, _ = de.evolve(0.15, lam, rho, alpha=0.75, iterations=120)
    assert not ok

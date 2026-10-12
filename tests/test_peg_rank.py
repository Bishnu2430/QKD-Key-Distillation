"""PEG construction and the GF(2) rank check."""

from __future__ import annotations

import numpy as np
import pytest

from model import code as qc
from model import peg, rank


@pytest.fixture(scope="module")
def peg_code() -> qc.QCCode:
    degrees = peg.degrees_from_profile(48, {6: 0.25, 3: 0.75})
    return peg.build_peg_code(n_b=48, m_b=24, z=32, col_degrees=degrees, seed=5)


def test_peg_respects_the_requested_degrees(peg_code):
    degrees = peg_code.column_degrees()
    assert sorted(degrees.tolist()) == sorted(
        peg.degrees_from_profile(48, {6: 0.25, 3: 0.75}).tolist()
    )


def test_peg_balances_check_degrees(peg_code):
    """PEG always picks the least-loaded admissible check, so rows stay even."""
    row_counts = (peg_code.base != qc.ZERO_BLOCK).sum(axis=1)
    assert row_counts.max() - row_counts.min() <= 1


def test_peg_code_has_no_four_cycles(peg_code):
    b, z = peg_code.base, peg_code.z
    for c1 in range(peg_code.n_b):
        for c2 in range(c1 + 1, peg_code.n_b):
            shared = [r for r in range(peg_code.m_b)
                      if b[r, c1] != qc.ZERO_BLOCK and b[r, c2] != qc.ZERO_BLOCK]
            diffs = [(int(b[r, c1]) - int(b[r, c2])) % z for r in shared]
            assert len(diffs) == len(set(diffs))


def test_heavy_columns_come_first(peg_code):
    degrees = peg_code.column_degrees()
    heavy = np.flatnonzero(degrees == 6)
    assert heavy.max() < np.flatnonzero(degrees == 3).min()


def test_syndrome_still_matches_a_dense_expansion(peg_code):
    h = np.zeros((peg_code.m, peg_code.n), dtype=np.uint8)
    for r in range(peg_code.m_b):
        for c in range(peg_code.n_b):
            k = int(peg_code.base[r, c])
            if k == qc.ZERO_BLOCK:
                continue
            for i in range(peg_code.z):
                h[r * peg_code.z + i, c * peg_code.z + (i + k) % peg_code.z] = 1
    rng = np.random.default_rng(1)
    word = rng.integers(0, 2, size=peg_code.n, dtype=np.uint8)
    assert np.array_equal(peg_code.syndrome(word), (h @ word) % 2)


# --- rank -----------------------------------------------------------------
def test_a_single_column_is_independent(peg_code):
    ok, r = rank.columns_are_independent(peg_code, np.array([0]))
    assert ok and r == 1


def test_duplicate_columns_are_dependent(peg_code):
    ok, r = rank.columns_are_independent(peg_code, np.array([3, 3]))
    assert not ok and r == 1


def test_rank_never_exceeds_the_number_of_columns(peg_code):
    cols = np.arange(0, 64)
    ok, r = rank.columns_are_independent(peg_code, cols)
    assert r <= cols.size


def test_more_columns_than_rows_must_be_dependent(peg_code):
    cols = np.arange(peg_code.m + 5)
    ok, r = rank.columns_are_independent(peg_code, cols)
    assert not ok and r <= peg_code.m


def test_mask_leakage_uses_the_rank_result(peg_code):
    mask = qc.make_mask(peg_code, 0, punctured_cols=[0, 1])
    leak, ok = rank.mask_leakage(peg_code, mask, tag_bits=64)
    expected = peg_code.m - (mask.p if ok else 0) + 64
    assert leak == expected

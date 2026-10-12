"""The accelerated kernels must equal the reference implementations exactly.

This is the test that lets the fast path be used for published curves: if it
passes, every number the Numba kernel produces is a number the reference model
would have produced.
"""

from __future__ import annotations

import numpy as np
import pytest

from model import code as qc
from model import decoder as l1
from model import fast, fixed, frame


@pytest.fixture(scope="module")
def small_code() -> qc.QCCode:
    return qc.make_qc_code(n_b=32, m_b=11, z=16, col_weight=3, seed=11)


@pytest.fixture(scope="module")
def frames(small_code):
    """A spread of frames: easy, moderate and beyond the code's threshold."""
    mask = qc.make_mask(small_code, 0, punctured_cols=[4], shortened_cols=[20])
    rng = np.random.default_rng(99)
    out = []
    for qber in (0.01, 0.03, 0.06, 0.12):
        for _ in range(4):
            out.append((mask, qber, frame.make_frame(mask, qber, rng)))
    return out


def test_fixed_kernel_matches_reference(small_code, frames):
    for mask, qber, f in frames:
        llr = fixed.initial_llr(mask, f.y_key, qber)
        ref = fixed.decode(small_code, llr, f.syndrome, max_iters=25)
        got = fast.decode_fixed(small_code, llr, f.syndrome, max_iters=25)
        assert got.ok == ref.ok
        assert got.iterations == ref.iterations
        assert np.array_equal(got.x_hat, ref.x_hat)
        assert np.array_equal(got.llr, ref.llr)


def test_float_kernel_matches_reference(small_code, frames):
    for mask, qber, f in frames:
        ref = l1.decode(small_code, f.llr, f.syndrome, max_iters=25, algorithm="nms")
        got = fast.decode_float(small_code, f.llr, f.syndrome, max_iters=25)
        assert got.ok == ref.ok
        assert got.iterations == ref.iterations
        assert np.array_equal(got.x_hat, ref.x_hat)
        assert np.allclose(got.llr, ref.llr, rtol=1e-9, atol=1e-9)


@pytest.mark.parametrize("shifts,alpha", [((1,), 0.5), ((1, 2), 0.75), ((1, 2, 3), 0.875)])
def test_kernel_matches_reference_for_each_alpha(small_code, frames, shifts, alpha):
    cfg = fixed.FixedConfig(alpha_shifts=shifts)
    mask, qber, f = frames[4]
    llr = fixed.initial_llr(mask, f.y_key, qber, cfg)
    ref = fixed.decode(small_code, llr, f.syndrome, max_iters=25, cfg=cfg)
    got = fast.decode_fixed(small_code, llr, f.syndrome, max_iters=25, cfg=cfg)
    assert (got.ok, got.iterations) == (ref.ok, ref.iterations)
    assert np.array_equal(got.llr, ref.llr)
    assert cfg.alpha == alpha


def test_kernel_matches_reference_for_narrow_widths(small_code, frames):
    cfg = fixed.FixedConfig(w_ch=4, w_msg=4, w_app=6, delta=0.5)
    mask, qber, f = frames[6]
    llr = fixed.initial_llr(mask, f.y_key, qber, cfg)
    ref = fixed.decode(small_code, llr, f.syndrome, max_iters=20, cfg=cfg)
    got = fast.decode_fixed(small_code, llr, f.syndrome, max_iters=20, cfg=cfg)
    assert (got.ok, got.iterations) == (ref.ok, ref.iterations)
    assert np.array_equal(got.llr, ref.llr)


def test_kernel_does_not_modify_its_input(small_code, frames):
    mask, qber, f = frames[0]
    llr = fixed.initial_llr(mask, f.y_key, qber)
    before = llr.copy()
    fast.decode_fixed(small_code, llr, f.syndrome, max_iters=10)
    assert np.array_equal(llr, before)

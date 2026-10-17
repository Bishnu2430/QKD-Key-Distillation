"""Tests for the L2 bit-true model (docs/05-algorithm-spec.md sections 2.1, 3.4, 3.6)."""

from __future__ import annotations

import numpy as np
import pytest

from model import code as qc
from model import decoder as l1
from model import fixed, frame


@pytest.fixture(scope="module")
def small_code() -> qc.QCCode:
    return qc.make_qc_code(n_b=24, m_b=8, z=16, col_weight=3, seed=7)


# ---------------------------------------------------------------------------
# arithmetic primitives
# ---------------------------------------------------------------------------
def test_symmetric_saturation_never_wraps():
    cfg = fixed.DEFAULT
    v = np.array([200, -200, 5], dtype=np.int32)
    out = fixed.saturate(v, cfg.max_app)
    assert out.tolist() == [127, -127, 5]
    assert cfg.max_app == 127 and cfg.max_msg == 31 and cfg.max_ch == 15


def test_alpha_is_a_sum_of_shifts():
    """0.75 via (v>>1)+(v>>2): docs/00-learning-guide.md section 15.4."""
    v = np.array([7, 13, 31, 20], dtype=np.int32)
    got = fixed.normalise(v, (1, 2)).tolist()
    assert got == [4, 9, 22, 15]  # exact 0.75v would be 5.25, 9.75, 23.25, 15
    assert fixed.DEFAULT.alpha == 0.75


def test_channel_amplitude_table():
    """Learning guide section 15.2, with delta = 0.25 and a 5-bit magnitude."""
    assert fixed.channel_amplitude(0.01) == 15  # 18.38 saturates
    assert fixed.channel_amplitude(0.05) == 12  # 11.78 rounds to 12
    assert fixed.channel_amplitude(0.10) == 9  # 8.79 rounds to 9


def test_channel_amplitude_is_never_zero():
    """Even a hopeless QBER estimate must leave the decoder some information."""
    assert fixed.channel_amplitude(0.49) == 1


def test_wider_widths_give_finer_amplitude():
    cfg = fixed.FixedConfig(w_ch=8, delta=0.125)
    assert fixed.channel_amplitude(0.05, cfg) == 24  # 2.944 / 0.125 = 23.6


# ---------------------------------------------------------------------------
# initial LLRs (spec section 3.3 / 3.4)
# ---------------------------------------------------------------------------
def test_initial_llr_structure(small_code):
    mask = qc.make_mask(small_code, 0, punctured_cols=[3], shortened_cols=[9])
    rng = np.random.default_rng(1)
    f = frame.make_frame(mask, 0.03, rng)
    llr = fixed.initial_llr(mask, f.y_key, 0.03)

    key, punct, short = mask.positions()
    amp = fixed.channel_amplitude(0.03)
    assert llr.dtype == np.int32
    assert np.array_equal(llr[key], np.where(f.y_key == 0, amp, -amp))
    assert np.all(llr[punct] == 0)
    assert np.all(llr[short] == fixed.DEFAULT.max_app)


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------
def test_error_free_frame_decodes_in_one_iteration(small_code):
    mask = qc.make_mask(small_code, 0)
    rng = np.random.default_rng(2)
    f = frame.make_frame(mask, 0.0, rng, qber_est=0.01)
    llr = fixed.initial_llr(mask, f.y_key, 0.01)
    res = fixed.decode(small_code, llr, f.syndrome, max_iters=8)
    assert res.ok and res.iterations == 1
    assert np.array_equal(res.key_bits(mask.positions()[0]), f.x_key)


def test_fixed_point_corrects_errors(small_code):
    mask = qc.make_mask(small_code, 0)
    rng = np.random.default_rng(3)
    ok = 0
    for _ in range(10):
        f = frame.make_frame(mask, 0.02, rng)
        llr = fixed.initial_llr(mask, f.y_key, 0.02)
        res = fixed.decode(small_code, llr, f.syndrome, max_iters=50)
        if res.ok and np.array_equal(res.key_bits(mask.positions()[0]), f.x_key):
            ok += 1
    assert ok >= 9, f"only {ok}/10 frames recovered"


def test_decoder_is_deterministic(small_code):
    """Same inputs, same outputs - the property that makes it an RTL oracle."""
    mask = qc.make_mask(small_code, 0)
    rng = np.random.default_rng(4)
    f = frame.make_frame(mask, 0.03, rng)
    llr = fixed.initial_llr(mask, f.y_key, 0.03)
    a = fixed.decode(small_code, llr, f.syndrome, max_iters=20)
    b = fixed.decode(small_code, llr, f.syndrome, max_iters=20)
    assert a.ok == b.ok and a.iterations == b.iterations
    assert np.array_equal(a.x_hat, b.x_hat) and np.array_equal(a.llr, b.llr)


def test_all_values_stay_inside_their_word_widths(small_code):
    """No value may exceed its declared width; the RTL has nowhere to put it."""
    mask = qc.make_mask(small_code, 0)
    rng = np.random.default_rng(5)
    f = frame.make_frame(mask, 0.04, rng)
    llr = fixed.initial_llr(mask, f.y_key, 0.04)
    res = fixed.decode(small_code, llr, f.syndrome, max_iters=30)
    assert np.abs(res.llr).max() <= fixed.DEFAULT.max_app


def test_fixed_point_tracks_float_at_low_qber(small_code):
    """L1 and L2 should agree on easy frames; divergence is the quantisation loss."""
    mask = qc.make_mask(small_code, 0)
    rng = np.random.default_rng(6)
    agree = 0
    for _ in range(10):
        f = frame.make_frame(mask, 0.015, rng)
        r_float = l1.decode(small_code, f.llr, f.syndrome, max_iters=50)
        r_fixed = fixed.decode(
            small_code, fixed.initial_llr(mask, f.y_key, 0.015), f.syndrome, max_iters=50
        )
        if r_float.ok == r_fixed.ok:
            agree += 1
    assert agree >= 9


def test_narrow_widths_degrade_rather_than_crash(small_code):
    """A deliberately starved configuration must still run and report honestly."""
    mask = qc.make_mask(small_code, 0)
    cfg = fixed.FixedConfig(w_ch=3, w_msg=3, w_app=4, delta=1.0)
    rng = np.random.default_rng(7)
    f = frame.make_frame(mask, 0.03, rng)
    llr = fixed.initial_llr(mask, f.y_key, 0.03, cfg)
    res = fixed.decode(small_code, llr, f.syndrome, max_iters=20, cfg=cfg)
    assert isinstance(res.ok, bool)
    assert np.abs(res.llr).max() <= cfg.max_app


# ---------------------------------------------------------------------------
# the RTL oracles (docs/stages/02 and 03)
# ---------------------------------------------------------------------------
def test_layer_trace_over_every_layer_equals_one_iteration(small_code):
    """Stage 2's oracle run to the end must equal stage 3's oracle after one pass."""
    mask = qc.make_mask(small_code, 0)
    rng = np.random.default_rng(11)
    f = frame.make_frame(mask, 0.03, rng, qber_est=0.03)
    llr = fixed.initial_llr(mask, f.y_key, 0.03)

    by_layer = fixed.decode_layer_trace(small_code, llr, f.syndrome, small_code.m_b)
    by_iter = fixed.decode_iteration_trace(small_code, llr, f.syndrome, 1)

    assert np.array_equal(by_layer[-1], by_iter[1])
    assert np.array_equal(by_layer[0], by_iter[0])


def test_iteration_trace_agrees_with_the_decoder(small_code):
    """The snapshot at iteration k is the decoder's state after k iterations.

    This is what licenses comparing RTL against the trace: whatever the decoder
    reports, the hardware is being held to the same arithmetic.
    """
    mask = qc.make_mask(small_code, 0)
    rng = np.random.default_rng(12)
    for _ in range(5):
        f = frame.make_frame(mask, 0.04, rng, qber_est=0.04)
        llr = fixed.initial_llr(mask, f.y_key, 0.04)
        res = fixed.decode(small_code, llr, f.syndrome, max_iters=8)
        trace = fixed.decode_iteration_trace(small_code, llr, f.syndrome, 8)
        assert np.array_equal(res.llr, trace[res.iterations])


def test_iteration_trace_never_stops_early(small_code):
    """It must run the full count even after the frame is solved, as the RTL does."""
    mask = qc.make_mask(small_code, 0)
    rng = np.random.default_rng(13)
    f = frame.make_frame(mask, 0.01, rng, qber_est=0.01)
    llr = fixed.initial_llr(mask, f.y_key, 0.01)
    trace = fixed.decode_iteration_trace(small_code, llr, f.syndrome, 6)
    assert len(trace) == 7

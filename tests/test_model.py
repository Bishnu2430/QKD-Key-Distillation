"""Unit tests for the L1 reference model.

Includes the worked examples from the specification and the learning guide, so
a change in behaviour shows up as a failing documented example rather than as a
silently different number.
"""

from __future__ import annotations

import numpy as np
import pytest

from model import bits, code, decoder, frame, hashing, info, pipeline


# ---------------------------------------------------------------------------
# bit conventions (spec section 2)
# ---------------------------------------------------------------------------
def test_packing_is_lsb_first():
    assert int(bits.pack_words(np.array([1, 0, 1]))[0]) == 0b101


def test_packing_round_trip_with_padding():
    rng = np.random.default_rng(1)
    b = rng.integers(0, 2, size=100, dtype=np.uint8)
    assert np.array_equal(bits.unpack_words(bits.pack_words(b), 100), b)


def test_hex_line_round_trip():
    rng = np.random.default_rng(2)
    b = rng.integers(0, 2, size=200, dtype=np.uint8)
    assert np.array_equal(bits.from_hex_lines(bits.to_hex_lines(b), 200), b)


# ---------------------------------------------------------------------------
# information theory
# ---------------------------------------------------------------------------
def test_binary_entropy_values():
    assert info.h(0.0) == 0.0
    assert info.h(0.5) == pytest.approx(1.0)
    assert info.h(0.03) == pytest.approx(0.1944, abs=1e-4)
    assert info.h(0.11) == pytest.approx(0.4999, abs=1e-4)


def test_required_rate_matches_learning_guide_table():
    # docs/00-learning-guide.md section 9.11
    assert info.required_rate(0.01, 1.1) == pytest.approx(0.911, abs=1e-3)
    assert info.required_rate(0.05, 1.1) == pytest.approx(0.685, abs=1e-3)
    assert info.required_rate(0.10, 1.1) == pytest.approx(0.484, abs=1e-3)


def test_secret_fraction_thresholds():
    # key generation stops at 11.0% / 10.2% / 9.5% for f = 1.0 / 1.1 / 1.2
    assert info.secret_fraction(0.109, 1.0) > 0
    assert info.secret_fraction(0.111, 1.0) == 0
    assert info.secret_fraction(0.103, 1.1) == 0
    assert info.secret_fraction(0.096, 1.2) == 0


def test_channel_llr_value():
    assert info.channel_llr(0.05) == pytest.approx(2.9444, abs=1e-4)


# ---------------------------------------------------------------------------
# QC-LDPC code (spec section 3.1)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def small_code() -> code.QCCode:
    return code.make_qc_code(n_b=24, m_b=8, z=16, col_weight=3, seed=7)


def explicit_h(c: code.QCCode) -> np.ndarray:
    """Expand the base matrix into a dense parity-check matrix, slowly."""
    h = np.zeros((c.m, c.n), dtype=np.uint8)
    for r in range(c.m_b):
        for col in range(c.n_b):
            k = int(c.base[r, col])
            if k == code.ZERO_BLOCK:
                continue
            for i in range(c.z):
                h[r * c.z + i, col * c.z + (i + k) % c.z] = 1
    return h


def test_syndrome_matches_dense_matrix(small_code):
    rng = np.random.default_rng(3)
    h = explicit_h(small_code)
    word = rng.integers(0, 2, size=small_code.n, dtype=np.uint8)
    assert np.array_equal(small_code.syndrome(word), (h @ word) % 2)


def test_each_variable_appears_once_per_layer(small_code):
    """The structural constraint that makes parallel == serial (spec 3.1)."""
    for r in range(small_code.m_b):
        v = small_code.variables_of_layer(r)
        for row in v:
            assert len(set(row.tolist())) == len(row)


def test_no_four_cycles_in_base(small_code):
    """Shift assignment rejects (B[r1,c1]-B[r1,c2]) == (B[r2,c1]-B[r2,c2])."""
    b, z = small_code.base, small_code.z
    for c1 in range(small_code.n_b):
        for c2 in range(c1 + 1, small_code.n_b):
            shared = [
                r for r in range(small_code.m_b)
                if b[r, c1] != code.ZERO_BLOCK and b[r, c2] != code.ZERO_BLOCK
            ]
            diffs = [(int(b[r, c1]) - int(b[r, c2])) % z for r in shared]
            assert len(diffs) == len(set(diffs)), f"4-cycle between columns {c1},{c2}"


def test_code_shape(small_code):
    assert small_code.n == 24 * 16
    assert small_code.m == 8 * 16
    assert small_code.rate0 == pytest.approx(1 - 8 / 24)
    assert small_code.n_edges_base == 24 * 3


# ---------------------------------------------------------------------------
# rate masks (spec sections 3.3 and 3.5)
# ---------------------------------------------------------------------------
def test_mask_arithmetic(small_code):
    mask = code.make_mask(small_code, 1, punctured_cols=[2, 7], shortened_cols=[11])
    assert mask.p == 2 * 16 and mask.s == 16
    assert mask.n_key == small_code.n - mask.p - mask.s
    assert mask.rate == pytest.approx(
        info.effective_rate(small_code.rate0, mask.pi, mask.sigma)
    )
    assert mask.leakage_bits(tag_bits=64) == small_code.m - mask.p + 64


def test_mask_positions_partition(small_code):
    mask = code.make_mask(small_code, 2, punctured_cols=[0], shortened_cols=[1, 23])
    key, punct, short = mask.positions()
    joined = np.concatenate([key, punct, short])
    assert np.array_equal(np.sort(joined), np.arange(small_code.n))


def test_mask_rejects_overlap(small_code):
    with pytest.raises(ValueError):
        code.make_mask(small_code, 3, punctured_cols=[4], shortened_cols=[4])


# ---------------------------------------------------------------------------
# framing (spec sections 3.3 and 3.4)
# ---------------------------------------------------------------------------
def test_frame_construction(small_code):
    mask = code.make_mask(small_code, 0, punctured_cols=[5], shortened_cols=[9])
    rng = np.random.default_rng(4)
    f = frame.make_frame(mask, 0.03, rng)

    key, punct, short = mask.positions()
    assert np.array_equal(f.word[key], f.x_key)
    assert np.all(f.word[short] == 0)
    assert f.syndrome.size == small_code.m
    assert np.all(f.llr[punct] == 0.0)
    assert np.all(f.llr[short] == frame.LLR_KNOWN)
    # LLR sign convention: positive favours 0
    assert np.all(f.llr[key][f.y_key == 0] > 0)
    assert np.all(f.llr[key][f.y_key == 1] < 0)


# ---------------------------------------------------------------------------
# decoder (spec section 3.6)
# ---------------------------------------------------------------------------
def test_error_free_frame_decodes_immediately(small_code):
    mask = code.make_mask(small_code, 0)
    rng = np.random.default_rng(5)
    # a real decoder is always configured with a non-zero QBER estimate
    f = frame.make_frame(mask, 0.0, rng, qber_est=0.01)
    assert f.n_errors == 0
    res = decoder.decode(small_code, f.llr, f.syndrome, max_iters=8)
    assert res.ok and res.iterations == 1
    assert np.array_equal(res.key_bits(mask.positions()[0]), f.x_key)


@pytest.mark.parametrize("algorithm", ["nms", "spa"])
def test_decoder_corrects_errors(small_code, algorithm):
    mask = code.make_mask(small_code, 0)
    rng = np.random.default_rng(6)
    successes = 0
    for _ in range(10):
        f = frame.make_frame(mask, 0.02, rng)
        res = decoder.decode(
            small_code, f.llr, f.syndrome, max_iters=50, algorithm=algorithm
        )
        if res.ok and np.array_equal(res.key_bits(mask.positions()[0]), f.x_key):
            successes += 1
    assert successes >= 9, f"{algorithm}: only {successes}/10 frames recovered"


def test_decoder_reports_failure_rather_than_lying(small_code):
    """At a QBER far beyond the code's threshold, frames must fail cleanly."""
    mask = code.make_mask(small_code, 0)
    rng = np.random.default_rng(7)
    f = frame.make_frame(mask, 0.25, rng)
    res = decoder.decode(small_code, f.llr, f.syndrome, max_iters=10)
    if res.ok:  # a satisfied syndrome must mean a genuine codeword
        assert small_code.syndrome_matches(res.x_hat, f.syndrome)


# ---------------------------------------------------------------------------
# hashing (spec sections 4 and 5)
# ---------------------------------------------------------------------------
def test_toeplitz_worked_example():
    """docs/00-learning-guide.md section 11.3: seed 10110, x 1101 -> 01."""
    seed = np.array([1, 0, 1, 1, 0], dtype=np.uint8)
    x = np.array([1, 1, 0, 1], dtype=np.uint8)
    expected = np.array([0, 1], dtype=np.uint8)
    assert np.array_equal(hashing.toeplitz_hash(seed, x, 2, method="window"), expected)
    assert np.array_equal(hashing.toeplitz_hash(seed, x, 2, method="kronecker"), expected)


def test_gf2_convolution_worked_example():
    """(1+z+z^3)(1+z^2) = 1+z+z^2+z^5 over GF(2)."""
    a = np.array([1, 1, 0, 1], dtype=np.uint8)
    b = np.array([1, 0, 1], dtype=np.uint8)
    assert np.array_equal(hashing.gf2_convolve(a, b), [1, 1, 1, 0, 0, 1])


def test_hash_methods_agree_on_random_input():
    rng = np.random.default_rng(8)
    n, out = 1000, 64
    x = rng.integers(0, 2, size=n, dtype=np.uint8)
    seed = hashing.random_seed(n, out, rng)
    a = hashing.toeplitz_hash(seed, x, out, method="window")
    b = hashing.toeplitz_hash(seed, x, out, method="kronecker")
    assert np.array_equal(a, b)


def test_tag_detects_a_single_bit_flip():
    rng = np.random.default_rng(9)
    n = 512
    x = rng.integers(0, 2, size=n, dtype=np.uint8)
    seed = hashing.random_seed(n, hashing.TAG_BITS, rng)
    y = x.copy()
    y[123] ^= 1
    assert not np.array_equal(
        hashing.verification_tag(x, seed), hashing.verification_tag(y, seed)
    )


def test_hash_is_linear():
    """Toeplitz hashing is GF(2)-linear: H(x ^ y) == H(x) ^ H(y)."""
    rng = np.random.default_rng(10)
    n, out = 300, 16
    seed = hashing.random_seed(n, out, rng)
    x = rng.integers(0, 2, size=n, dtype=np.uint8)
    y = rng.integers(0, 2, size=n, dtype=np.uint8)
    hx = hashing.toeplitz_hash(seed, x, out)
    hy = hashing.toeplitz_hash(seed, y, out)
    hxy = hashing.toeplitz_hash(seed, x ^ y, out)
    assert np.array_equal(hxy, hx ^ hy)


def test_seed_length_is_checked():
    rng = np.random.default_rng(11)
    x = rng.integers(0, 2, size=50, dtype=np.uint8)
    with pytest.raises(ValueError):
        hashing.toeplitz_hash(np.zeros(10, dtype=np.uint8), x, 8)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def test_block_pipeline_produces_a_shared_key(small_code):
    mask = code.make_mask(small_code, 0)
    rng = np.random.default_rng(12)
    res = pipeline.process_block(mask, 0.02, n_frames=6, rng=rng, max_iters=50)
    assert res.n_ok >= 5
    assert res.undetected_errors() == 0
    assert res.block_bits is not None and res.secret_key is not None
    assert 0 < res.secret_key.size < res.block_bits.size


def test_measure_reports_consistent_statistics(small_code):
    mask = code.make_mask(small_code, 0)
    stats = pipeline.measure(mask, 0.02, n_frames=8, seed=13, max_iters=50)
    assert stats["undetected"] == 0
    assert 0.0 <= stats["fer"] <= 1.0
    assert stats["efficiency"] > 1.0  # never below the Slepian-Wolf limit
    assert stats["n_key"] == mask.n_key

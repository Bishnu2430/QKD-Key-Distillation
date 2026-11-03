"""Guard the word-wise decomposition the stage-14 RTL implements.

model/hashing.py defines the tag bit by bit. The RTL cannot do that: it sees
the key 64 bits at a time and must accumulate a partial tag per word, using a
sliding 128-bit window of the seed.

These tests pin that decomposition to the model. If someone changes the bit
order in model/bits.py, or the seed-length convention in hashing.py, the RTL
stops matching and this fails here rather than in a waveform.
"""

from __future__ import annotations

import numpy as np
import pytest

from model import bits, hashing

W = 64
MASK64 = (1 << W) - 1


def tag_wordwise(x: np.ndarray, seed: np.ndarray, t: int) -> int:
    """The tag exactly as toeplitz_tag.sv computes it, as an integer.

    At key word s the RTL holds vwin = {v_word[s+1], v_word[s]}, so vwin bit k
    is seed bit 64*s + k, and output bit i consumes vwin[i +: 64].
    """
    xw = bits.pack_words(x)
    vw = bits.pack_words(seed)
    acc = 0
    for s in range(x.size // W):
        lo = int(vw[s])
        hi = int(vw[s + 1]) if s + 1 < vw.size else 0
        vwin = lo | (hi << W)
        xs = int(xw[s])
        for i in range(t):
            term = ((vwin >> i) & MASK64) & xs
            acc ^= (bin(term).count("1") & 1) << i
    return acc


def tag_int(tag_bits: np.ndarray) -> int:
    return int(bits.pack_words(tag_bits)[0])


@pytest.mark.parametrize("n_words", [1, 2, 7, 64])
def test_wordwise_matches_model(n_words: int) -> None:
    rng = np.random.default_rng(1234 + n_words)
    n_key = n_words * W
    x = rng.integers(0, 2, size=n_key, dtype=np.uint8)
    seed = hashing.random_seed(n_key, hashing.TAG_BITS, rng)

    expected = hashing.verification_tag(x, seed)
    assert tag_wordwise(x, seed, hashing.TAG_BITS) == tag_int(expected)


def test_window_needs_two_words() -> None:
    """The 128-bit window is not generous, it is exactly enough.

    Output bit t-1 reads vwin[t-1 : t-1+W-1], so the widest bit touched is
    t + W - 2. With t = W = 64 that is 126, which fits in 2W only just - and is
    why the RTL asserts T <= W + 1.
    """
    t = hashing.TAG_BITS
    assert t + W - 2 == 126
    assert t + W - 2 < 2 * W
    assert t <= W + 1


def test_a_flipped_key_bit_changes_the_tag() -> None:
    """Verification has to detect a wrong key, not merely be reproducible."""
    rng = np.random.default_rng(99)
    n_key = 8 * W
    x = rng.integers(0, 2, size=n_key, dtype=np.uint8)
    seed = hashing.random_seed(n_key, hashing.TAG_BITS, rng)

    good = hashing.verification_tag(x, seed)
    for pos in (0, 1, n_key // 2, n_key - 1):
        bad_key = x.copy()
        bad_key[pos] ^= 1
        assert not np.array_equal(good, hashing.verification_tag(bad_key, seed))


def test_seed_length_convention() -> None:
    """n_key + t - 1 bits, spec section 4. The RTL sizes its window from this."""
    for n_key in (64, 128, 47_488):
        assert hashing.seed_length(n_key, hashing.TAG_BITS) == n_key + 63
        n_seed_words = -(-hashing.seed_length(n_key, hashing.TAG_BITS) // W)
        # the RTL reads one word beyond the last key word, and no further
        assert n_seed_words == n_key // W + 1

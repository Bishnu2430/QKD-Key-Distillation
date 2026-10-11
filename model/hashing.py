"""Toeplitz hashing: error verification and privacy amplification.

Implements docs/05-algorithm-spec.md sections 4 and 5. Both stages are the same
primitive with different output lengths, which mirrors contribution C3 (one
GF(2) multiply datapath shared by the verification tag and privacy
amplification).

Definition (spec section 5), for a seed of ``N + L - 1`` bits::

    k_i = XOR_j  seed[i + j] AND x_j,      i = 0 .. L-1,  j = 0 .. N-1

Two implementations, both exact and interchangeable:

``window``
    Direct sliding-window evaluation. O(N*L) work, clear and obviously correct,
    used as the test oracle and for small inputs.
``kronecker``
    The same product computed as one GF(2) polynomial multiplication, via
    Kronecker substitution into a single big-integer multiply. Each coefficient
    gets a byte-aligned slot wide enough that no carry crosses it, so the parity
    of a slot is the GF(2) coefficient. O(N log N)-ish and the only practical
    choice for block sizes of 10^5 and above.
"""

from __future__ import annotations

import numpy as np


def _slot_bytes(max_coeff: int) -> int:
    """Bytes per coefficient slot so that no carry leaks into the next slot."""
    return max(1, ((max_coeff.bit_length() + 1) + 7) // 8)


def _to_int(bits: np.ndarray, slot: int) -> int:
    buf = np.zeros((bits.size, slot), dtype=np.uint8)
    buf[:, 0] = bits
    return int.from_bytes(buf.tobytes(), "little")


def gf2_convolve(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Convolution of two bit vectors over GF(2), length ``len(a)+len(b)-1``."""
    a = np.asarray(a, dtype=np.uint8)
    b = np.asarray(b, dtype=np.uint8)
    if a.size == 0 or b.size == 0:
        return np.zeros(0, dtype=np.uint8)
    out_len = a.size + b.size - 1
    slot = _slot_bytes(min(a.size, b.size))
    prod = _to_int(a, slot) * _to_int(b, slot)
    raw = prod.to_bytes((out_len + 1) * slot, "little")
    slots = np.frombuffer(raw[: out_len * slot], dtype=np.uint8).reshape(out_len, slot)
    return (slots[:, 0] & 1).astype(np.uint8)


def toeplitz_hash(
    seed: np.ndarray,
    x: np.ndarray,
    out_len: int,
    method: str = "auto",
) -> np.ndarray:
    """Hash ``x`` (N bits) to ``out_len`` bits with the Toeplitz matrix from ``seed``.

    ``seed`` must hold ``N + out_len - 1`` bits (spec section 5).
    """
    seed = np.asarray(seed, dtype=np.uint8)
    x = np.asarray(x, dtype=np.uint8)
    n = x.size
    if out_len <= 0:
        return np.zeros(0, dtype=np.uint8)
    if seed.size != n + out_len - 1:
        raise ValueError(f"seed must be {n + out_len - 1} bits, got {seed.size}")

    if method == "auto":
        method = "window" if n * out_len <= 4_000_000 else "kronecker"

    if method == "window":
        windows = np.lib.stride_tricks.sliding_window_view(seed, n)[:out_len]
        return (np.bitwise_and(windows, x).sum(axis=1) & 1).astype(np.uint8)

    if method == "kronecker":
        conv = gf2_convolve(x[::-1], seed)
        return conv[n - 1 : n - 1 + out_len].copy()

    raise ValueError("method must be 'auto', 'window' or 'kronecker'")


def seed_length(n_bits: int, out_len: int) -> int:
    """Seed size required by :func:`toeplitz_hash`."""
    return n_bits + out_len - 1


def random_seed(n_bits: int, out_len: int, rng: np.random.Generator) -> np.ndarray:
    """Draw a public seed. In deployment this comes from a certified RNG."""
    return rng.integers(0, 2, size=seed_length(n_bits, out_len), dtype=np.uint8)


# ---------------------------------------------------------------------------
# the two protocol stages
# ---------------------------------------------------------------------------
TAG_BITS = 64  # spec section 4


def verification_tag(x: np.ndarray, seed: np.ndarray, tag_bits: int = TAG_BITS) -> np.ndarray:
    """Error-verification tag (spec section 4).

    2-universal, so two different frames collide with probability at most
    2^-tag_bits. The seed is public and drawn *after* decoding.
    """
    return toeplitz_hash(seed, x, tag_bits)


def privacy_amplify(block: np.ndarray, seed: np.ndarray, out_len: int) -> np.ndarray:
    """Compress a verified block to ``out_len`` secret bits (spec section 5)."""
    return toeplitz_hash(seed, block, out_len)

"""Bit-level conventions.

Implements docs/05-algorithm-spec.md section 2: index 0 is the first bit, and
bit j lives in 64-bit word j // 64 at position j % 64 (LSB-first).

Bit vectors are carried around as numpy uint8 arrays of 0/1, which is the
clearest representation for a reference model. Packing is only needed at the
boundaries: test vectors, files and anything the RTL will consume.
"""

from __future__ import annotations

import numpy as np

WORD_BITS = 64


def pack_words(bits: np.ndarray) -> np.ndarray:
    """Pack a 0/1 bit array into uint64 words, LSB-first (spec section 2).

    The final word is zero-padded when ``len(bits)`` is not a multiple of 64.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    pad = (-bits.size) % WORD_BITS
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    reshaped = bits.reshape(-1, WORD_BITS).astype(np.uint64)
    weights = (np.uint64(1) << np.arange(WORD_BITS, dtype=np.uint64))
    return (reshaped * weights).sum(axis=1, dtype=np.uint64)


def unpack_words(words: np.ndarray, n_bits: int) -> np.ndarray:
    """Inverse of :func:`pack_words`, truncated to ``n_bits``."""
    words = np.asarray(words, dtype=np.uint64)
    shifts = np.arange(WORD_BITS, dtype=np.uint64)
    bits = ((words[:, None] >> shifts) & np.uint64(1)).astype(np.uint8)
    return bits.reshape(-1)[:n_bits]


def to_hex_lines(bits: np.ndarray) -> list[str]:
    """Format a bit vector as one 16-digit hex word per line (test-vector format)."""
    return [f"{int(w):016x}" for w in pack_words(bits)]


def from_hex_lines(lines: list[str], n_bits: int) -> np.ndarray:
    """Parse the format produced by :func:`to_hex_lines`."""
    words = np.array([int(line.strip(), 16) for line in lines], dtype=np.uint64)
    return unpack_words(words, n_bits)


def hamming_weight(bits: np.ndarray) -> int:
    return int(np.count_nonzero(bits))


def xor(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.bitwise_xor(np.asarray(a, dtype=np.uint8), np.asarray(b, dtype=np.uint8))

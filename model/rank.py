"""GF(2) rank of selected parity-check columns.

The leakage accounting of docs/05-algorithm-spec.md section 3.5 may subtract
the punctured positions (``leak = m - p``) only when the punctured columns of H
are **linearly independent** over GF(2). Otherwise the conservative ``leak = m``
applies. The C1 sweep produced masks where this mattered, so the check is part
of building a mask, not an afterthought.

Columns are bit-packed into uint64 words and eliminated with a Numba kernel, so
a check on thousands of columns of a 20,000-row matrix takes seconds.
"""

from __future__ import annotations

import numpy as np
from numba import njit

from .code import QCCode


def pack_columns(code: QCCode, columns: np.ndarray) -> np.ndarray:
    """Bit-pack the given bit-columns of H into (len(columns), words) uint64."""
    columns = np.asarray(columns, dtype=np.int64)
    words = (code.m + 63) // 64
    out = np.zeros((columns.size, words), dtype=np.uint64)

    # row index of every 1 in a column: for base column c and offset j, the
    # check is r*Z + ((j - shift) mod Z) for every base row r with an entry
    z = code.z
    for idx, col in enumerate(columns):
        base_col, offset = divmod(int(col), z)
        for r in range(code.m_b):
            shift = int(code.base[r, base_col])
            if shift == -1:
                continue
            row = r * z + ((offset - shift) % z)
            out[idx, row >> 6] |= np.uint64(1) << np.uint64(row & 63)
    return out


@njit(cache=True)
def _rank_gf2(mat: np.ndarray) -> int:
    """Rank of bit-packed rows over GF(2), by Gaussian elimination."""
    n_rows, n_words = mat.shape
    rank = 0
    for word in range(n_words):
        for bit in range(64):
            mask = np.uint64(1) << np.uint64(bit)
            pivot = -1
            for r in range(rank, n_rows):
                if mat[r, word] & mask:
                    pivot = r
                    break
            if pivot < 0:
                continue
            if pivot != rank:
                for w in range(n_words):
                    tmp = mat[rank, w]
                    mat[rank, w] = mat[pivot, w]
                    mat[pivot, w] = tmp
            for r in range(n_rows):
                if r != rank and (mat[r, word] & mask):
                    for w in range(word, n_words):
                        mat[r, w] ^= mat[rank, w]
            rank += 1
            if rank == n_rows:
                return rank
    return rank


def columns_are_independent(code: QCCode, columns: np.ndarray) -> tuple[bool, int]:
    """Are these columns of H linearly independent over GF(2)?

    Returns ``(independent, rank)``. Independence means ``rank == len(columns)``
    and licenses the ``leak = m - p`` accounting.
    """
    columns = np.asarray(columns, dtype=np.int64)
    if columns.size == 0:
        return True, 0
    packed = pack_columns(code, columns)
    rank = int(_rank_gf2(packed))
    return rank == columns.size, rank


def mask_leakage(code: QCCode, mask, tag_bits: int = 64) -> tuple[int, bool]:
    """Leakage for a mask, with the rank condition actually checked.

    Returns ``(leak_bits, rank_ok)``.
    """
    _, punctured, _ = mask.positions()
    ok, _ = columns_are_independent(code, punctured)
    leak = code.m - (punctured.size if ok else 0) + tag_bits
    return int(leak), bool(ok)

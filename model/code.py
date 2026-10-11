"""Quasi-cyclic LDPC code representation, syndrome computation and rate masks.

Implements docs/05-algorithm-spec.md sections 3.1 to 3.3 and 3.5.

Conventions (normative, from the spec):

* The code is a base matrix ``B`` of shape (m_b, n_b) over {-1, 0 .. Z-1}.
  ``-1`` is an all-zero Z x Z block; ``k`` is the circulant ``P^k`` whose ones
  sit at ``(i, (i + k) mod Z)``.
* Therefore check ``r*Z + i`` touches variable ``c*Z + ((i + B[r, c]) mod Z)``.
* Every non-negative base entry is a *single* circulant, so within a block row
  (a decoder layer) each variable appears at most once. The parallel hardware
  and this serial model then produce identical results.
* Neighbours of a check are ordered by increasing base column, which fixes the
  tie-break in the decoder's minimum search.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

ZERO_BLOCK = -1


@dataclass(frozen=True)
class QCCode:
    """A lifted quasi-cyclic LDPC code."""

    base: np.ndarray  # (m_b, n_b) int16, -1 or a shift in [0, Z)
    z: int

    # flattened edge lists, grouped by layer and sorted by base column
    layer_ptr: np.ndarray = field(init=False, repr=False)
    edge_col: np.ndarray = field(init=False, repr=False)
    edge_shift: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        base = np.asarray(self.base, dtype=np.int32)
        object.__setattr__(self, "base", base)
        ptr, cols, shifts = [0], [], []
        for r in range(base.shape[0]):
            for c in range(base.shape[1]):  # increasing column = neighbour order
                if base[r, c] != ZERO_BLOCK:
                    cols.append(c)
                    shifts.append(int(base[r, c]) % self.z)
            ptr.append(len(cols))
        object.__setattr__(self, "layer_ptr", np.array(ptr, dtype=np.int32))
        object.__setattr__(self, "edge_col", np.array(cols, dtype=np.int32))
        object.__setattr__(self, "edge_shift", np.array(shifts, dtype=np.int32))

    # -- shape -----------------------------------------------------------
    @property
    def m_b(self) -> int:
        return int(self.base.shape[0])

    @property
    def n_b(self) -> int:
        return int(self.base.shape[1])

    @property
    def n(self) -> int:
        """Codeword length in bits."""
        return self.n_b * self.z

    @property
    def m(self) -> int:
        """Number of parity checks (syndrome length in bits)."""
        return self.m_b * self.z

    @property
    def rate0(self) -> float:
        """Design rate of the mother code, 1 - m/n."""
        return 1.0 - self.m / self.n

    @property
    def n_edges_base(self) -> int:
        """Non-zero entries of the base matrix (cycles per decoder iteration)."""
        return int(self.edge_col.size)

    # -- structure -------------------------------------------------------
    def layer_edges(self, r: int) -> tuple[np.ndarray, np.ndarray]:
        """(columns, shifts) of layer ``r``, in neighbour order."""
        lo, hi = self.layer_ptr[r], self.layer_ptr[r + 1]
        return self.edge_col[lo:hi], self.edge_shift[lo:hi]

    def variables_of_layer(self, r: int) -> np.ndarray:
        """(Z, deg) array: variable index for every check in layer r."""
        cols, shifts = self.layer_edges(r)
        rows = np.arange(self.z, dtype=np.int32)[:, None]
        return cols[None, :] * self.z + (rows + shifts[None, :]) % self.z

    def column_degrees(self) -> np.ndarray:
        deg = np.zeros(self.n_b, dtype=np.int32)
        for c in self.edge_col:
            deg[c] += 1
        return deg

    # -- parity ----------------------------------------------------------
    def syndrome(self, word: np.ndarray) -> np.ndarray:
        """s = H * word over GF(2) (spec section 3.2). ``word`` has n bits."""
        word = np.asarray(word, dtype=np.uint8)
        if word.size != self.n:
            raise ValueError(f"expected {self.n} bits, got {word.size}")
        s = np.zeros(self.m, dtype=np.uint8)
        for r in range(self.m_b):
            acc = np.zeros(self.z, dtype=np.uint8)
            for v in self.variables_of_layer(r).T:  # one base entry at a time
                acc ^= word[v]
            s[r * self.z : (r + 1) * self.z] = acc
        return s

    def syndrome_matches(self, word: np.ndarray, s: np.ndarray) -> bool:
        return bool(np.array_equal(self.syndrome(word), np.asarray(s, dtype=np.uint8)))


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------
def make_qc_code(
    n_b: int,
    m_b: int,
    z: int,
    col_weight: int = 3,
    seed: int = 0,
    shift_attempts: int = 200,
) -> QCCode:
    """Build a baseline QC-LDPC code with a (near-)regular base matrix.

    This is the **month-2 placeholder**: a random base graph with balanced row
    weights, random circulant shifts, and rejection sampling against 4-cycles.
    The real code design (PEG construction, degree distributions from density
    evolution, rate masks with a rank check) is contribution C1 and lands in
    docs/06-ldpc-code-design.md.

    4-cycle rule: two columns c1, c2 sharing rows r1, r2 create a length-4 cycle
    in the lifted graph when
    ``(B[r1,c1] - B[r1,c2]) == (B[r2,c1] - B[r2,c2])  (mod Z)``.
    """
    if col_weight > m_b:
        raise ValueError("column weight cannot exceed the number of block rows")
    rng = np.random.default_rng(seed)
    base = np.full((m_b, n_b), ZERO_BLOCK, dtype=np.int32)

    # place edges column by column, always into the currently emptiest rows
    row_load = np.zeros(m_b, dtype=np.int64)
    for c in range(n_b):
        order = np.lexsort((rng.random(m_b), row_load))
        rows = order[:col_weight]
        for r in rows:
            base[r, c] = 0  # placeholder, shift assigned below
            row_load[r] += 1

    # assign shifts with rejection sampling against 4-cycles
    for c in range(n_b):
        rows_c = np.flatnonzero(base[:, c] != ZERO_BLOCK)
        for r in rows_c:
            for _ in range(shift_attempts):
                cand = int(rng.integers(0, z))
                base[r, c] = cand
                if not _creates_four_cycle(base, r, c, z):
                    break
            else:  # pragma: no cover - only with a very dense base matrix
                base[r, c] = int(rng.integers(0, z))
    return QCCode(base=base, z=z)


def _creates_four_cycle(base: np.ndarray, r: int, c: int, z: int) -> bool:
    """Does the (partially filled) entry (r, c) close a length-4 cycle?"""
    m_b, n_b = base.shape
    other_rows = [rr for rr in range(m_b) if rr != r and base[rr, c] != ZERO_BLOCK]
    for c2 in range(n_b):
        if c2 == c or base[r, c2] == ZERO_BLOCK:
            continue
        d1 = (int(base[r, c]) - int(base[r, c2])) % z
        for r2 in other_rows:
            if base[r2, c2] == ZERO_BLOCK:
                continue
            d2 = (int(base[r2, c]) - int(base[r2, c2])) % z
            if d1 == d2:
                return True
    return False


# ---------------------------------------------------------------------------
# rate adaptation (spec section 3.3)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RateMask:
    """Puncture/shorten mask at base-column granularity.

    Whole base columns are punctured or shortened, so a mask is a handful of
    column indices rather than a bit map: cheap to store, cheap to apply in
    hardware, and it keeps the quasi-cyclic structure intact.
    """

    mask_id: int
    code: QCCode
    punctured_cols: np.ndarray
    shortened_cols: np.ndarray

    @property
    def z(self) -> int:
        return self.code.z

    @property
    def p(self) -> int:
        """Punctured positions."""
        return int(len(self.punctured_cols)) * self.z

    @property
    def s(self) -> int:
        """Shortened positions."""
        return int(len(self.shortened_cols)) * self.z

    @property
    def n_key(self) -> int:
        """Key bits carried by one frame."""
        return self.code.n - self.p - self.s

    @property
    def pi(self) -> float:
        return self.p / self.code.n

    @property
    def sigma(self) -> float:
        return self.s / self.code.n

    @property
    def rate(self) -> float:
        """Effective rate (R0 - sigma) / (1 - pi - sigma)."""
        return (self.code.rate0 - self.sigma) / (1.0 - self.pi - self.sigma)

    def positions(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(key, punctured, shortened) bit positions, each sorted ascending."""
        z = self.z
        punct = np.concatenate(
            [np.arange(c * z, (c + 1) * z) for c in self.punctured_cols]
        ) if len(self.punctured_cols) else np.empty(0, dtype=np.int64)
        short = np.concatenate(
            [np.arange(c * z, (c + 1) * z) for c in self.shortened_cols]
        ) if len(self.shortened_cols) else np.empty(0, dtype=np.int64)
        taken = np.zeros(self.code.n, dtype=bool)
        taken[punct] = True
        taken[short] = True
        key = np.flatnonzero(~taken)
        return key, np.sort(punct), np.sort(short)

    def leakage_bits(self, tag_bits: int = 64, assume_rank_ok: bool = True) -> int:
        """Disclosed bits per frame (spec section 3.5).

        ``m - p + t`` when the punctured columns of H are linearly independent,
        otherwise the conservative ``m + t``. The rank check itself is part of
        the M3 code design; until then the caller states the assumption.
        """
        base = self.code.m - self.p if assume_rank_ok else self.code.m
        return int(base + tag_bits)


def make_mask(
    code: QCCode,
    mask_id: int = 0,
    punctured_cols: np.ndarray | list[int] | None = None,
    shortened_cols: np.ndarray | list[int] | None = None,
) -> RateMask:
    punct = np.array(sorted(punctured_cols or []), dtype=np.int32)
    short = np.array(sorted(shortened_cols or []), dtype=np.int32)
    if set(punct.tolist()) & set(short.tolist()):
        raise ValueError("a base column cannot be both punctured and shortened")
    if len(punct) and punct.max() >= code.n_b:
        raise ValueError("punctured column out of range")
    if len(short) and short.max() >= code.n_b:
        raise ValueError("shortened column out of range")
    return RateMask(mask_id, code, punct, short)


def spread_columns(n_b: int, count: int, offset: int = 0) -> list[int]:
    """Pick ``count`` base columns spread evenly across the block, for masks."""
    if count <= 0:
        return []
    if count > n_b:
        raise ValueError("cannot select more columns than the code has")
    step = n_b / count
    return sorted({int((i + 0.5) * step + offset) % n_b for i in range(count)})

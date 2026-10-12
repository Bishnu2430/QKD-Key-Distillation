"""Progressive edge growth (PEG) construction for QC-LDPC base matrices.

PEG (Hu, Eleftheriou & Arnold, 2005) places edges one at a time, each into the
check node that is *furthest* from the variable in the current graph, which
maximises the local girth. Short cycles are what make iterative decoding
correlate its own messages, so a PEG base graph decodes closer to its density
evolution threshold than a random one.

Here PEG runs on the **base** graph of a quasi-cyclic code; the lifting shifts
are then chosen to avoid 4-cycles in the expanded graph
(docs/05-algorithm-spec.md section 3.1 requires one circulant per base entry).
"""

from __future__ import annotations

import numpy as np

from .code import ZERO_BLOCK, QCCode, _creates_four_cycle


def _reachable_checks(
    col: int,
    cols_to_rows: list[list[int]],
    rows_to_cols: list[list[int]],
    m_b: int,
) -> set[int]:
    """Checks reachable from ``col``, expanded until the set stops growing."""
    current = set(cols_to_rows[col])
    if not current:
        return current
    while True:
        if len(current) >= m_b:
            return current
        variables: set[int] = set()
        for r in current:
            variables.update(rows_to_cols[r])
        grown = set(current)
        for v in variables:
            grown.update(cols_to_rows[v])
        if grown == current:
            return current
        current = grown


def peg_adjacency(
    n_b: int,
    m_b: int,
    col_degrees: np.ndarray,
    rng: np.random.Generator,
) -> list[list[int]]:
    """Return, per base column, the rows it connects to."""
    cols_to_rows: list[list[int]] = [[] for _ in range(n_b)]
    rows_to_cols: list[list[int]] = [[] for _ in range(m_b)]

    # low-degree columns first: PEG's standard ordering
    order = np.argsort(col_degrees, kind="stable")
    for col in order:
        for edge in range(int(col_degrees[col])):
            if edge == 0:
                candidates = list(range(m_b))
            else:
                reachable = _reachable_checks(col, cols_to_rows, rows_to_cols, m_b)
                candidates = [r for r in range(m_b) if r not in reachable]
                if not candidates:  # graph saturated: fall back to any unused check
                    candidates = [r for r in range(m_b) if r not in cols_to_rows[col]]
            # lowest check degree wins, ties broken at random
            loads = np.array([len(rows_to_cols[r]) for r in candidates])
            noise = rng.random(len(candidates))
            best = candidates[int(np.lexsort((noise, loads))[0])]
            cols_to_rows[col].append(best)
            rows_to_cols[best].append(col)
    return cols_to_rows


def assign_shifts(
    cols_to_rows: list[list[int]],
    m_b: int,
    n_b: int,
    z: int,
    rng: np.random.Generator,
    attempts: int = 300,
) -> np.ndarray:
    """Fill a base matrix with circulant shifts, rejecting 4-cycles."""
    base = np.full((m_b, n_b), ZERO_BLOCK, dtype=np.int32)
    failures = 0
    for col in range(n_b):
        for row in cols_to_rows[col]:
            for _ in range(attempts):
                base[row, col] = int(rng.integers(0, z))
                if not _creates_four_cycle(base, row, col, z):
                    break
            else:
                failures += 1
    if failures:  # pragma: no cover - only for very dense base graphs
        print(f"warning: {failures} entries left with a 4-cycle")
    return base


def build_peg_code(
    n_b: int,
    m_b: int,
    z: int,
    col_degrees: np.ndarray | list[int] | int,
    seed: int = 0,
    attempts: int = 300,
) -> QCCode:
    """PEG base graph plus 4-cycle-free lifting."""
    degrees = (np.full(n_b, int(col_degrees), dtype=np.int32)
               if np.isscalar(col_degrees)
               else np.asarray(col_degrees, dtype=np.int32))
    if degrees.size != n_b:
        raise ValueError("one degree per base column is required")
    rng = np.random.default_rng(seed)
    adjacency = peg_adjacency(n_b, m_b, degrees, rng)
    base = assign_shifts(adjacency, m_b, n_b, z, rng, attempts)
    return QCCode(base=base, z=z)


def degrees_from_profile(
    n_b: int,
    node_fractions: dict[int, float],
    heavy_first: bool = True,
) -> np.ndarray:
    """Turn a node-perspective degree profile into a per-column degree list.

    With ``heavy_first`` the high-degree columns are placed at the front, which
    gives the rate masks a contiguous puncturable region to draw from
    (results/c1_rate_adaptation: the puncturable subset must be larger than the
    punctured set).
    """
    degrees: list[int] = []
    for deg in sorted(node_fractions, reverse=heavy_first):
        count = int(round(node_fractions[deg] * n_b))
        degrees.extend([deg] * count)
    if len(degrees) < n_b:  # rounding slack goes to the most common degree
        common = max(node_fractions, key=node_fractions.get)
        degrees.extend([common] * (n_b - len(degrees)))
    return np.array(degrees[:n_b], dtype=np.int32)

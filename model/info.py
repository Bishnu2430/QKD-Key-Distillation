"""Information-theoretic helpers.

Entropy, reconciliation efficiency and the rate-adaptation arithmetic of
docs/05-algorithm-spec.md section 3.3, plus the asymptotic secret-key fraction
used for sanity checks (docs/00-learning-guide.md section 7.3).
"""

from __future__ import annotations

import numpy as np


def h(p: float | np.ndarray) -> float | np.ndarray:
    """Binary entropy in bits. h(0) = h(1) = 0."""
    p = np.asarray(p, dtype=float)
    out = np.zeros_like(p)
    mask = (p > 0.0) & (p < 1.0)
    pm = p[mask] if p.ndim else p
    if p.ndim:
        out[mask] = -pm * np.log2(pm) - (1 - pm) * np.log2(1 - pm)
        return out
    if not mask:
        return 0.0
    return float(-p * np.log2(p) - (1 - p) * np.log2(1 - p))


def efficiency(leak_bits: int, n_key: int, qber: float) -> float:
    """f = leak / (n_key * h(Q)); the Slepian-Wolf limit is f = 1."""
    denom = n_key * h(qber)
    if denom <= 0:
        return float("inf")
    return leak_bits / denom


def effective_rate(r0: float, pi: float, sigma: float) -> float:
    """R = (R0 - sigma) / (1 - pi - sigma)  (Elkouss et al. 2011)."""
    denom = 1.0 - pi - sigma
    if denom <= 0:
        raise ValueError("puncturing plus shortening must leave key positions")
    return (r0 - sigma) / denom


def efficiency_from_rate(rate: float, qber: float) -> float:
    """f = (1 - R) / h(Q)."""
    hq = h(qber)
    if hq <= 0:
        return float("inf")
    return (1.0 - rate) / hq


def required_rate(qber: float, f: float = 1.1) -> float:
    """Code rate needed to reconcile at QBER with efficiency f: R = 1 - f h(Q)."""
    return 1.0 - f * h(qber)


def secret_fraction(qber: float, f: float = 1.1) -> float:
    """Asymptotic BB84 secret-key fraction r = 1 - h(Q) - f h(Q), floored at 0.

    A sanity reference only; the finite-key calculation lives elsewhere
    (docs/04-system-model.md section 5).
    """
    return max(0.0, 1.0 - h(qber) - f * h(qber))


def channel_llr(qber: float) -> float:
    """ln((1-Q)/Q): the magnitude of a BSC channel LLR."""
    if not 0.0 < qber < 0.5:
        raise ValueError("qber must lie in (0, 0.5)")
    return float(np.log((1.0 - qber) / qber))

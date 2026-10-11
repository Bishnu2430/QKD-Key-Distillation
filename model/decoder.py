"""L1 floating-point LDPC syndrome decoder.

Implements docs/05-algorithm-spec.md section 3.6 (layered normalized min-sum)
and 3.7 (the floating-point reference, including the optional sum-product
check-node rule).

Structure of one iteration, for every layer (block row) in order:

    T      = L[v] - R                      variable-to-check
    sign   = (-1)^syndrome * prod(sign T)  syndrome-aware check update
    R_new  = sign_j * alpha * (min2 if j is the argmin else min1)
    L[v]   = T + R_new                     immediate (layered) update

Because every base entry is a single circulant, each variable appears at most
once per layer, so the Z checks of a layer are independent and the vectorised
update below is exactly the serial result the spec defines.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .code import QCCode

LARGE = 1.0e6


@dataclass
class DecodeResult:
    ok: bool
    iterations: int
    x_hat: np.ndarray  # full n-bit hard decision
    llr: np.ndarray  # final a-posteriori LLRs

    def key_bits(self, key_positions: np.ndarray) -> np.ndarray:
        return self.x_hat[key_positions]


def _check_update_minsum(t: np.ndarray, sign_syndrome: np.ndarray, alpha: float) -> np.ndarray:
    """Normalized min-sum check node, vectorised over the Z checks of a layer.

    ``t`` is (Z, deg); ``sign_syndrome`` is (Z,) holding +1 / -1 for s_i = 0 / 1.
    """
    signs = np.where(t >= 0.0, 1.0, -1.0)
    mag = np.abs(t)

    idx = np.argmin(mag, axis=1)  # first occurrence: ties break on neighbour order
    rows = np.arange(mag.shape[0])
    min1 = mag[rows, idx]
    mag_wo = mag.copy()
    mag_wo[rows, idx] = np.inf
    min2 = mag_wo.min(axis=1)

    out_mag = np.broadcast_to(min1[:, None], mag.shape).copy()
    out_mag[rows, idx] = min2

    sgn = sign_syndrome * signs.prod(axis=1)
    return sgn[:, None] * signs * (alpha * out_mag)


def _check_update_sumproduct(t: np.ndarray, sign_syndrome: np.ndarray) -> np.ndarray:
    """Exact tanh rule, for reference comparisons (spec section 3.7)."""
    tt = np.tanh(np.clip(t, -30.0, 30.0) / 2.0)
    tt = np.where(tt == 0.0, 1e-12, tt)
    total = np.prod(tt, axis=1)[:, None]
    excl = np.clip(total / tt, -1 + 1e-12, 1 - 1e-12)
    return sign_syndrome[:, None] * 2.0 * np.arctanh(excl)


def decode(
    code: QCCode,
    llr_init: np.ndarray,
    syndrome: np.ndarray,
    max_iters: int = 32,
    alpha: float = 0.75,
    algorithm: str = "nms",
) -> DecodeResult:
    """Decode one frame.

    Parameters
    ----------
    llr_init : Bob's initial LLRs, n values (positive favours bit 0).
    syndrome : Alice's m-bit syndrome.
    alpha    : normalisation factor; ignored for ``algorithm="spa"``.
    algorithm: ``"nms"`` (normalized min-sum) or ``"spa"`` (sum-product).

    Returns the hard decision, whether it satisfies the syndrome, and how many
    iterations were used. Early termination is evaluated only at iteration
    boundaries, so every implementation stops on the same iteration.
    """
    if algorithm not in ("nms", "spa"):
        raise ValueError("algorithm must be 'nms' or 'spa'")

    llr = np.array(llr_init, dtype=np.float64, copy=True)
    syndrome = np.asarray(syndrome, dtype=np.uint8)
    r_msg = np.zeros((code.n_edges_base, code.z), dtype=np.float64)

    # cache the per-layer variable index maps once
    layer_vars = [code.variables_of_layer(r) for r in range(code.m_b)]
    sign_syn = [
        np.where(syndrome[r * code.z : (r + 1) * code.z] == 0, 1.0, -1.0)
        for r in range(code.m_b)
    ]

    for it in range(1, max_iters + 1):
        for r in range(code.m_b):
            lo, hi = code.layer_ptr[r], code.layer_ptr[r + 1]
            v = layer_vars[r]  # (Z, deg)
            t = llr[v] - r_msg[lo:hi].T  # variable-to-check
            np.clip(t, -LARGE, LARGE, out=t)

            if algorithm == "nms":
                r_new = _check_update_minsum(t, sign_syn[r], alpha)
            else:
                r_new = _check_update_sumproduct(t, sign_syn[r])

            llr[v] = t + r_new  # safe: each variable appears once per layer
            r_msg[lo:hi] = r_new.T

        x_hat = (llr < 0.0).astype(np.uint8)
        if code.syndrome_matches(x_hat, syndrome):
            return DecodeResult(True, it, x_hat, llr)

    x_hat = (llr < 0.0).astype(np.uint8)
    return DecodeResult(False, max_iters, x_hat, llr)

"""L2 bit-true fixed-point model.

Implements docs/05-algorithm-spec.md sections 2.1, 3.4 and 3.6 exactly as the
RTL will: integer word widths, symmetric saturation, shift-based normalisation
and first-occurrence tie-breaking. This module is the **oracle** the RTL is
checked against (verification level L3), so every operation here is the one the
hardware performs, not a convenient approximation of it.

Differences from :mod:`model.decoder` (L1) are all deliberate:

* LLRs are integers on a grid of ``delta`` volts-per-LSB, not reals.
* Every sum saturates to a symmetric range; nothing wraps.
* ``alpha`` is a sum of right shifts, so 0.75 truncates rather than rounding.
* Magnitudes entering the check node are clipped to the message width.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .code import QCCode, RateMask
from .info import channel_llr


@dataclass(frozen=True)
class FixedConfig:
    """Fixed-point parameters (spec section 2.1 defaults)."""

    w_ch: int = 5  # channel LLR magnitude width
    w_msg: int = 6  # check-to-variable message width
    w_app: int = 8  # a-posteriori LLR width
    delta: float = 0.25  # LLR quantisation step
    alpha_shifts: tuple[int, ...] = (1, 2)  # 0.75 = 1/2 + 1/4

    @property
    def max_ch(self) -> int:
        return (1 << (self.w_ch - 1)) - 1

    @property
    def max_msg(self) -> int:
        return (1 << (self.w_msg - 1)) - 1

    @property
    def max_app(self) -> int:
        return (1 << (self.w_app - 1)) - 1

    @property
    def alpha(self) -> float:
        """The effective normalisation factor, for reporting."""
        return float(sum(2.0**-s for s in self.alpha_shifts))

    def describe(self) -> str:
        return (f"W_CH={self.w_ch} W_MSG={self.w_msg} W_APP={self.w_app} "
                f"delta={self.delta} alpha={self.alpha}")


DEFAULT = FixedConfig()


def saturate(v: np.ndarray, limit: int) -> np.ndarray:
    """Symmetric saturation to [-limit, +limit] (spec section 2)."""
    return np.clip(v, -limit, limit)


def normalise(mag: np.ndarray, shifts: tuple[int, ...]) -> np.ndarray:
    """alpha * mag as a sum of right shifts on a non-negative integer.

    With shifts (1, 2) this is ``(v >> 1) + (v >> 2)``: 0.75 with truncation,
    exactly what the RTL computes with two wires and an adder.
    """
    out = np.zeros_like(mag)
    for s in shifts:
        out += mag >> s
    return out


def channel_amplitude(qber_est: float, cfg: FixedConfig = DEFAULT) -> int:
    """A = min(max_ch, max(1, round(ln((1-Q)/Q) / delta)))  (spec section 3.4).

    ``round`` is round-half-away-from-zero, matching the spec rather than
    Python's banker's rounding.
    """
    raw = channel_llr(qber_est) / cfg.delta
    rounded = int(np.floor(raw + 0.5))
    return int(min(cfg.max_ch, max(1, rounded)))


def initial_llr(
    mask: RateMask,
    y_key: np.ndarray,
    qber_est: float,
    cfg: FixedConfig = DEFAULT,
) -> np.ndarray:
    """Integer starting LLRs: +/-A on key bits, 0 punctured, +max_app shortened."""
    key_pos, punct_pos, short_pos = mask.positions()
    amp = channel_amplitude(qber_est, cfg)
    llr = np.zeros(mask.code.n, dtype=np.int32)
    llr[key_pos] = np.where(y_key == 0, amp, -amp)
    llr[punct_pos] = 0
    llr[short_pos] = cfg.max_app
    return llr


@dataclass
class FixedDecodeResult:
    ok: bool
    iterations: int
    x_hat: np.ndarray
    llr: np.ndarray

    def key_bits(self, key_positions: np.ndarray) -> np.ndarray:
        return self.x_hat[key_positions]


def decode(
    code: QCCode,
    llr_init: np.ndarray,
    syndrome: np.ndarray,
    max_iters: int = 32,
    cfg: FixedConfig = DEFAULT,
) -> FixedDecodeResult:
    """Bit-true layered normalized min-sum (spec section 3.6).

    The loop mirrors the pseudocode in the spec line for line; the only
    vectorisation is over the Z independent checks of a layer, which the
    single-circulant constraint guarantees is equivalent to processing them one
    at a time.
    """
    llr = np.array(llr_init, dtype=np.int32, copy=True)
    syndrome = np.asarray(syndrome, dtype=np.uint8)
    r_msg = np.zeros((code.n_edges_base, code.z), dtype=np.int32)

    layer_vars = [code.variables_of_layer(r) for r in range(code.m_b)]
    sign_syn = [
        np.where(syndrome[r * code.z : (r + 1) * code.z] == 0, 1, -1).astype(np.int32)
        for r in range(code.m_b)
    ]
    rows = np.arange(code.z)

    for it in range(1, max_iters + 1):
        for r in range(code.m_b):
            lo, hi = code.layer_ptr[r], code.layer_ptr[r + 1]
            v = layer_vars[r]

            t = saturate(llr[v] - r_msg[lo:hi].T, cfg.max_app)  # variable-to-check
            signs = np.where(t >= 0, 1, -1).astype(np.int32)  # sign(0) = +1
            a = np.minimum(np.abs(t), cfg.max_msg)  # clip into message width

            idx = np.argmin(a, axis=1)  # first occurrence breaks ties
            min1 = a[rows, idx]
            a_wo = a.copy()
            a_wo[rows, idx] = cfg.max_msg + 1
            min2 = a_wo.min(axis=1)

            mag = np.broadcast_to(min1[:, None], a.shape).copy()
            mag[rows, idx] = min2

            sgn = sign_syn[r] * signs.prod(axis=1)
            r_new = (sgn[:, None] * signs * normalise(mag, cfg.alpha_shifts)).astype(np.int32)

            llr[v] = saturate(t + r_new, cfg.max_app)
            r_msg[lo:hi] = r_new.T

        x_hat = (llr < 0).astype(np.uint8)
        if code.syndrome_matches(x_hat, syndrome):
            return FixedDecodeResult(True, it, x_hat, llr)

    return FixedDecodeResult(False, max_iters, (llr < 0).astype(np.uint8), llr)


def decode_layer_trace(
    code: QCCode,
    llr_init: np.ndarray,
    syndrome: np.ndarray,
    n_layers: int,
    cfg: FixedConfig = DEFAULT,
) -> list[np.ndarray]:
    """Run the first ``n_layers`` layers of iteration 1, snapshotting the APP array.

    Returns ``n_layers + 1`` arrays: the initial state, then the state after each
    layer. This is the oracle for RTL bring-up stage 2 - a mismatch at layer k
    localises the bug to one layer instead of one frame
    (docs/stages/02-layer-datapath.md).

    The arithmetic is identical to :func:`decode`; only the stopping point and
    the snapshots differ.
    """
    llr = np.array(llr_init, dtype=np.int32, copy=True)
    syndrome = np.asarray(syndrome, dtype=np.uint8)
    r_msg = np.zeros((code.n_edges_base, code.z), dtype=np.int32)
    rows = np.arange(code.z)
    snapshots = [llr.copy()]

    for r in range(min(n_layers, code.m_b)):
        lo, hi = code.layer_ptr[r], code.layer_ptr[r + 1]
        v = code.variables_of_layer(r)
        sign_syn = np.where(syndrome[r * code.z : (r + 1) * code.z] == 0, 1, -1).astype(np.int32)

        t = saturate(llr[v] - r_msg[lo:hi].T, cfg.max_app)
        signs = np.where(t >= 0, 1, -1).astype(np.int32)
        a = np.minimum(np.abs(t), cfg.max_msg)

        idx = np.argmin(a, axis=1)
        min1 = a[rows, idx]
        a_wo = a.copy()
        a_wo[rows, idx] = cfg.max_msg + 1
        min2 = a_wo.min(axis=1)

        mag = np.broadcast_to(min1[:, None], a.shape).copy()
        mag[rows, idx] = min2

        sgn = sign_syn * signs.prod(axis=1)
        r_new = (sgn[:, None] * signs * normalise(mag, cfg.alpha_shifts)).astype(np.int32)

        llr[v] = saturate(t + r_new, cfg.max_app)
        r_msg[lo:hi] = r_new.T
        snapshots.append(llr.copy())

    return snapshots

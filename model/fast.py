"""Numba-accelerated decoders.

Scalar-loop kernels that reproduce :mod:`model.decoder` (L1 float) and
:mod:`model.fixed` (L2 bit-true) **exactly** — same tie-breaking, same
saturation, same iteration counts — but fast enough for the sample sizes
REQ-VER-02 asks for (at least 100 frame errors or 10^5 frames per point).

Equivalence with the reference implementations is a test, not a hope: see
``tests/test_fast.py``. If a kernel here ever disagrees with the reference, the
reference is right and the kernel is the bug.
"""

from __future__ import annotations

import numpy as np
from numba import njit

from .code import QCCode
from .fixed import DEFAULT, FixedConfig, FixedDecodeResult
from .decoder import DecodeResult

MAX_DEGREE = 64  # per-check scratch size; base rows are far smaller than this


@njit(cache=True)
def _syndrome_ok(llr, syn, layer_ptr, edge_col, edge_shift, z) -> bool:
    m_b = layer_ptr.size - 1
    for r in range(m_b):
        lo, hi = layer_ptr[r], layer_ptr[r + 1]
        for zz in range(z):
            parity = 0
            for e in range(lo, hi):
                v = edge_col[e] * z + ((zz + edge_shift[e]) % z)
                if llr[v] < 0:
                    parity ^= 1
            if parity != syn[r * z + zz]:
                return False
    return True


@njit(cache=True)
def _decode_fixed_kernel(llr, syn, layer_ptr, edge_col, edge_shift, z,
                         max_iters, max_app, max_msg, shifts):
    m_b = layer_ptr.size - 1
    r_msg = np.zeros((edge_col.size, z), dtype=np.int32)
    t_buf = np.empty(MAX_DEGREE, dtype=np.int32)
    a_buf = np.empty(MAX_DEGREE, dtype=np.int32)

    for it in range(1, max_iters + 1):
        for r in range(m_b):
            lo, hi = layer_ptr[r], layer_ptr[r + 1]
            deg = hi - lo
            for zz in range(z):
                sgn = 1 if syn[r * z + zz] == 0 else -1
                min1 = max_msg + 1
                min2 = max_msg + 1
                idx = -1

                for e in range(deg):
                    v = edge_col[lo + e] * z + ((zz + edge_shift[lo + e]) % z)
                    t = llr[v] - r_msg[lo + e, zz]
                    if t > max_app:
                        t = max_app
                    elif t < -max_app:
                        t = -max_app
                    t_buf[e] = t

                    if t >= 0:
                        a = t
                    else:
                        a = -t
                        sgn = -sgn
                    if a > max_msg:
                        a = max_msg
                    a_buf[e] = a

                    if a < min1:          # strict: keeps the first occurrence
                        min2 = min1
                        min1 = a
                        idx = e
                    elif a < min2:
                        min2 = a

                for e in range(deg):
                    mag = min2 if e == idx else min1
                    norm = 0
                    for k in range(shifts.size):
                        norm += mag >> shifts[k]
                    t = t_buf[e]
                    rn = sgn * norm if t >= 0 else -sgn * norm
                    r_msg[lo + e, zz] = rn

                    new = t + rn
                    if new > max_app:
                        new = max_app
                    elif new < -max_app:
                        new = -max_app
                    llr[edge_col[lo + e] * z + ((zz + edge_shift[lo + e]) % z)] = new

        if _syndrome_ok(llr, syn, layer_ptr, edge_col, edge_shift, z):
            return True, it
    return False, max_iters


@njit(cache=True)
def _decode_float_kernel(llr, syn, layer_ptr, edge_col, edge_shift, z,
                         max_iters, alpha, large):
    m_b = layer_ptr.size - 1
    r_msg = np.zeros((edge_col.size, z), dtype=np.float64)
    t_buf = np.empty(MAX_DEGREE, dtype=np.float64)

    for it in range(1, max_iters + 1):
        for r in range(m_b):
            lo, hi = layer_ptr[r], layer_ptr[r + 1]
            deg = hi - lo
            for zz in range(z):
                sgn = 1.0 if syn[r * z + zz] == 0 else -1.0
                min1 = np.inf
                min2 = np.inf
                idx = -1

                for e in range(deg):
                    v = edge_col[lo + e] * z + ((zz + edge_shift[lo + e]) % z)
                    t = llr[v] - r_msg[lo + e, zz]
                    if t > large:
                        t = large
                    elif t < -large:
                        t = -large
                    t_buf[e] = t

                    if t >= 0.0:
                        a = t
                    else:
                        a = -t
                        sgn = -sgn

                    if a < min1:
                        min2 = min1
                        min1 = a
                        idx = e
                    elif a < min2:
                        min2 = a

                for e in range(deg):
                    mag = min2 if e == idx else min1
                    t = t_buf[e]
                    rn = sgn * alpha * mag if t >= 0.0 else -sgn * alpha * mag
                    r_msg[lo + e, zz] = rn
                    llr[edge_col[lo + e] * z + ((zz + edge_shift[lo + e]) % z)] = t + rn

        if _syndrome_ok(llr, syn, layer_ptr, edge_col, edge_shift, z):
            return True, it
    return False, max_iters


def decode_fixed(
    code: QCCode,
    llr_init: np.ndarray,
    syndrome: np.ndarray,
    max_iters: int = 32,
    cfg: FixedConfig = DEFAULT,
) -> FixedDecodeResult:
    """Accelerated equivalent of :func:`model.fixed.decode`."""
    llr = np.array(llr_init, dtype=np.int32, copy=True)
    ok, iters = _decode_fixed_kernel(
        llr, np.asarray(syndrome, dtype=np.uint8),
        code.layer_ptr, code.edge_col, code.edge_shift, code.z,
        max_iters, cfg.max_app, cfg.max_msg,
        np.asarray(cfg.alpha_shifts, dtype=np.int64),
    )
    return FixedDecodeResult(bool(ok), int(iters), (llr < 0).astype(np.uint8), llr)


def decode_float(
    code: QCCode,
    llr_init: np.ndarray,
    syndrome: np.ndarray,
    max_iters: int = 32,
    alpha: float = 0.75,
    large: float = 1.0e6,
) -> DecodeResult:
    """Accelerated equivalent of :func:`model.decoder.decode` (``algorithm="nms"``)."""
    llr = np.array(llr_init, dtype=np.float64, copy=True)
    ok, iters = _decode_float_kernel(
        llr, np.asarray(syndrome, dtype=np.uint8),
        code.layer_ptr, code.edge_col, code.edge_shift, code.z,
        max_iters, float(alpha), float(large),
    )
    return DecodeResult(bool(ok), int(iters), (llr < 0).astype(np.uint8), llr)


def warm_up(code: QCCode) -> None:
    """Trigger JIT compilation once, so timing runs measure the kernel."""
    llr_i = np.zeros(code.n, dtype=np.int32)
    llr_f = np.zeros(code.n, dtype=np.float64)
    syn = np.zeros(code.m, dtype=np.uint8)
    decode_fixed(code, llr_i, syn, max_iters=1)
    decode_float(code, llr_f, syn, max_iters=1)

"""Frame construction: Alice's word, the channel, and Bob's initial LLRs.

Implements docs/05-algorithm-spec.md sections 3.3 and 3.4, with the sifted-key
channel model of docs/04-system-model.md section 2 (i.i.d. BSC(Q)).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .code import RateMask
from .info import channel_llr

#: LLR magnitude used for shortened positions in the float model (spec 3.7).
LLR_KNOWN = 1.0e3


@dataclass
class Frame:
    """One reconciliation frame, from both parties' points of view."""

    mask: RateMask
    x_key: np.ndarray  # Alice's key bits, n_key
    y_key: np.ndarray  # Bob's received bits, n_key
    word: np.ndarray  # Alice's full n-bit word (key + fill)
    syndrome: np.ndarray  # m bits, sent over the public channel
    llr: np.ndarray  # Bob's initial LLRs, n values
    qber_true: float
    n_errors: int

    @property
    def n_key(self) -> int:
        return int(self.x_key.size)


def build_alice_word(mask: RateMask, x_key: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Place key bits, private random fill and known zeros (spec section 3.3)."""
    key_pos, punct_pos, short_pos = mask.positions()
    if x_key.size != key_pos.size:
        raise ValueError(f"expected {key_pos.size} key bits, got {x_key.size}")
    word = np.zeros(mask.code.n, dtype=np.uint8)
    word[key_pos] = x_key
    if punct_pos.size:  # private random bits, unknown to Bob and to Eve
        word[punct_pos] = rng.integers(0, 2, size=punct_pos.size, dtype=np.uint8)
    word[short_pos] = 0  # known to both parties
    return word


def initial_llr(mask: RateMask, y_key: np.ndarray, qber_est: float) -> np.ndarray:
    """Bob's starting LLRs: +/-ln((1-Q)/Q) on key bits, 0 punctured, +max shortened."""
    key_pos, punct_pos, short_pos = mask.positions()
    amp = channel_llr(qber_est)
    llr = np.zeros(mask.code.n, dtype=np.float64)
    llr[key_pos] = np.where(y_key == 0, amp, -amp)
    llr[punct_pos] = 0.0
    llr[short_pos] = LLR_KNOWN
    return llr


def make_frame(
    mask: RateMask,
    qber: float,
    rng: np.random.Generator,
    qber_est: float | None = None,
) -> Frame:
    """Draw a random key, pass it through BSC(qber) and build both views.

    ``qber_est`` is what the decoder is told; leaving it ``None`` means a
    perfect estimate. Setting it differently drives the estimation-mismatch
    sweep of experiment E1.
    """
    key_pos, _, _ = mask.positions()
    n_key = key_pos.size
    x_key = rng.integers(0, 2, size=n_key, dtype=np.uint8)
    errors = (rng.random(n_key) < qber).astype(np.uint8)
    y_key = x_key ^ errors

    word = build_alice_word(mask, x_key, rng)
    syndrome = mask.code.syndrome(word)
    llr = initial_llr(mask, y_key, qber if qber_est is None else qber_est)

    return Frame(
        mask=mask,
        x_key=x_key,
        y_key=y_key,
        word=word,
        syndrome=syndrome,
        llr=llr,
        qber_true=qber,
        n_errors=int(errors.sum()),
    )

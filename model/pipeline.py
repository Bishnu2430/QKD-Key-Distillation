"""End-to-end L1 pipeline: reconcile, verify, accumulate, privacy-amplify.

Ties together docs/05-algorithm-spec.md sections 3 to 6 and the accounting of
docs/04-system-model.md section 4. This is the floating-point reference used
for experiments E1 and E3; it is also the scaffolding the bit-true L2 model
will slot into.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import hashing
from .code import RateMask
from .decoder import decode
from .frame import make_frame
from .info import efficiency


@dataclass
class FrameOutcome:
    ok: bool  # decoded and verified
    decoded: bool  # satisfied the syndrome
    verified: bool  # tag matched
    iterations: int
    n_key: int
    leak_bits: int
    bit_errors_in: int
    bit_errors_out: int  # residual errors after decoding (0 when ok)
    key_bits: np.ndarray | None


@dataclass
class BlockResult:
    frames: list[FrameOutcome] = field(default_factory=list)
    block_bits: np.ndarray | None = None
    secret_key: np.ndarray | None = None

    @property
    def n_frames(self) -> int:
        return len(self.frames)

    @property
    def n_ok(self) -> int:
        return sum(1 for f in self.frames if f.ok)

    @property
    def fer(self) -> float:
        return 1.0 - self.n_ok / self.n_frames if self.n_frames else float("nan")

    @property
    def leak_total(self) -> int:
        return sum(f.leak_bits for f in self.frames)

    @property
    def avg_iterations(self) -> float:
        return float(np.mean([f.iterations for f in self.frames])) if self.frames else float("nan")

    @property
    def block_len(self) -> int:
        return 0 if self.block_bits is None else int(self.block_bits.size)

    def undetected_errors(self) -> int:
        """Frames the verifier accepted that were in fact wrong. Must be 0."""
        return sum(1 for f in self.frames if f.ok and f.bit_errors_out > 0)


def process_frame(
    mask: RateMask,
    qber: float,
    rng: np.random.Generator,
    max_iters: int = 32,
    alpha: float = 0.75,
    qber_est: float | None = None,
    tag_bits: int = hashing.TAG_BITS,
    algorithm: str = "nms",
) -> FrameOutcome:
    """Reconcile and verify one frame (spec sections 3 and 4)."""
    frame = make_frame(mask, qber, rng, qber_est=qber_est)
    key_pos, _, _ = mask.positions()

    res = decode(
        mask.code,
        frame.llr,
        frame.syndrome,
        max_iters=max_iters,
        alpha=alpha,
        algorithm=algorithm,
    )
    x_hat_key = res.key_bits(key_pos)
    residual = int(np.count_nonzero(x_hat_key ^ frame.x_key))

    verified = False
    if res.ok:
        seed = hashing.random_seed(frame.n_key, tag_bits, rng)
        tag_a = hashing.verification_tag(frame.x_key, seed, tag_bits)
        tag_b = hashing.verification_tag(x_hat_key, seed, tag_bits)
        verified = bool(np.array_equal(tag_a, tag_b))

    ok = bool(res.ok and verified)
    return FrameOutcome(
        ok=ok,
        decoded=bool(res.ok),
        verified=verified,
        iterations=res.iterations,
        n_key=frame.n_key,
        leak_bits=mask.leakage_bits(tag_bits=tag_bits),
        bit_errors_in=frame.n_errors,
        bit_errors_out=residual,
        key_bits=x_hat_key if ok else None,
    )


def process_block(
    mask: RateMask,
    qber: float,
    n_frames: int,
    rng: np.random.Generator,
    out_len: int | None = None,
    **frame_kwargs,
) -> BlockResult:
    """Run ``n_frames`` frames, concatenate the survivors and hash them down.

    ``out_len`` is the final key length. In the real protocol it comes from the
    finite-key formula (docs/04-system-model.md section 5); here it defaults to
    the asymptotic estimate ``N - leak`` so the pipeline can be exercised.
    """
    result = BlockResult()
    kept: list[np.ndarray] = []

    for _ in range(n_frames):
        outcome = process_frame(mask, qber, rng, **frame_kwargs)
        result.frames.append(outcome)
        if outcome.ok and outcome.key_bits is not None:
            kept.append(outcome.key_bits)

    if not kept:
        return result

    block = np.concatenate(kept)
    result.block_bits = block

    if out_len is None:
        leak_kept = sum(f.leak_bits for f in result.frames if f.ok)
        out_len = max(0, int(block.size - leak_kept))
    if out_len > 0:
        seed = hashing.random_seed(block.size, out_len, rng)
        result.secret_key = hashing.privacy_amplify(block, seed, out_len)
    return result


def measure(
    mask: RateMask,
    qber: float,
    n_frames: int,
    seed: int = 0,
    **frame_kwargs,
) -> dict:
    """FER, efficiency and iteration statistics for one (mask, QBER) point.

    This is the unit that experiment E1 sweeps.
    """
    rng = np.random.default_rng(seed)
    outcomes = [process_frame(mask, qber, rng, **frame_kwargs) for _ in range(n_frames)]

    n_ok = sum(1 for o in outcomes if o.ok)
    iters_ok = [o.iterations for o in outcomes if o.ok]
    leak = outcomes[0].leak_bits
    return {
        "qber": qber,
        "mask_id": mask.mask_id,
        "n": mask.code.n,
        "n_key": mask.n_key,
        "rate": mask.rate,
        "p": mask.p,
        "s": mask.s,
        "frames": n_frames,
        "fer": 1.0 - n_ok / n_frames,
        "efficiency": efficiency(leak, mask.n_key, qber),
        "leak_bits": leak,
        "avg_iters_ok": float(np.mean(iters_ok)) if iters_ok else float("nan"),
        "max_iters_ok": int(np.max(iters_ok)) if iters_ok else 0,
        "undetected": sum(1 for o in outcomes if o.ok and o.bit_errors_out > 0),
        # f < 1 with frames actually decoding would mean the leakage accounting
        # is wrong (spec 3.5 rank condition), not that we beat Slepian-Wolf
        "leak_below_limit": bool(efficiency(leak, mask.n_key, qber) < 1.0),
    }

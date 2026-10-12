"""Decoder throughput benchmark: reference implementations against the Numba kernels.

Answers the practical question behind REQ-VER-02: can we afford the 10^5-frame
runs the published curves need?

    uv run python scripts/bench_decoder.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import code as qc  # noqa: E402
from model import decoder as l1  # noqa: E402
from model import fast, fixed, frame  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def bench(code: qc.QCCode, qber: float, n_frames: int, max_iters: int, seed: int) -> dict:
    mask = qc.make_mask(code, 0)
    rng = np.random.default_rng(seed)
    frames = [frame.make_frame(mask, qber, rng) for _ in range(n_frames)]
    llrs_fixed = [fixed.initial_llr(mask, f.y_key, qber) for f in frames]
    fast.warm_up(code)

    t0 = time.perf_counter()
    for f in frames:
        l1.decode(code, f.llr, f.syndrome, max_iters=max_iters)
    t_ref_float = time.perf_counter() - t0

    t0 = time.perf_counter()
    for f, llr in zip(frames, llrs_fixed):
        fixed.decode(code, llr, f.syndrome, max_iters=max_iters)
    t_ref_fixed = time.perf_counter() - t0

    t0 = time.perf_counter()
    for f in frames:
        fast.decode_float(code, f.llr, f.syndrome, max_iters=max_iters)
    t_fast_float = time.perf_counter() - t0

    t0 = time.perf_counter()
    for f, llr in zip(frames, llrs_fixed):
        fast.decode_fixed(code, llr, f.syndrome, max_iters=max_iters)
    t_fast_fixed = time.perf_counter() - t0

    return {
        "n": code.n, "qber": qber, "frames": n_frames,
        "ref_float_s": round(t_ref_float, 3), "ref_fixed_s": round(t_ref_fixed, 3),
        "fast_float_s": round(t_fast_float, 3), "fast_fixed_s": round(t_fast_fixed, 3),
        "speedup_float": round(t_ref_float / t_fast_float, 1),
        "speedup_fixed": round(t_ref_fixed / t_fast_fixed, 1),
        "fast_fixed_frames_per_s": round(n_frames / t_fast_fixed, 1),
        "hours_for_1e5_frames": round(1e5 * t_fast_fixed / n_frames / 3600, 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--max-iters", type=int, default=30)
    ap.add_argument("--qber", type=float, default=0.03)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path("results/bench_decoder"))
    args = ap.parse_args()

    sizes = [
        ("n=4096", 128, 42, 32),
        ("n=8192", 256, 84, 32),
        ("n=16384", 256, 84, 64),
        ("n=65536", 512, 168, 128),
    ]

    rows = []
    for label, n_b, m_b, z in sizes:
        t0 = time.perf_counter()
        code = qc.make_qc_code(n_b, m_b, z, 3, seed=args.seed)
        build_s = time.perf_counter() - t0
        row = bench(code, args.qber, args.frames, args.max_iters, args.seed)
        row["label"] = label
        row["code_build_s"] = round(build_s, 1)
        rows.append(row)
        print(f"{label:9s} build {build_s:5.1f}s | "
              f"reference fixed {row['ref_fixed_s']:7.2f}s  "
              f"fast fixed {row['fast_fixed_s']:6.2f}s  "
              f"speedup {row['speedup_fixed']:5.1f}x  "
              f"({row['fast_fixed_frames_per_s']:.1f} frames/s, "
              f"{row['hours_for_1e5_frames']:.2f} h per 1e5 frames)")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "bench.json").write_text(json.dumps({
        "commit": git_commit(), "date": date.today().isoformat(),
        "frames": args.frames, "max_iters": args.max_iters, "qber": args.qber,
        "rows": rows, "command": " ".join(sys.argv),
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out / 'bench.json'}")


if __name__ == "__main__":
    main()

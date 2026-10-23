"""Experiment E3: the two run-time knobs against throughput, latency and energy.

The decoder's hardware is fixed now — [stage 8](../docs/stages/08-split-arithmetic.md)
meets 125 MHz at 10,149 cycles per iteration. What is left adjustable at run time
is what the PS chooses per frame: **which mask** (how much shortening) and **what
I_max**. Both trade accuracy for speed, and neither costs a gate.

This sweep measures both against the bit-true model and converts the result
through the implemented decoder's cycle model, so the throughput and energy
columns describe the hardware that exists rather than an idealisation.

    uv run python scripts/sweep_e3.py --frames 40

Part 1 (rate sweep) answers REQ-PERF-04: at a given QBER, how much shortening
buys how much throughput, and what it costs in reconciliation efficiency.
Part 2 (I_max sweep) answers REQ-FUN-04 and REQ-PERF-05: how low I_max can go
before frames start failing, and what that does to worst-case latency.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import code as qc  # noqa: E402
from model import info, sweeps  # noqa: E402

# ---------------------------------------------------------------------------
# The implemented decoder, as measured. results/stage8_deep_pipeline/README.md
# ---------------------------------------------------------------------------
CYCLES_PER_ITER = 10_149     # measured in simulation, both mask sets agree
CYCLES_FIXED = 1_181         # the loader pass (1,026) plus the record clear (155)
F_CLK = 125e6                # Hz, WNS +0.081 ns at this period
P_DYNAMIC = 0.917            # W, still the vectorless estimate (stage 9 pending)
E_CYCLE = P_DYNAMIC / F_CLK  # J per clock, ~7.34 nJ


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def derive(row: dict) -> dict:
    """Add the hardware columns to a model measurement."""
    iters = row["avg_iters_ok"]
    if not np.isfinite(iters):
        row.update(cycles=float("nan"), frame_time_ms=float("nan"),
                   throughput_mbps=0.0, energy_nj_per_bit=float("nan"),
                   secret_fraction=0.0, secret_mbps=0.0)
        return row
    cycles = CYCLES_FIXED + iters * CYCLES_PER_ITER
    t = cycles / F_CLK
    row["cycles"] = cycles
    row["frame_time_ms"] = t * 1e3
    row["throughput_mbps"] = row["n_key"] / t / 1e6
    row["energy_nj_per_bit"] = cycles * E_CYCLE / row["n_key"] * 1e9
    # What a QKD system actually gets: the throughput times the fraction of
    # each key bit that survives leakage and privacy amplification. A cheaper
    # mask decodes faster but leaks more, so this has an optimum that raw
    # throughput does not. Asymptotic BB84, no finite-key correction.
    row["secret_fraction"] = max(0.0, info.secret_fraction(row["qber"], row["efficiency"]))
    row["secret_mbps"] = row["throughput_mbps"] * row["secret_fraction"]
    return row


def shortened(n_b: int, count: int) -> list[int]:
    if count <= 0:
        return []
    step = n_b / count
    return sorted({int((i + 0.5) * step) for i in range(count)})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--code", type=Path, default=Path("codes/v3_mother_1_r700.npz"))
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", type=Path, default=Path("results/e3_throughput_tradeoff"))
    args = ap.parse_args()

    code = qc.load_code(args.code)
    args.out.mkdir(parents=True, exist_ok=True)
    cfg = dict(backend="fixed", accelerate=True)

    # ---- part 1: how much shortening, at each QBER ------------------------
    qbers = [0.03, 0.04, 0.05, 0.06]
    shorten_counts = [0, 32, 64, 96, 128, 160, 192]

    points = []
    for q in qbers:
        for s in shorten_counts:
            mask = qc.make_mask(code, mask_id=s,
                                shortened_cols=shortened(code.n_b, s))
            points.append(sweeps.Point(mask=mask, qber=q, frames=args.frames,
                                       seed=args.seed, label=f"q{q:.2f}_s{s}",
                                       kwargs=dict(max_iters=32, **cfg)))

    print(f"part 1: {len(points)} points x {args.frames} frames")
    rate_rows = [derive(r) for r in
                 sweeps.run_points(points, workers=args.workers,
                                   on_result=lambda r: print(
                                       f"  {r['label']:>12}  rate={r['rate']:.3f} "
                                       f"fer={r['fer']:.3f} iters={r['avg_iters_ok']:.1f}"))]
    rate_rows.sort(key=lambda r: (r["qber"], r["s"]))

    # ---- part 2: how low I_max can go -------------------------------------
    # At the 5% operating point the project has been quoting: 125 shortened
    # columns, the mask the stage-5 vectors use.
    imax_mask = qc.make_mask(code, mask_id=125, shortened_cols=shortened(code.n_b, 125))
    imax_values = [8, 12, 16, 20, 24, 28, 32]
    points = [sweeps.Point(mask=imax_mask, qber=0.05, frames=args.frames,
                           seed=args.seed, label=f"imax{i}",
                           kwargs=dict(max_iters=i, **cfg))
              for i in imax_values]

    print(f"part 2: {len(points)} points")
    imax_rows = []
    for r in sweeps.run_points(points, workers=args.workers,
                               on_result=lambda r: print(
                                   f"  {r['label']:>8}  fer={r['fer']:.3f} "
                                   f"iters={r['avg_iters_ok']:.1f}")):
        # run_points returns results as they finish, not in submission order,
        # so the I_max has to come from the row's own label.
        r = derive(r)
        r["i_max"] = int(r["label"][4:])
        r["worst_case_ms"] = (CYCLES_FIXED + r["i_max"] * CYCLES_PER_ITER) / F_CLK * 1e3
        imax_rows.append(r)
    imax_rows.sort(key=lambda r: r["i_max"])

    # ---- write ------------------------------------------------------------
    for name, rows in (("rate_sweep.csv", rate_rows), ("imax_sweep.csv", imax_rows)):
        with (args.out / name).open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    (args.out / "meta.json").write_text(json.dumps({
        "generated": date.today().isoformat(), "commit": git_commit(),
        "code": str(args.code), "frames_per_point": args.frames, "seed": args.seed,
        "hardware_model": {
            "source": "results/stage8_deep_pipeline",
            "cycles_per_iteration": CYCLES_PER_ITER,
            "cycles_fixed_per_frame": CYCLES_FIXED,
            "f_clk_hz": F_CLK,
            "dynamic_power_w": P_DYNAMIC,
            "power_is_vectorless": True,
        },
        "command": " ".join(sys.argv),
    }, indent=2), encoding="utf-8")

    # ---- the headline, printed -------------------------------------------
    for q in qbers:
        print(f"\nQ={q:.0%} (REQ-PERF-04 asks for >= 50 Mbit/s):")
        print(f"  {'cols':>5} {'rate':>6} {'f':>6} {'FER':>6} {'iters':>6} "
              f"{'Mbit/s':>8} {'secret':>7} {'nJ/bit':>7}")
        best = None
        for r in rate_rows:
            if abs(r["qber"] - q) > 1e-9:
                continue
            print(f"  {r['s'] // code.z:>5} {r['rate']:>6.3f} "
                  f"{r['efficiency']:>6.3f} {r['fer']:>6.2f} {r['avg_iters_ok']:>6.1f} "
                  f"{r['throughput_mbps']:>8.1f} {r['secret_mbps']:>7.1f} "
                  f"{r['energy_nj_per_bit']:>7.1f}")
            if r["fer"] == 0.0 and (best is None or r["secret_mbps"] > best["secret_mbps"]):
                best = r
        if best:
            print(f"  -> most secret key: {best['s'] // code.z} shortened columns, "
                  f"rate {best['rate']:.3f}, f {best['efficiency']:.3f}, "
                  f"{best['secret_mbps']:.1f} Mbit/s secret")

    print("\nI_max at Q=5%, 125 shortened columns:")
    for r in imax_rows:
        print(f"  I_max={r['i_max']:>3}  FER={r['fer']:.3f}  "
              f"worst case {r['worst_case_ms']:.2f} ms  "
              f"{r['throughput_mbps']:.1f} Mbit/s")

    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()

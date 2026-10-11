"""Experiment E1 (L1): frame error rate and efficiency against QBER.

Runs the floating-point reference pipeline over a QBER grid for one or more
rate masks and writes a CSV plus a plot into ``results/``.

    uv run python scripts/sweep_e1.py --frames 40 --nb 256 --z 64

Every output carries a header with the git commit, the parameters and the RNG
seed, per REQ-REP-01.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import code as qc  # noqa: E402
from model import info, pipeline  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def build_masks(mother: qc.QCCode, puncture_counts: list[int]) -> list[qc.RateMask]:
    masks = []
    for i, p_cols in enumerate(puncture_counts):
        cols = qc.spread_columns(mother.n_b, p_cols)
        masks.append(qc.make_mask(mother, mask_id=i, punctured_cols=cols))
    return masks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nb", type=int, default=256, help="base-matrix columns")
    ap.add_argument("--mb", type=int, default=None, help="base-matrix rows (default nb/3)")
    ap.add_argument("--z", type=int, default=64, help="lifting size")
    ap.add_argument("--col-weight", type=int, default=3)
    ap.add_argument("--frames", type=int, default=40, help="frames per point")
    ap.add_argument("--max-iters", type=int, default=50)
    ap.add_argument("--alpha", type=float, default=0.75)
    ap.add_argument("--qber", type=float, nargs="+",
                    default=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
    ap.add_argument("--puncture", type=int, nargs="+", default=[0],
                    help="number of punctured base columns, one mask per value")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path("results/e1_l1"))
    args = ap.parse_args()

    m_b = args.mb if args.mb is not None else max(2, args.nb // 3)
    mother = qc.make_qc_code(args.nb, m_b, args.z, args.col_weight, seed=args.seed)
    masks = build_masks(mother, args.puncture)

    print(f"code: n={mother.n} m={mother.m} R0={mother.rate0:.3f} "
          f"edges={mother.n_edges_base} (Z={mother.z}, base {mother.m_b}x{mother.n_b})")

    rows = []
    t0 = time.time()
    for mask in masks:
        for q in args.qber:
            t = time.time()
            stats = pipeline.measure(
                mask, q, args.frames, seed=args.seed + mask.mask_id * 1000,
                max_iters=args.max_iters, alpha=args.alpha,
            )
            stats["seconds"] = round(time.time() - t, 2)
            stats["shannon_rate"] = info.required_rate(q, 1.0)
            rows.append(stats)
            print(f"  mask {mask.mask_id} R={mask.rate:.3f}  Q={q:5.3f}  "
                  f"FER={stats['fer']:.3f}  f={stats['efficiency']:.3f}  "
                  f"iters={stats['avg_iters_ok']:.1f}  ({stats['seconds']}s)")

    args.out.mkdir(parents=True, exist_ok=True)
    header = {
        "experiment": "E1 (L1 float model)",
        "commit": git_commit(),
        "date": date.today().isoformat(),
        "code": {"n": mother.n, "m": mother.m, "z": mother.z, "n_b": mother.n_b,
                 "m_b": mother.m_b, "rate0": round(mother.rate0, 4),
                 "col_weight": args.col_weight},
        "decoder": {"algorithm": "nms", "alpha": args.alpha,
                    "max_iters": args.max_iters},
        "frames_per_point": args.frames,
        "seed": args.seed,
        "runtime_s": round(time.time() - t0, 1),
        "command": " ".join(sys.argv),
    }
    (args.out / "meta.json").write_text(json.dumps(header, indent=2), encoding="utf-8")

    csv_path = args.out / "e1.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {csv_path} and meta.json")

    try:
        plot(rows, args.out / "e1.png")
        print(f"wrote {args.out / 'e1.png'}")
    except Exception as exc:  # pragma: no cover
        print(f"(plot skipped: {exc})")


def plot(rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    masks = sorted({r["mask_id"] for r in rows})
    for mid in masks:
        sub = [r for r in rows if r["mask_id"] == mid]
        q = [r["qber"] * 100 for r in sub]
        label = f"mask {mid} (R={sub[0]['rate']:.2f})"
        ax1.semilogy(q, [max(r["fer"], 1e-3) for r in sub], "o-", label=label)
        ax2.plot(q, [r["efficiency"] for r in sub], "o-", label=label)

    ax1.set_xlabel("QBER (%)"); ax1.set_ylabel("frame error rate"); ax1.grid(alpha=.3)
    ax2.set_xlabel("QBER (%)"); ax2.set_ylabel("reconciliation efficiency f")
    ax2.axhline(1.0, color="k", lw=1, ls="--", label="Slepian-Wolf limit")
    ax2.grid(alpha=.3); ax2.legend(fontsize=8); ax1.legend(fontsize=8)
    fig.suptitle("E1 (L1 float model): FER and efficiency against QBER")
    fig.savefig(path, dpi=150)


if __name__ == "__main__":
    main()

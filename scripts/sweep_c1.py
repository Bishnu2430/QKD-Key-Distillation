"""Contribution C1: how well does one mother code cover the QBER range?

For each QBER on the grid, the script tries a ladder of target efficiencies
(the most aggressive first), builds the matching puncture/shorten mask and
measures FER. The selected operating point is the **lowest-leakage mask whose
FER meets the target**, which is exactly the choice the PS makes at run time
(spec section 6).

    uv run python scripts/sweep_c1.py --frames 25

Outputs: a CSV of every candidate, a JSON header, a selection table and a plot.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import code as qc  # noqa: E402
from model import info, pipeline  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nb", type=int, default=256)
    ap.add_argument("--mb", type=int, default=84)
    ap.add_argument("--z", type=int, default=32)
    ap.add_argument("--col-weight", type=int, default=3)
    ap.add_argument("--frames", type=int, default=25)
    ap.add_argument("--max-iters", type=int, default=60)
    ap.add_argument("--alpha", type=float, default=0.75)
    ap.add_argument("--qber", type=float, nargs="+",
                    default=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08])
    ap.add_argument("--f-ladder", type=float, nargs="+",
                    default=[1.05, 1.10, 1.20, 1.35, 1.55, 1.80])
    ap.add_argument("--fer-target", type=float, default=0.10,
                    help="maximum acceptable FER at this sample size")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path("results/c1_rate_adaptation"))
    args = ap.parse_args()

    mother = qc.make_qc_code(args.nb, args.mb, args.z, args.col_weight, seed=args.seed)
    print(f"mother code: n={mother.n} m={mother.m} R0={mother.rate0:.3f} "
          f"(base {mother.m_b}x{mother.n_b}, Z={mother.z}, col weight {args.col_weight})")
    print(f"FER target {args.fer_target}, {args.frames} frames per candidate\n")

    rows: list[dict] = []
    selected: list[dict] = []
    t0 = time.time()

    for q in args.qber:
        print(f"QBER {q*100:4.1f}%  (Shannon rate {info.required_rate(q, 1.0):.3f})")
        chosen = None
        for i, f_target in enumerate(args.f_ladder):
            target_rate = info.required_rate(q, f_target)
            if not 0.02 < target_rate < 0.98:
                continue
            mask = qc.mask_for_rate(mother, target_rate, mask_id=i)
            stats = pipeline.measure(mask, q, args.frames,
                                     seed=args.seed + i * 977 + int(q * 10000),
                                     max_iters=args.max_iters, alpha=args.alpha)
            stats.update({"f_target": f_target, "target_rate": target_rate,
                          "p": mask.p, "s": mask.s, "selected": False})
            rows.append(stats)
            flag = "ok " if stats["fer"] <= args.fer_target else "   "
            print(f"   {flag}f_target={f_target:4.2f}  R={mask.rate:.3f} "
                  f"(p={mask.p:5d} s={mask.s:5d})  FER={stats['fer']:5.2f}  "
                  f"f={stats['efficiency']:5.3f}  iters={stats['avg_iters_ok']:5.1f}")
            if chosen is None and stats["fer"] <= args.fer_target:
                chosen = stats
        if chosen is not None:
            chosen["selected"] = True
            selected.append(chosen)
            print(f"   -> selected f = {chosen['efficiency']:.3f} "
                  f"(leak {chosen['leak_bits']} bits over {chosen['n_key']} key bits)\n")
        else:
            print("   -> no candidate met the FER target\n")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "meta.json").write_text(json.dumps({
        "experiment": "C1 rate adaptation (L1 float model)",
        "commit": git_commit(),
        "date": date.today().isoformat(),
        "code": {"n": mother.n, "m": mother.m, "z": mother.z, "n_b": mother.n_b,
                 "m_b": mother.m_b, "rate0": round(mother.rate0, 4),
                 "col_weight": args.col_weight},
        "decoder": {"algorithm": "nms", "alpha": args.alpha, "max_iters": args.max_iters},
        "frames_per_point": args.frames,
        "fer_target": args.fer_target,
        "f_ladder": args.f_ladder,
        "seed": args.seed,
        "runtime_s": round(time.time() - t0, 1),
        "command": " ".join(sys.argv),
    }, indent=2), encoding="utf-8")

    with (args.out / "candidates.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("selected operating points")
    print(f"{'QBER':>6} {'R':>7} {'p':>7} {'s':>7} {'f':>7} {'FER':>6} {'iters':>7}")
    for s in selected:
        print(f"{s['qber']*100:5.1f}% {s['rate']:7.3f} {s['p']:7d} {s['s']:7d} "
              f"{s['efficiency']:7.3f} {s['fer']:6.2f} {s['avg_iters_ok']:7.1f}")
    print(f"\nwrote {args.out}/candidates.csv and meta.json  "
          f"({time.time() - t0:.0f}s total)")

    try:
        plot(rows, selected, args.out / "c1.png")
        print(f"wrote {args.out / 'c1.png'}")
    except Exception as exc:  # pragma: no cover
        print(f"(plot skipped: {exc})")


def plot(rows: list[dict], selected: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)

    ax1.scatter([r["qber"] * 100 for r in rows], [r["efficiency"] for r in rows],
                s=18, c=["#2a78d6" if r["fer"] <= 0.1 else "#d9d9d9" for r in rows],
                label="candidates (grey = FER too high)")
    if selected:
        ax1.plot([s["qber"] * 100 for s in selected],
                 [s["efficiency"] for s in selected], "o-", color="#eb6834",
                 label="selected operating point")
    ax1.axhline(1.0, color="k", lw=1, ls="--", label="Slepian-Wolf limit")
    ax1.set_xlabel("QBER (%)"); ax1.set_ylabel("efficiency f"); ax1.grid(alpha=.3)
    ax1.legend(fontsize=8)

    ax2.scatter([r["qber"] * 100 for r in rows], [r["rate"] for r in rows],
                s=18, c=["#2a78d6" if r["fer"] <= 0.1 else "#d9d9d9" for r in rows])
    qs = sorted({r["qber"] for r in rows})
    ax2.plot([q * 100 for q in qs], [info.required_rate(q, 1.0) for q in qs],
             "k--", lw=1, label="Shannon rate 1-h(Q)")
    if rows:
        ax2.axhline(rows[0]["rate"] if False else 0, alpha=0)  # keep axis stable
    ax2.set_xlabel("QBER (%)"); ax2.set_ylabel("effective code rate R")
    ax2.grid(alpha=.3); ax2.legend(fontsize=8)

    fig.suptitle("C1: one mother code with puncture/shorten masks")
    fig.savefig(path, dpi=150)


if __name__ == "__main__":
    main()

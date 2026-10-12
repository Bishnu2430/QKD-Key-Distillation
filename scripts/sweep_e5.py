"""Experiment E5: secret key rate against fibre distance.

Connects the hardware numbers this project measures — reconciliation
efficiency f, frame error rate, and (for the finite-key curve) block size — to
the secret key rate a link would actually deliver.

    uv run python scripts/sweep_e5.py

Two families of curves:

* **Asymptotic** (solid, quotable): decoy-state GLLP rate at the optimal
  intensity for each distance, for several values of f.
* **Finite-key** (provisional): the same link with a finite block, using the
  decoy estimators of arXiv:2405.16578v3. The epsilon bookkeeping is a
  placeholder, so these curves are labelled provisional everywhere they appear.
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

from model import keyrate  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-km", type=float, default=200.0)
    ap.add_argument("--step-km", type=float, default=5.0)
    ap.add_argument("--f", type=float, nargs="+", default=[1.0, 1.15, 1.4, 1.6],
                    help="reconciliation efficiencies to compare")
    ap.add_argument("--fer", type=float, default=0.01)
    ap.add_argument("--pulses", type=float, nargs="+", default=[1e10, 1e12],
                    help="block sizes in pulses for the finite-key curves")
    ap.add_argument("--rep-rate", type=float, default=1e9)
    ap.add_argument("--out", type=Path, default=Path("results/e5_key_rate"))
    args = ap.parse_args()

    channel = keyrate.Channel(rep_rate_hz=args.rep_rate)
    distances = np.arange(0.0, args.max_km + 1e-9, args.step_km)

    rows: list[dict] = []
    print(f"{'km':>6} " + " ".join(f"{'f=' + str(f):>12}" for f in args.f))
    for d in distances:
        line = f"{d:6.0f} "
        for f in args.f:
            mu, best = keyrate.optimal_mu(channel, float(d), f_ec=f, fer=args.fer)
            rows.append({"kind": "asymptotic", "distance_km": float(d), "f_ec": f,
                         "fer": args.fer, "mu": mu, "qber": best["qber"],
                         "gain": best["gain"], "secret_bps": best["secret_bps"],
                         "pulses": "", "provisional": False})
            line += f"{best['secret_bps']:12.3g} "
        if d % 25 == 0:
            print(line)

    # finite-key curves, one per block size, at the best f we expect to achieve
    f_target = min(args.f, key=lambda f: abs(f - 1.15))
    intensities = {0.5: 0.7, 0.1: 0.3}
    print(f"\nprovisional finite-key curves (f = {f_target}, 1-decoy {intensities})")
    for pulses in args.pulses:
        for d in distances:
            det, err, total = keyrate.expected_counts(channel, float(d), intensities,
                                                      pulses, basis_prob=0.5)
            if total <= 0:
                continue
            mu_main = max(intensities)
            leak = f_target * total * keyrate.h(channel.qber(mu_main, float(d))) + 64.0
            res = keyrate.finite_key_length(det, err, intensities, total, total, leak)
            seconds = pulses / channel.rep_rate_hz
            rows.append({"kind": "finite", "distance_km": float(d), "f_ec": f_target,
                         "fer": args.fer, "mu": mu_main,
                         "qber": channel.qber(mu_main, float(d)), "gain": total / pulses,
                         "secret_bps": res.length * (1.0 - args.fer) / seconds,
                         "pulses": pulses, "provisional": True})

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "e5.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "meta.json").write_text(json.dumps({
        "experiment": "E5 secret key rate vs distance",
        "commit": git_commit(), "date": date.today().isoformat(),
        "channel": {"attenuation_db_km": channel.attenuation_db_km,
                    "detector_efficiency": channel.detector_efficiency,
                    "dark_count_rate": channel.dark_count_rate,
                    "misalignment": channel.misalignment,
                    "rep_rate_hz": channel.rep_rate_hz,
                    "sift_factor": channel.sift_factor},
        "parameters_are_illustrative": True,
        "finite_key_provisional": True,
        "command": " ".join(sys.argv),
    }, indent=2), encoding="utf-8")

    try:
        plot(rows, args.out / "e5.png")
        print(f"wrote {args.out}/e5.csv, meta.json and e5.png")
    except Exception as exc:  # pragma: no cover
        print(f"wrote {args.out}/e5.csv and meta.json (plot skipped: {exc})")


def plot(rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.5, 5), constrained_layout=True)
    colours = ["#2a78d6", "#eb6834", "#1baf7a", "#8a5300"]

    for i, f in enumerate(sorted({r["f_ec"] for r in rows if r["kind"] == "asymptotic"})):
        sub = [r for r in rows if r["kind"] == "asymptotic" and r["f_ec"] == f
               and r["secret_bps"] > 0]
        ax.semilogy([r["distance_km"] for r in sub], [r["secret_bps"] for r in sub],
                    "-", color=colours[i % len(colours)], label=f"asymptotic, f = {f}")

    for i, pulses in enumerate(sorted({r["pulses"] for r in rows if r["kind"] == "finite"})):
        sub = [r for r in rows if r["kind"] == "finite" and r["pulses"] == pulses
               and r["secret_bps"] > 0]
        if sub:
            ax.semilogy([r["distance_km"] for r in sub], [r["secret_bps"] for r in sub],
                        "--", color=colours[i % len(colours)], alpha=0.8,
                        label=f"finite block {pulses:.0e} pulses (provisional)")

    ax.set_xlabel("fibre distance (km)")
    ax.set_ylabel("secret key rate (bit/s)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    ax.set_title("E5: secret key rate against distance\n"
                 "illustrative channel parameters; dashed curves provisional",
                 fontsize=10)
    fig.savefig(path, dpi=150)


if __name__ == "__main__":
    main()

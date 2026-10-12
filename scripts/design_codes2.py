"""M3, second pass: threshold-driven code design (contribution C1).

The first pass (``scripts/design_codes.py``, results/m3_code_design) built
masks to hit a target efficiency f = 1.15 and every operating point failed:
asking for f = 1.15 at QBER Q fixes the rate at R = 1 - 1.15 h(Q), and for
these ensembles that rate's decoding threshold is *below* Q. Efficiency is an
outcome, not an input.

This pass inverts the loop:

1. Compute the density-evolution threshold as a function of rate for the best
   degree profile.
2. For each QBER, take the **highest rate whose threshold still exceeds Q with
   a finite-length margin**. That rate is what the code can actually decode.
3. The achievable efficiency follows: f = (1 - R) / h(Q).
4. Pick mother rates that cover the required range within the 10% puncture
   budget from results/c1_rate_adaptation, build them with PEG, check the rank
   of every punctured column set, and validate by simulation.

    uv run python scripts/design_codes2.py --margin 1.25 --validate-frames 40
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import code as qc  # noqa: E402
from model import de, info, peg, rank, sweeps  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def shannon_limit(rate: float) -> float:
    lo, hi = 1e-6, 0.5
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if info.h(mid) < 1.0 - rate:
            lo = mid
        else:
            hi = mid
    return lo


PROFILE = {3: 0.75, 6: 0.125, 8: 0.125}  # best profile from the first pass


def _threshold_at(args: tuple[float, dict, float, int]) -> dict:
    rate, profile, alpha, iterations = args
    lam = de.node_to_edge(profile)
    rho = de.check_degrees_for_rate(lam, rate)
    th = de.threshold(lam, rho, alpha=alpha, iterations=iterations)
    return {"rate": rate, "threshold": th, "shannon": shannon_limit(rate),
            "f_at_threshold": (1.0 - rate) / info.h(th) if th > 0 else float("inf")}


def threshold_curve(rates: list[float], profile: dict, alpha: float,
                    iterations: int, workers: int) -> list[dict]:
    jobs = [(r, profile, alpha, iterations) for r in rates]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return sorted(pool.map(_threshold_at, jobs), key=lambda r: r["rate"])


def usable_rate(curve: list[dict], qber: float, margin: float) -> dict | None:
    """Highest rate whose threshold clears ``qber * margin``."""
    ok = [c for c in curve if c["threshold"] >= qber * margin]
    return max(ok, key=lambda c: c["rate"]) if ok else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nb", type=int, default=512)
    ap.add_argument("--z", type=int, default=128)
    ap.add_argument("--alpha", type=float, default=0.75)
    ap.add_argument("--de-iters", type=int, default=150)
    ap.add_argument("--margin", type=float, default=1.25,
                    help="threshold must exceed QBER by this factor (finite-length margin)")
    ap.add_argument("--qber", type=float, nargs="+",
                    default=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10])
    ap.add_argument("--validate-frames", type=int, default=40)
    ap.add_argument("--max-iters", type=int, default=100)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path("results/m3_code_design_v2"))
    ap.add_argument("--codes", type=Path, default=Path("codes"))
    args = ap.parse_args()

    workers = args.workers or sweeps.default_workers()
    t0 = time.time()

    # --- 1. threshold against rate -----------------------------------------
    rates = [round(r, 3) for r in np.arange(0.40, 0.93, 0.025)]
    print(f"computing the threshold curve for profile {PROFILE} "
          f"({len(rates)} rates, {workers} workers)")
    curve = threshold_curve(rates, PROFILE, args.alpha, args.de_iters, workers)
    print(f"{'rate':>6} {'threshold':>10} {'Shannon':>9} {'f at threshold':>15}")
    for c in curve:
        print(f"{c['rate']:6.3f} {c['threshold']*100:9.3f}% {c['shannon']*100:8.2f}% "
              f"{c['f_at_threshold']:15.3f}")

    # --- 2. usable rate per QBER -------------------------------------------
    print(f"\nusable operating points (margin x{args.margin})")
    print(f"{'QBER':>6} {'rate':>7} {'threshold':>10} {'f achievable':>13}")
    plan = []
    for q in args.qber:
        pick = usable_rate(curve, q, args.margin)
        if pick is None:
            print(f"{q*100:5.1f}%   no rate on the grid clears the margin")
            continue
        f_ach = (1.0 - pick["rate"]) / info.h(q)
        plan.append({"qber": q, "rate": pick["rate"],
                     "threshold": pick["threshold"], "f": f_ach})
        print(f"{q*100:5.1f}% {pick['rate']:7.3f} {pick['threshold']*100:9.3f}% "
              f"{f_ach:13.3f}")

    if not plan:
        print("nothing to build")
        return

    # --- 3. mother rates ----------------------------------------------------
    hi_rate = max(p["rate"] for p in plan)
    lo_rate = min(p["rate"] for p in plan)
    # stay inside the 10% puncture budget: a mother code can reach at most
    # R0 / (1 - 0.10) by puncturing, and any lower rate by shortening
    mother_high = round(hi_rate * 0.90, 3)
    mother_low = round(lo_rate, 3)
    print(f"\nmother codes: high R0 = {mother_high} (reaches {hi_rate} by puncturing), "
          f"low R0 = {mother_low}")

    report: dict = {"commit": git_commit(), "date": date.today().isoformat(),
                    "command": " ".join(sys.argv), "profile": PROFILE,
                    "margin": args.margin,
                    "threshold_curve": curve, "plan": plan, "codes": {}}

    designs = []
    for name, r0 in (("high", mother_high), ("low", mother_low)):
        m_b = int(round(args.nb * (1.0 - r0)))
        degrees = peg.degrees_from_profile(args.nb, PROFILE)
        code = peg.build_peg_code(args.nb, m_b, args.z, degrees, seed=args.seed)
        path = args.codes / f"v2_mother_{name}.npz"
        args.codes.mkdir(parents=True, exist_ok=True)
        qc.save_code(path, code, profile=json.dumps(PROFILE), target_rate=r0)
        print(f"  {name}: base {m_b}x{args.nb}, Z={args.z}, n={code.n}, "
              f"R0={code.rate0:.4f}, edges={code.n_edges_base}")
        designs.append((name, code, r0, path))

    # --- 4. masks, with the rank condition checked -------------------------
    print(f"\n{'code':>5} {'QBER':>6} {'R target':>9} {'R mask':>8} {'p':>7} {'s':>7} "
          f"{'leak':>8} {'rank':>6} {'f':>7}")
    assignments = []
    for entry in plan:
        q, target = entry["qber"], entry["rate"]
        # the code whose mother rate is closest below/above the target
        name, code, r0, _ = min(designs, key=lambda d: abs(d[2] - target))
        mask = qc.mask_for_rate(code, target, mask_id=len(assignments))
        leak, rank_ok = rank.mask_leakage(code, mask)
        f_real = leak / (mask.n_key * info.h(q))
        assignments.append({"code": name, "qber": q, "target_rate": target,
                            "rate": mask.rate, "p": mask.p, "s": mask.s,
                            "leak": leak, "rank_ok": rank_ok, "f": f_real,
                            "mask": mask})
        print(f"{name:>5} {q*100:5.1f}% {target:9.3f} {mask.rate:8.3f} {mask.p:7d} "
              f"{mask.s:7d} {leak:8d} {str(rank_ok):>6} {f_real:7.3f}")

    report["codes"] = {name: {"rate0": code.rate0, "base": [code.m_b, code.n_b],
                              "z": code.z, "n": code.n,
                              "edges_base": code.n_edges_base, "path": str(path)}
                       for name, code, r0, path in designs}
    report["masks"] = [{k: v for k, v in a.items() if k != "mask"} for a in assignments]

    # --- 5. validation ------------------------------------------------------
    if args.validate_frames > 0:
        print(f"\nvalidating ({args.validate_frames} frames per point, {workers} workers, "
              f"max {args.max_iters} iterations)")
        points = [sweeps.Point(a["mask"], a["qber"], args.validate_frames,
                               seed=args.seed + int(a["qber"] * 10000), label=a["code"],
                               kwargs={"max_iters": args.max_iters, "backend": "fixed"})
                  for a in assignments]
        measured = sweeps.run_points(points, workers=workers)
        print(f"{'code':>5} {'QBER':>6} {'FER':>6} {'f':>7} {'iters':>7} {'undetected':>11}")
        for st in measured:
            print(f"{st['label']:>5} {st['qber']*100:5.1f}% {st['fer']:6.2f} "
                  f"{st['efficiency']:7.3f} {st['avg_iters_ok']:7.1f} {st['undetected']:11d}")
        report["validation"] = [{k: v for k, v in st.items() if k != "label"}
                                | {"code": st["label"]} for st in measured]

    args.out.mkdir(parents=True, exist_ok=True)
    report["runtime_s"] = round(time.time() - t0, 1)
    (args.out / "design.json").write_text(json.dumps(report, indent=2, default=float),
                                          encoding="utf-8")
    print(f"\nwrote {args.out / 'design.json'} ({report['runtime_s']:.0f}s)")


if __name__ == "__main__":
    main()

"""M3: design the mother codes and their rate masks (contribution C1).

Pipeline:

1. Search degree distributions with density evolution, at each target rate,
   under the decoder we actually use (normalized min-sum, alpha = 0.75).
2. Build the base matrices with PEG and 4-cycle-free lifting at n = 65,536.
3. Derive the rate-mask table, **checking the GF(2) rank** of every punctured
   column set so the leakage accounting is honest (spec section 3.5).
4. Validate by simulation and compare the measured waterfall with the density
   evolution threshold.

    uv run python scripts/design_codes.py --validate-frames 40

Design constraints come from results/c1_rate_adaptation:
  * puncture at most ~10% of positions,
  * keep the puncturable (heavy-degree) subset larger than the punctured set,
  * use two mother codes rather than one.
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

HEAVY_DEGREE = 6
MAX_AVG_DEGREE = 4.0
MIN_HEAVY_FRACTION = 0.15  # larger than the ~10% puncture budget


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def candidate_profiles() -> list[dict[int, float]]:
    """Node-perspective degree profiles worth evaluating."""
    out: list[dict[int, float]] = [{3: 1.0}, {4: 1.0}]
    for heavy in (0.15, 0.20, 0.25, 0.30):
        for light in (2, 3):
            out.append({HEAVY_DEGREE: heavy, light: 1.0 - heavy})
        out.append({HEAVY_DEGREE: heavy, 3: 1.0 - heavy - 0.15, 2: 0.15})
    for heavy in (0.15, 0.25):
        out.append({8: heavy, 3: 1.0 - heavy})
        out.append({8: heavy * 0.5, HEAVY_DEGREE: heavy * 0.5, 3: 1.0 - heavy})
    return out


def profile_ok(profile: dict[int, float]) -> bool:
    avg = sum(d * f for d, f in profile.items())
    heavy = sum(f for d, f in profile.items() if d >= HEAVY_DEGREE)
    return avg <= MAX_AVG_DEGREE and (heavy == 0.0 or heavy >= MIN_HEAVY_FRACTION)


def _evaluate(args: tuple[dict[int, float], float, float, int]) -> dict:
    profile, rate, alpha, iterations = args
    lam = de.node_to_edge(profile)
    rho = de.check_degrees_for_rate(lam, rate)
    th = de.threshold(lam, rho, alpha=alpha, iterations=iterations)
    return {"profile": profile, "rate": rate, "rho": rho,
            "avg_degree": sum(d * f for d, f in profile.items()),
            "threshold": th, "shannon": shannon_limit(rate)}


def shannon_limit(rate: float) -> float:
    lo, hi = 1e-6, 0.5
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if info.h(mid) < 1.0 - rate:
            lo = mid
        else:
            hi = mid
    return lo


def search_profiles(rate: float, alpha: float, workers: int, iterations: int) -> list[dict]:
    jobs = [(p, rate, alpha, iterations) for p in candidate_profiles() if profile_ok(p)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_evaluate, jobs))
    return sorted(results, key=lambda r: -r["threshold"])


def build_mask_table(code: qc.QCCode, qbers: list[float], f_target: float,
                     puncture_cap: float) -> list[dict]:
    """One mask per QBER, with the rank condition checked."""
    table = []
    for i, q in enumerate(qbers):
        target_rate = info.required_rate(q, f_target)
        mask = qc.mask_for_rate(code, target_rate, mask_id=i)
        if mask.p / code.n > puncture_cap:  # respect the C1 budget
            cap_cols = int(puncture_cap * code.n_b)
            mask = qc.make_mask(code, i, punctured_cols=qc.spread_columns(code.n_b, cap_cols))
        leak, rank_ok = rank.mask_leakage(code, mask)
        table.append({"qber": q, "mask": mask, "rate": mask.rate, "p": mask.p,
                      "s": mask.s, "leak": leak, "rank_ok": rank_ok,
                      "f_predicted": leak / (mask.n_key * info.h(q))})
    return table


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nb", type=int, default=512)
    ap.add_argument("--z", type=int, default=128)
    ap.add_argument("--alpha", type=float, default=0.75)
    ap.add_argument("--de-iters", type=int, default=150)
    ap.add_argument("--high-rate", type=float, default=0.87)
    ap.add_argument("--low-rate", type=float, default=0.62)
    ap.add_argument("--f-target", type=float, default=1.15)
    ap.add_argument("--validate-frames", type=int, default=40)
    ap.add_argument("--max-iters", type=int, default=60)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path("results/m3_code_design"))
    ap.add_argument("--codes", type=Path, default=Path("codes"))
    args = ap.parse_args()

    workers = args.workers or sweeps.default_workers()
    t0 = time.time()
    report: dict = {"commit": git_commit(), "date": date.today().isoformat(),
                    "command": " ".join(sys.argv), "codes": {}}

    designs = []
    for name, target_rate, qbers, cap in (
        ("high", args.high_rate, [0.01, 0.02, 0.03], 0.10),
        ("low", args.low_rate, [0.04, 0.05, 0.06, 0.08, 0.10], 0.10),
    ):
        print(f"\n=== {name}-rate mother code, target R0 = {target_rate:.3f} ===")
        ranked = search_profiles(target_rate, args.alpha, workers, args.de_iters)
        print(f"{'profile':38s} {'avg dv':>7} {'threshold':>10} {'Shannon':>9}")
        for r in ranked[:6]:
            prof = ", ".join(f"{d}:{f:.2f}" for d, f in sorted(r["profile"].items()))
            print(f"{prof:38s} {r['avg_degree']:7.2f} {r['threshold']*100:9.3f}% "
                  f"{r['shannon']*100:8.2f}%")
        best = ranked[0]

        m_b = int(round(args.nb * (1.0 - target_rate)))
        degrees = peg.degrees_from_profile(args.nb, best["profile"])
        print(f"building PEG code: base {m_b}x{args.nb}, Z={args.z}, "
              f"n={args.nb * args.z}, degrees {np.bincount(degrees)[1:].tolist()}")
        t = time.time()
        code = peg.build_peg_code(args.nb, m_b, args.z, degrees, seed=args.seed)
        print(f"  built in {time.time() - t:.1f}s, R0={code.rate0:.4f}, "
              f"edges={code.n_edges_base}")

        args.codes.mkdir(parents=True, exist_ok=True)
        path = args.codes / f"mother_{name}.npz"
        qc.save_code(path, code, profile=json.dumps(best["profile"]),
                     threshold=best["threshold"], target_rate=target_rate)

        table = build_mask_table(code, qbers, args.f_target, cap)
        print(f"  {'QBER':>6} {'R':>7} {'p':>7} {'s':>7} {'leak':>8} {'rank':>6} {'f_pred':>7}")
        for row in table:
            print(f"  {row['qber']*100:5.1f}% {row['rate']:7.3f} {row['p']:7d} "
                  f"{row['s']:7d} {row['leak']:8d} {str(row['rank_ok']):>6} "
                  f"{row['f_predicted']:7.3f}")

        designs.append((name, code, best, table))
        report["codes"][name] = {
            "target_rate": target_rate, "rate0": code.rate0,
            "base": [m_b, args.nb], "z": args.z, "n": code.n,
            "profile": {str(k): v for k, v in best["profile"].items()},
            "avg_degree": best["avg_degree"],
            "de_threshold": best["threshold"], "shannon": best["shannon"],
            "edges_base": code.n_edges_base, "path": str(path),
            "ranked": [{"profile": {str(k): v for k, v in r["profile"].items()},
                        "threshold": r["threshold"]} for r in ranked],
            "masks": [{k: (v if k != "mask" else None) for k, v in row.items()}
                      for row in table],
        }

    # --- validation by simulation ------------------------------------------
    if args.validate_frames > 0:
        print(f"\n=== validating by simulation ({args.validate_frames} frames per point, "
              f"{workers} workers) ===")
        points = []
        for name, code, best, table in designs:
            for row in table:
                points.append(sweeps.Point(
                    row["mask"], row["qber"], args.validate_frames,
                    seed=args.seed + int(row["qber"] * 10000), label=name,
                    kwargs={"max_iters": args.max_iters, "backend": "fixed"}))
        measured = sweeps.run_points(points, workers=workers)
        print(f"  {'code':>5} {'QBER':>6} {'FER':>6} {'f':>7} {'iters':>7} {'undetected':>11}")
        for st in measured:
            print(f"  {st['label']:>5} {st['qber']*100:5.1f}% {st['fer']:6.2f} "
                  f"{st['efficiency']:7.3f} {st['avg_iters_ok']:7.1f} {st['undetected']:11d}")
        report["validation"] = [
            {k: v for k, v in st.items() if k != "label"} | {"code": st["label"]}
            for st in measured
        ]

    args.out.mkdir(parents=True, exist_ok=True)
    report["runtime_s"] = round(time.time() - t0, 1)
    (args.out / "design.json").write_text(json.dumps(report, indent=2, default=float),
                                          encoding="utf-8")
    print(f"\nwrote {args.out / 'design.json'} and {args.codes}/mother_*.npz "
          f"({report['runtime_s']:.0f}s)")


if __name__ == "__main__":
    main()

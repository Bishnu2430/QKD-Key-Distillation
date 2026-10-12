"""M3, third pass: mother rates at the top of their range (contribution C1).

Lessons carried in from the two earlier passes:

* **v1** (results/m3_code_design) built masks for a target efficiency. Every
  point failed: efficiency is an outcome of the rate, not an input to it.
* **v2** (results/m3_code_design_v2) drove the rate from the density-evolution
  threshold, which fixed the high-rate code (FER 0 at Q = 1-4%), but placed the
  low-rate mother code at the *bottom* of its range, so reaching the rest of
  the range meant puncturing 24-30% of positions - far past the ~10% budget
  measured in results/c1_rate_adaptation. Those points failed.

The rule this pass applies:

    a mother code sits at the TOP of the rate range it serves;
    lower rates are reached by SHORTENING, which measurement shows is safe;
    PUNCTURING is used only within the 10% budget, to nudge above R0.

    uv run python scripts/design_codes3.py --curve-from results/m3_code_design_v2/design.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import code as qc  # noqa: E402
from model import info, peg, rank, sweeps  # noqa: E402

PROFILE = {3: 0.75, 6: 0.125, 8: 0.125}
PUNCTURE_BUDGET = 0.10  # fraction of n, from results/c1_rate_adaptation


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def plan_from_curve(curve: list[dict], qbers: list[float], margin: float) -> list[dict]:
    plan = []
    for q in qbers:
        ok = [c for c in curve if c["threshold"] >= q * margin]
        if not ok:
            continue
        pick = max(ok, key=lambda c: c["rate"])
        plan.append({"qber": q, "rate": pick["rate"], "threshold": pick["threshold"],
                     "f_achievable": (1.0 - pick["rate"]) / info.h(q)})
    return plan


def choose_mother_rates(plan: list[dict], max_sigma: float) -> list[float]:
    """Greedy cover: each mother code sits at the top of what it can shorten to.

    Shortening from R0 to R costs sigma = (R0 - R) / (1 - R); a code covers
    every rate down to the point where sigma would exceed ``max_sigma``.
    """
    rates = sorted({p["rate"] for p in plan}, reverse=True)
    mothers: list[float] = []
    for rate in rates:
        if mothers:
            r0 = mothers[-1]
            sigma = (r0 - rate) / (1.0 - rate) if rate < r0 else 0.0
            if sigma <= max_sigma:
                continue  # the current mother code already reaches this rate
        mothers.append(rate)
    return mothers


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--curve-from", type=Path,
                    default=Path("results/m3_code_design_v2/design.json"))
    ap.add_argument("--nb", type=int, default=512)
    ap.add_argument("--z", type=int, default=128)
    ap.add_argument("--margin", type=float, default=1.25)
    ap.add_argument("--max-sigma", type=float, default=0.40,
                    help="largest shortening fraction a mother code may use")
    ap.add_argument("--qber", type=float, nargs="+",
                    default=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08])
    ap.add_argument("--validate-frames", type=int, default=40)
    ap.add_argument("--max-iters", type=int, default=100)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path("results/m3_code_design_v3"))
    ap.add_argument("--codes", type=Path, default=Path("codes"))
    args = ap.parse_args()

    workers = args.workers or sweeps.default_workers()
    t0 = time.time()

    curve = json.loads(args.curve_from.read_text(encoding="utf-8"))["threshold_curve"]
    plan = plan_from_curve(curve, args.qber, args.margin)
    print(f"{'QBER':>6} {'rate':>7} {'threshold':>10} {'f achievable':>13}")
    for p in plan:
        print(f"{p['qber']*100:5.1f}% {p['rate']:7.3f} {p['threshold']*100:9.3f}% "
              f"{p['f_achievable']:13.3f}")

    mothers = choose_mother_rates(plan, args.max_sigma)
    print(f"\nmother rates (top of range, shorten downward, sigma <= {args.max_sigma}): "
          f"{mothers}")

    args.codes.mkdir(parents=True, exist_ok=True)
    codes = []
    for i, r0 in enumerate(mothers):
        m_b = int(round(args.nb * (1.0 - r0)))
        degrees = peg.degrees_from_profile(args.nb, PROFILE)
        code = peg.build_peg_code(args.nb, m_b, args.z, degrees, seed=args.seed + i)
        path = args.codes / f"v3_mother_{i}_r{int(r0*1000):03d}.npz"
        qc.save_code(path, code, profile=json.dumps(PROFILE), target_rate=r0)
        codes.append((r0, code, path))
        print(f"  code {i}: R0={code.rate0:.4f}, base {m_b}x{args.nb}, Z={args.z}, "
              f"n={code.n}, edges={code.n_edges_base}")

    print(f"\n{'QBER':>6} {'code':>5} {'R target':>9} {'R mask':>8} {'p':>7} {'s':>7} "
          f"{'leak':>8} {'rank':>6} {'f':>7}")
    assignments = []
    for p in plan:
        target = p["rate"]
        # the cheapest code that reaches this rate: the lowest R0 at or above it
        usable = [c for c in codes if c[0] >= target] or [max(codes, key=lambda c: c[0])]
        r0, code, _ = min(usable, key=lambda c: c[0])
        mask = qc.mask_for_rate(code, target, mask_id=len(assignments))
        if mask.p / code.n > PUNCTURE_BUDGET:
            cap = int(PUNCTURE_BUDGET * code.n_b)
            mask = qc.make_mask(code, len(assignments),
                                punctured_cols=qc.spread_columns(code.n_b, cap))
        leak, rank_ok = rank.mask_leakage(code, mask)
        f_real = leak / (mask.n_key * info.h(p["qber"]))
        assignments.append({"qber": p["qber"], "code_rate0": r0, "target_rate": target,
                            "rate": mask.rate, "p": mask.p, "s": mask.s, "leak": leak,
                            "rank_ok": rank_ok, "f": f_real, "n_key": mask.n_key,
                            "mask": mask})
        print(f"{p['qber']*100:5.1f}% {r0:5.3f} {target:9.3f} {mask.rate:8.3f} "
              f"{mask.p:7d} {mask.s:7d} {leak:8d} {str(rank_ok):>6} {f_real:7.3f}")

    report = {"commit": git_commit(), "date": date.today().isoformat(),
              "command": " ".join(sys.argv), "profile": PROFILE,
              "margin": args.margin, "max_sigma": args.max_sigma,
              "puncture_budget": PUNCTURE_BUDGET, "plan": plan,
              "mother_rates": mothers,
              "codes": [{"rate0": c.rate0, "base": [c.m_b, c.n_b], "z": c.z,
                         "n": c.n, "edges_base": c.n_edges_base, "path": str(path)}
                        for r0, c, path in codes],
              "masks": [{k: v for k, v in a.items() if k != "mask"} for a in assignments]}

    if args.validate_frames > 0:
        print(f"\nvalidating ({args.validate_frames} frames per point, {workers} workers)")
        points = [sweeps.Point(a["mask"], a["qber"], args.validate_frames,
                               seed=args.seed + int(a["qber"] * 10000),
                               label=f"r{a['code_rate0']:.3f}",
                               kwargs={"max_iters": args.max_iters, "backend": "fixed"})
                  for a in assignments]
        measured = sweeps.run_points(points, workers=workers)
        print(f"{'QBER':>6} {'code':>7} {'FER':>6} {'f':>7} {'iters':>7} "
              f"{'n_key':>7} {'undetected':>11}")
        for st in measured:
            print(f"{st['qber']*100:5.1f}% {st['label']:>7} {st['fer']:6.2f} "
                  f"{st['efficiency']:7.3f} {st['avg_iters_ok']:7.1f} "
                  f"{st['n_key']:7d} {st['undetected']:11d}")
        report["validation"] = [{k: v for k, v in st.items() if k != "label"}
                                | {"code": st["label"]} for st in measured]

    args.out.mkdir(parents=True, exist_ok=True)
    report["runtime_s"] = round(time.time() - t0, 1)
    (args.out / "design.json").write_text(json.dumps(report, indent=2, default=float),
                                          encoding="utf-8")
    print(f"\nwrote {args.out / 'design.json'} ({report['runtime_s']:.0f}s)")


if __name__ == "__main__":
    main()

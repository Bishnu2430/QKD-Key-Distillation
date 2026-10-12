"""Experiment E2: quantisation study (L1 float against L2 bit-true).

Sweeps the fixed-point parameters of docs/05-algorithm-spec.md section 2.1
against the floating-point reference, so the word widths in the RTL are chosen
from measurements instead of folklore.

    uv run python scripts/sweep_e2.py --frames 30

Reports, per configuration and QBER: FER, average iterations and the delta
against the float model.
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
from model import fixed, pipeline  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def configurations() -> list[tuple[str, fixed.FixedConfig]]:
    """The configurations worth measuring, named for the report."""
    d = fixed.DEFAULT
    return [
        ("default 5/6/8, d=0.25, a=0.75", d),
        ("msg 4 bits", fixed.FixedConfig(w_msg=4, w_app=d.w_app, w_ch=d.w_ch)),
        ("msg 5 bits", fixed.FixedConfig(w_msg=5, w_app=d.w_app, w_ch=d.w_ch)),
        ("msg 7 bits", fixed.FixedConfig(w_msg=7, w_app=d.w_app, w_ch=d.w_ch)),
        ("app 6 bits", fixed.FixedConfig(w_app=6)),
        ("app 7 bits", fixed.FixedConfig(w_app=7)),
        ("app 10 bits", fixed.FixedConfig(w_app=10)),
        ("delta 0.5", fixed.FixedConfig(delta=0.5)),
        ("delta 0.125", fixed.FixedConfig(delta=0.125)),
        ("alpha 0.5", fixed.FixedConfig(alpha_shifts=(1,))),
        ("alpha 0.875", fixed.FixedConfig(alpha_shifts=(1, 2, 3))),
        ("alpha 1.0 (plain min-sum)", fixed.FixedConfig(alpha_shifts=(0,))),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nb", type=int, default=128)
    ap.add_argument("--mb", type=int, default=42)
    ap.add_argument("--z", type=int, default=32)
    ap.add_argument("--col-weight", type=int, default=3)
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--max-iters", type=int, default=60)
    ap.add_argument("--qber", type=float, nargs="+", default=[0.02, 0.03, 0.04])
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path("results/e2_quantisation"))
    args = ap.parse_args()

    code = qc.make_qc_code(args.nb, args.mb, args.z, args.col_weight, seed=args.seed)
    mask = qc.make_mask(code, 0)
    print(f"code: n={code.n} R0={code.rate0:.3f}; {args.frames} frames per point\n")

    rows: list[dict] = []
    t0 = time.time()

    # floating-point reference first
    float_ref: dict[float, dict] = {}
    for q in args.qber:
        st = pipeline.measure(mask, q, args.frames, seed=args.seed,
                              max_iters=args.max_iters, backend="float")
        float_ref[q] = st
        rows.append({"config": "float reference", "qber": q, "fer": st["fer"],
                     "avg_iters": st["avg_iters_ok"], "delta_fer": 0.0,
                     "undetected": st["undetected"], "w_ch": "", "w_msg": "",
                     "w_app": "", "delta_q": "", "alpha": ""})
        print(f"float  Q={q*100:4.1f}%  FER={st['fer']:5.2f}  iters={st['avg_iters_ok']:5.1f}")
    print()

    for name, cfg in configurations():
        for q in args.qber:
            st = pipeline.measure(mask, q, args.frames, seed=args.seed,
                                  max_iters=args.max_iters, backend="fixed", cfg=cfg)
            rows.append({"config": name, "qber": q, "fer": st["fer"],
                         "avg_iters": st["avg_iters_ok"],
                         "delta_fer": st["fer"] - float_ref[q]["fer"],
                         "undetected": st["undetected"],
                         "w_ch": cfg.w_ch, "w_msg": cfg.w_msg, "w_app": cfg.w_app,
                         "delta_q": cfg.delta, "alpha": cfg.alpha})
            print(f"{name:28s} Q={q*100:4.1f}%  FER={st['fer']:5.2f} "
                  f"({st['fer'] - float_ref[q]['fer']:+.2f} vs float)  "
                  f"iters={st['avg_iters_ok']:5.1f}")
        print()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "meta.json").write_text(json.dumps({
        "experiment": "E2 quantisation (L1 float vs L2 bit-true)",
        "commit": git_commit(), "date": date.today().isoformat(),
        "code": {"n": code.n, "rate0": round(code.rate0, 4), "z": code.z,
                 "n_b": code.n_b, "m_b": code.m_b, "col_weight": args.col_weight},
        "frames_per_point": args.frames, "max_iters": args.max_iters,
        "seed": args.seed, "runtime_s": round(time.time() - t0, 1),
        "command": " ".join(sys.argv),
    }, indent=2), encoding="utf-8")

    with (args.out / "e2.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {args.out}/e2.csv and meta.json ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()

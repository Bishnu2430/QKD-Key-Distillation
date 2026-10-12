"""Export bit-exact test vectors for the RTL testbench (spec section 7).

The L2 model is the oracle the RTL is checked against, so the handover between
Python and SystemVerilog is a set of files, not a conversation. Every vector
here is what the hardware must reproduce **exactly**: same decoded bits, same
iteration count, same success flag.

    uv run python scripts/export_test_vectors.py --code codes/mother_low.npz \
        --qber 0.05 --frames 50 --out tv/low_q05

Files written (all hex, 16 digits per 64-bit word, LSB-first per spec section 2):

    meta.json        code shape, mask, fixed-point configuration, seeds
    base_matrix.txt  the base matrix, one row per line, -1 for a zero block
    frames/NNN_y.hex        Bob's received key bits
    frames/NNN_syndrome.hex Alice's syndrome
    frames/NNN_xhat.hex     expected decoded key bits
    expected.csv            per frame: ok flag, iterations, channel amplitude
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

from model import bits, code as qc, fast, fixed, frame  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def write_hex(path: Path, vector: np.ndarray) -> None:
    path.write_text("\n".join(bits.to_hex_lines(vector)) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--code", type=Path, required=True, help="codes/*.npz")
    ap.add_argument("--qber", type=float, default=0.05)
    ap.add_argument("--qber-est", type=float, default=None)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--max-iters", type=int, default=60)
    ap.add_argument("--puncture-cols", type=int, default=0)
    ap.add_argument("--shorten-cols", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    code = qc.load_code(args.code)
    mask = qc.make_mask(
        code, 0,
        punctured_cols=qc.spread_columns(code.n_b, args.puncture_cols),
        shortened_cols=qc.spread_columns(code.n_b, args.shorten_cols, offset=code.n_b // 2),
    )
    cfg = fixed.DEFAULT
    qber_est = args.qber if args.qber_est is None else args.qber_est
    amplitude = fixed.channel_amplitude(qber_est, cfg)
    key_pos, _, _ = mask.positions()

    out = args.out
    (out / "frames").mkdir(parents=True, exist_ok=True)

    # the base matrix, so the testbench can build the same code
    rows = [" ".join(str(int(v)) for v in code.base[r]) for r in range(code.m_b)]
    (out / "base_matrix.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

    rng = np.random.default_rng(args.seed)
    records = []
    for i in range(args.frames):
        f = frame.make_frame(mask, args.qber, rng, qber_est=qber_est)
        llr = fixed.initial_llr(mask, f.y_key, qber_est, cfg)
        res = fast.decode_fixed(code, llr, f.syndrome, max_iters=args.max_iters, cfg=cfg)
        x_hat = res.key_bits(key_pos)

        tag = f"{i:03d}"
        write_hex(out / "frames" / f"{tag}_y.hex", f.y_key)
        write_hex(out / "frames" / f"{tag}_syndrome.hex", f.syndrome)
        write_hex(out / "frames" / f"{tag}_xhat.hex", x_hat)
        records.append({
            "frame": i, "ok": int(res.ok), "iterations": res.iterations,
            "amplitude": amplitude, "errors_in": f.n_errors,
            "matches_alice": int(np.array_equal(x_hat, f.x_key)),
            "n_key_bits": int(x_hat.size), "syndrome_bits": int(f.syndrome.size),
        })

    with (out / "expected.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)

    (out / "meta.json").write_text(json.dumps({
        "generated": date.today().isoformat(),
        "commit": git_commit(),
        "source_code_file": str(args.code),
        "code": {"n": code.n, "m": code.m, "z": code.z,
                 "n_b": code.n_b, "m_b": code.m_b,
                 "rate0": round(code.rate0, 4), "edges_base": code.n_edges_base},
        "mask": {"punctured_cols": args.puncture_cols, "shorten_cols": args.shorten_cols,
                 "p": mask.p, "s": mask.s, "n_key": mask.n_key,
                 "rate": round(mask.rate, 4)},
        "fixed_point": {"w_ch": cfg.w_ch, "w_msg": cfg.w_msg, "w_app": cfg.w_app,
                        "delta": cfg.delta, "alpha": cfg.alpha,
                        "alpha_shifts": list(cfg.alpha_shifts)},
        "decoder": {"max_iters": args.max_iters, "channel_amplitude": amplitude},
        "channel": {"qber": args.qber, "qber_est": qber_est},
        "frames": args.frames, "seed": args.seed,
        "bit_order": "LSB-first within each 64-bit word (spec section 2)",
        "command": " ".join(sys.argv),
    }, indent=2), encoding="utf-8")

    ok = sum(r["ok"] for r in records)
    exact = sum(r["matches_alice"] for r in records)
    print(f"wrote {args.frames} frames to {out}")
    print(f"  code n={code.n} m={code.m} R={mask.rate:.3f} n_key={mask.n_key}")
    print(f"  channel amplitude A={amplitude}, max {args.max_iters} iterations")
    print(f"  decoded {ok}/{args.frames}, bit-exact against Alice {exact}/{args.frames}")


if __name__ == "__main__":
    main()

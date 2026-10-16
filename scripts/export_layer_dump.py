"""Export per-layer APP snapshots for RTL bring-up stage 2.

Stage 2 builds one layer of the decoder datapath. Checking it against a whole
decoded frame would only say "wrong somewhere"; checking it against the APP
array after layer 0 says "wrong here". This script produces those snapshots
from the bit-true L2 model.

    uv run python scripts/export_layer_dump.py --code codes/v3_mother_1_r700.npz \
        --qber 0.03 --layers 2 --out tv/r700_q03_layers

Files written (hex, 16 digits per 64-bit word, LSB-first, per spec section 2):

    app_init.hex          APP array before any layer runs
    app_after_l000.hex    after layer 0
    app_after_l001.hex    after layer 1 (and so on)
    syndrome.hex          the frame's syndrome, needed for the sign twist
    meta.json             code shape, fixed-point configuration, amplitude, seed

APP serialisation: one signed 8-bit value per variable, in variable order, eight
values per 64-bit word. Variable ``v = c*Z + j`` therefore sits in word
``v / 8`` at byte ``v % 8``, so base column ``c`` occupies the 16 consecutive
words starting at ``16*c``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import bits, code as qc, fixed, frame  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def write_app_hex(path: Path, app: np.ndarray) -> None:
    """Pack signed 8-bit APP values, eight per 64-bit word, LSB-first."""
    as_bytes = np.asarray(app, dtype=np.int32).astype(np.int8).view(np.uint8)
    words = as_bytes.reshape(-1, 8)
    lines = []
    for w in words:
        value = 0
        for byte_index, byte in enumerate(w):
            value |= int(byte) << (8 * byte_index)
        lines.append(f"{value:016x}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--code", type=Path, required=True)
    ap.add_argument("--qber", type=float, default=0.03)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    code = qc.load_code(args.code)
    mask = qc.make_mask(code, 0)  # unmasked: stage 2 does not do rate masks yet
    cfg = fixed.DEFAULT
    amplitude = fixed.channel_amplitude(args.qber, cfg)

    rng = np.random.default_rng(args.seed)
    f = frame.make_frame(mask, args.qber, rng, qber_est=args.qber)
    llr = fixed.initial_llr(mask, f.y_key, args.qber, cfg)

    snapshots = fixed.decode_layer_trace(code, llr, f.syndrome, args.layers, cfg)

    args.out.mkdir(parents=True, exist_ok=True)
    write_app_hex(args.out / "app_init.hex", snapshots[0])
    for i, snap in enumerate(snapshots[1:]):
        write_app_hex(args.out / f"app_after_l{i:03d}.hex", snap)
    (args.out / "syndrome.hex").write_text(
        "\n".join(bits.to_hex_lines(f.syndrome)) + "\n", encoding="utf-8")

    changed = [int(np.count_nonzero(snapshots[i + 1] != snapshots[i]))
               for i in range(len(snapshots) - 1)]

    (args.out / "meta.json").write_text(json.dumps({
        "generated": date.today().isoformat(), "commit": git_commit(),
        "source_code_file": str(args.code),
        "code": {"n": code.n, "m": code.m, "z": code.z, "n_b": code.n_b,
                 "m_b": code.m_b, "rate0": round(code.rate0, 4)},
        "fixed_point": {"w_ch": cfg.w_ch, "w_msg": cfg.w_msg, "w_app": cfg.w_app,
                        "delta": cfg.delta, "alpha": cfg.alpha,
                        "alpha_shifts": list(cfg.alpha_shifts),
                        "max_app": cfg.max_app, "max_msg": cfg.max_msg},
        "channel": {"qber": args.qber, "amplitude": amplitude},
        "layers_dumped": args.layers,
        "values_changed_per_layer": changed,
        "app_words_per_file": code.n // 8,
        "words_per_base_column": code.z // 8,
        "seed": args.seed,
        "format": "signed int8 per variable, 8 values per 64-bit word, LSB-first",
        "command": " ".join(sys.argv),
    }, indent=2), encoding="utf-8")

    print(f"wrote {args.layers + 1} snapshots to {args.out}")
    print(f"  code n={code.n} m={code.m} layers={code.m_b}, amplitude A={amplitude}")
    print(f"  APP file: {code.n // 8} lines of 64-bit hex "
          f"({code.z // 8} lines per base column)")
    for i, n_changed in enumerate(changed):
        print(f"  layer {i:3d}: {n_changed} of {code.n} APP values changed")


if __name__ == "__main__":
    main()

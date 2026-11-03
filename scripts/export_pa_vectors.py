"""Export privacy-amplification vectors (spec section 5) for the stage-15 RTL.

Privacy amplification compresses a verified block of N bits to L secret bits
with the same Toeplitz family the verification tag uses:

    k_i = XOR_j  v[i + j] AND x[j],   i = 0..L-1,  j = 0..N-1

so the seed is N + L - 1 bits. The RTL computes this in L/B passes over the
block, B = 256 output bits at a time; the model computes it in one shot, which
is exactly the independence that makes it a useful oracle.

Each case directory gets:

    seed.hex    public seed v,  N + L - 1 bits, zero-padded to a word
    blk.hex     the input block, N bits
    out.hex     the expected output, L bits
    case.json   N, L, the chunk count and the seed

Hex format is the project's throughout (spec section 2): one 64-bit word per
line, 16 digits, LSB-first inside the word.

    uv run python scripts/export_pa_vectors.py --out tv/pa
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import bits, hashing  # noqa: E402

W = 64   # stream width, spec section 2
B = 256  # RTL output chunk, learning guide section 17.1


def write_hex(path: Path, vector: np.ndarray) -> None:
    """Write a bit vector as 64-bit words, zero-padded to a whole word."""
    pad = (-vector.size) % W
    if pad:
        vector = np.concatenate([vector, np.zeros(pad, dtype=np.uint8)])
    path.write_text("\n".join(bits.to_hex_lines(vector)) + "\n", encoding="utf-8")


def one_case(out_dir: Path, n_bits: int, l_bits: int, seed: int) -> dict:
    if n_bits % W:
        raise SystemExit(f"N={n_bits} must be a multiple of W={W}")
    if l_bits % B:
        raise SystemExit(f"L={l_bits} must be a multiple of B={B}")
    if l_bits > n_bits:
        raise SystemExit(f"L={l_bits} must not exceed N={n_bits} (REQ-FUN-07)")

    rng = np.random.default_rng(seed)
    v = hashing.random_seed(n_bits, l_bits, rng)
    x = rng.integers(0, 2, size=n_bits, dtype=np.uint8)
    k = hashing.privacy_amplify(x, v, l_bits)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_hex(out_dir / "seed.hex", v)
    write_hex(out_dir / "blk.hex", x)
    write_hex(out_dir / "out.hex", k)

    meta = {
        "generated": date.today().isoformat(),
        "n_bits": n_bits,
        "l_bits": l_bits,
        "n_words": n_bits // W,
        "seed_bits": hashing.seed_length(n_bits, l_bits),
        "seed_words": -(-hashing.seed_length(n_bits, l_bits) // W),
        "l_words": l_bits // W,
        "n_chunks": l_bits // B,
        "chunk_bits": B,
        "rng_seed": seed,
        "out_weight": int(k.sum()),
        "bit_order": "LSB-first within each 64-bit word (spec section 2)",
    }
    (out_dir / "case.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


# N, L, rng seed. The small cases run in a second and catch every indexing
# bug; the last one is the REQ-PERF-08 operating point, N = 2^17 with L = N/2.
CASES = [
    ("n1024_l256",    1_024,     256,  101),   # 1 chunk  - the degenerate pass
    ("n1024_l512",    1_024,     512,  102),   # 2 chunks - proves the seed offset
    ("n8192_l4096",   8_192,   4_096,  103),   # 16 chunks
    ("n65536_l32768", 65_536, 32_768,  104),   # a decoded frame's worth
    ("n131072_l65536", 131_072, 65_536, 105),  # REQ-PERF-08: N = 2^17, L = N/2
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="tv/pa", help="output directory")
    ap.add_argument("--case", action="append", help="only these case names")
    args = ap.parse_args()

    root = Path(args.out)
    for name, n_bits, l_bits, seed in CASES:
        if args.case and name not in args.case:
            continue
        meta = one_case(root / name, n_bits, l_bits, seed)
        print(
            f"{name:<16} N={meta['n_bits']:>7}  L={meta['l_bits']:>6}  "
            f"{meta['n_chunks']:>4} chunks  seed={meta['seed_bits']:>7} bits  "
            f"weight={meta['out_weight']}/{meta['l_bits']}"
        )
    print(f"written to {root}")


if __name__ == "__main__":
    main()

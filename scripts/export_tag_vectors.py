"""Export error-verification tag vectors (spec section 4) for the stage-14 RTL.

The tag is computed over the *decoded key* of an existing test-vector set, so
the RTL is checked against real decoder output rather than synthetic bits. Run
this on a directory that export_test_vectors.py already produced.

Files written, alongside the ones already there:

    frames/NNN_seed.hex   public seed v, n_key + t - 1 bits
    tags.csv              per frame: n_key_bits, the expected tag, and the tag
                          of the same key with one bit flipped

Hex format is the project's throughout (spec section 2): one 64-bit word per
line, 16 digits, LSB-first inside the word.

The flipped-key tag is there so the testbench can prove the tag *detects* a
wrong key, not merely that it reproduces a number. A verification tag that
always matches would pass a weaker test perfectly.

    uv run python scripts/export_tag_vectors.py --tv tv/r700_q05_m16s125
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import bits, hashing  # noqa: E402


def read_hex(path: Path, n_bits: int) -> np.ndarray:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").split("\n") if ln.strip()]
    return bits.from_hex_lines(lines, n_bits)


def write_hex(path: Path, vector: np.ndarray) -> None:
    path.write_text("\n".join(bits.to_hex_lines(vector)) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tv", type=Path, required=True,
                    help="a directory from export_test_vectors.py")
    ap.add_argument("--tag-bits", type=int, default=hashing.TAG_BITS,
                    help=f"tag length t (default {hashing.TAG_BITS}, spec section 4)")
    ap.add_argument("--seed", type=int, default=20241028,
                    help="RNG seed for the public seeds (reproducibility only)")
    args = ap.parse_args()

    tv = args.tv
    if not (tv / "expected.csv").exists():
        raise SystemExit(f"no expected.csv under {tv} - run export_test_vectors.py first")

    with (tv / "expected.csv").open(newline="", encoding="utf-8") as fh:
        frames = list(csv.DictReader(fh))

    t = args.tag_bits
    rng = np.random.default_rng(args.seed)
    records = []

    for row in frames:
        i = int(row["frame"])
        n_key = int(row["n_key_bits"])
        name = f"{i:03d}"

        # xhat.hex holds the whole block; the key is its first n_key bits.
        x = read_hex(tv / "frames" / f"{name}_xhat.hex", n_key)

        seed = hashing.random_seed(n_key, t, rng)
        tag = hashing.verification_tag(x, seed, t)

        # the same key with bit 0 flipped - a frame that decoded to the wrong
        # answer. Its tag must differ, or verification is not doing anything.
        x_bad = x.copy()
        x_bad[0] ^= 1
        tag_bad = hashing.verification_tag(x_bad, seed, t)

        write_hex(tv / "frames" / f"{name}_seed.hex", seed)
        records.append({
            "frame": i,
            "n_key_bits": n_key,
            "seed_bits": int(seed.size),
            "tag": bits.to_hex_lines(tag)[0],
            "tag_bit0_flipped": bits.to_hex_lines(tag_bad)[0],
        })

        if np.array_equal(tag, tag_bad):
            raise SystemExit(f"frame {i}: flipping a key bit left the tag unchanged")

    with (tv / "tags.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)

    meta_path = tv / "tag_meta.json"
    meta_path.write_text(json.dumps({
        "generated": date.today().isoformat(),
        "tag_bits": t,
        "seed_rng": args.seed,
        "frames": len(records),
        "note": "seed is n_key + tag_bits - 1 bits, spec section 4",
    }, indent=2) + "\n", encoding="utf-8")

    n_key = records[0]["n_key_bits"]
    print(f"  {len(records)} frames, t={t}")
    print(f"  n_key={n_key} bits = {n_key // 64} words")
    print(f"  seed ={records[0]['seed_bits']} bits = "
          f"{-(-records[0]['seed_bits'] // 64)} words")
    print(f"  -> {tv / 'tags.csv'}")


if __name__ == "__main__":
    main()

#!/bin/bash
# Generate the eleven 1,000-frame vector sets for the REQ-VER-01 campaign.
#
# The grid is chosen so that one campaign closes three requirements instead of
# one:
#
#   REQ-VER-01  >= 1,000 random frames per (QBER, rate) point, zero mismatches
#   REQ-FUN-02  Q in [1%, 10%] - the endpoints are points here, not interpolated
#   REQ-FUN-03  >= 10 rate points from puncture/shorten masks
#
# Each QBER is paired with a mother code near its own operating range. A mask
# far from its band either decodes every frame in five iterations or fails all
# of them, and neither exercises the decoder.
#
# The seed is the same 7 used for the committed 4- and 20-frame sets under
# tv/, so the leading frames of each set here are byte-identical to the vectors
# xsim has already run in Vivado. That overlap is what lets the bulk campaign
# run under Verilator; see results/ver01_bit_exactness/README.md.
#
# Output is ~450 MB and gitignored. Run time is about 25 minutes.
set -e
cd "$(dirname "$0")/.."
UV=${UV:-uv}
N=${N:-1000}

run() {   # name  code  qber  shorten_cols
  echo "=== $1  (Q=$3, s=$4) ==="
  $UV run python scripts/export_test_vectors.py \
      --code "$2" --qber "$3" --frames "$N" \
      --puncture-cols 16 --shorten-cols "$4" --max-iters 32 \
      --out "tv/ver01/$1" 2>&1 | tail -3
}

#   name               code                        QBER  shorten
run r850_q01_m16s0    codes/v3_mother_0_r850.npz  0.01    0
run r850_q01_m16s32   codes/v3_mother_0_r850.npz  0.01   32
run r850_q02_m16s200  codes/v3_mother_0_r850.npz  0.02  200
run r700_q03_m16s0    codes/v3_mother_1_r700.npz  0.03    0
run r700_q03_m16s32   codes/v3_mother_1_r700.npz  0.03   32
run r700_q04_m16s80   codes/v3_mother_1_r700.npz  0.04   80
run r700_q05_m16s125  codes/v3_mother_1_r700.npz  0.05  125
run r700_q06_m16s180  codes/v3_mother_1_r700.npz  0.06  180
run r400_q08_m16s0    codes/v3_mother_2_r400.npz  0.08    0
run r400_q08_m16s32   codes/v3_mother_2_r400.npz  0.08   32
run r400_q10_m16s64   codes/v3_mother_2_r400.npz  0.10   64

echo "=== generation complete ==="
du -sh tv/ver01

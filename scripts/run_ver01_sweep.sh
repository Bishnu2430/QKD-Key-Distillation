#!/bin/bash
# REQ-VER-01 / T-DEC-02: run ldpc_decoder_chunk against 1,000 frames at each of
# eleven (QBER, rate) points and compare ok, the iteration count and every key
# bit against the L2 model.
#
# Needs Verilator 5.x and the vector sets from scripts/gen_ver01_vectors.sh.
# Run time is about 55 minutes with JOBS=4; the longest single point
# (r700_q05_m16s125, the only one with a real frame-error rate) takes 54.
#
# Three things this driver has to get right, each of which cost a failed run:
#
#   * The testbench watchdog in tb/ is #500_000_000 - 500 ms of simulated time (the full run needs 2 s),
#     which is ample for the 20-frame bring-up run that file exists to serve
#     and short of 1,000 frames at every point. It is raised in the per-point
#     copy, not in the repo file.
#
#   * rtl/ldpc_decoder_chunk.sv and tb/tb_ldpc_decoder_chunk.sv BOTH include a
#     code-parameter header, and Verilator compiles them as one unit, so both
#     are rewritten per point. Leaving one behind is not a wrong answer, it is
#     'N_B is already declared' - the stage-12 lesson.
#
#   * The points run concurrently, so the testbench module is renamed per point
#     or the parallel builds collide in the output binary.
set -e
cd "$(dirname "$0")/.."
REPO=$(pwd)
WORK=${WORK:-build/ver01}
JOBS=${JOBS:-4}
FRAMES=${FRAMES:-1000}
mkdir -p "$WORK"

prepare() {
  local NAME=$1 CODE=$2
  cp "$REPO/rtl/ldpc_decoder_chunk.sv"    "$WORK/dut_$NAME.sv"
  cp "$REPO/tb/tb_ldpc_decoder_chunk.sv"  "$WORK/tb_$NAME.sv"
  sed -i "s|v3_mother_[0-9]_r[0-9]*|$CODE|g" "$WORK/dut_$NAME.sv" "$WORK/tb_$NAME.sv"
  sed -i "s|\"D:/QKD-Key-Distillation/tv/[^\"]*\"|\"$REPO/tv/ver01/$NAME/\"|" "$WORK/tb_$NAME.sv"
  sed -i "s|N_FRAMES = [0-9]*|N_FRAMES = $FRAMES|"      "$WORK/tb_$NAME.sv"
  sed -i "s|#500_000_000;|#(64'd40_000_000_000);|"      "$WORK/tb_$NAME.sv"
  sed -i "s|module tb_ldpc_decoder_chunk;|module tb_$NAME;|" "$WORK/tb_$NAME.sv"

  # Guard every rewrite: a sed that silently matched nothing would run the
  # wrong code or time out two hours later with no explanation.
  grep -q "$CODE" "$WORK/dut_$NAME.sv" || { echo "FATAL $NAME: dut not on $CODE"; exit 1; }
  grep -q "$CODE" "$WORK/tb_$NAME.sv"  || { echo "FATAL $NAME: tb not on $CODE";  exit 1; }
  grep -q "tv/ver01/$NAME/"  "$WORK/tb_$NAME.sv" || { echo "FATAL $NAME: vector dir not set"; exit 1; }
  grep -q "64'd40_000_000_000" "$WORK/tb_$NAME.sv" || { echo "FATAL $NAME: watchdog not raised"; exit 1; }
  grep -q "module tb_$NAME;"   "$WORK/tb_$NAME.sv" || { echo "FATAL $NAME: module not renamed"; exit 1; }
}

one_point() {
  local NAME=$1 CODE=$2 START
  prepare "$NAME" "$CODE"
  rm -rf "$WORK/obj_$NAME"
  # The vector paths are absolute, so the simulation runs from the repo root.
  verilator --binary --Mdir "$WORK/obj_$NAME" -Wno-fatal \
            --top-module "tb_$NAME" -o sim \
            "$WORK/dut_$NAME.sv" "$WORK/tb_$NAME.sv" \
            > "$WORK/build_$NAME.log" 2>&1 \
    || { echo "BUILD FAILED $NAME - see $WORK/build_$NAME.log"; return 1; }
  START=$(date +%s)
  "./$WORK/obj_$NAME/sim" > "$WORK/res_$NAME.log" 2>&1 || true
  echo "  done $NAME in $(( $(date +%s) - START ))s"
}

POINTS=(
  "r850_q01_m16s0     v3_mother_0_r850"
  "r850_q01_m16s32    v3_mother_0_r850"
  "r850_q02_m16s200   v3_mother_0_r850"
  "r700_q03_m16s0     v3_mother_1_r700"
  "r700_q03_m16s32    v3_mother_1_r700"
  "r700_q04_m16s80    v3_mother_1_r700"
  "r700_q05_m16s125   v3_mother_1_r700"
  "r700_q06_m16s180   v3_mother_1_r700"
  "r400_q08_m16s0     v3_mother_2_r400"
  "r400_q08_m16s32    v3_mother_2_r400"
  "r400_q10_m16s64    v3_mother_2_r400"
)

echo "running ${#POINTS[@]} points, $FRAMES frames each, $JOBS at a time"
rm -f "$WORK"/res_*.log
for p in "${POINTS[@]}"; do
  set -- $p
  if [ ! -d "tv/ver01/$1" ]; then
    echo "  SKIP $1 - no vectors, run scripts/gen_ver01_vectors.sh"; continue
  fi
  while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
  one_point "$1" "$2" &
done
wait

echo
echo "=============================================================="
printf '  %-20s %6s %7s %7s %6s  %s\n' POINT FRAMES DECODED FAILED MISM VERDICT
echo "=============================================================="
TOTAL=0; BAD=0; NOFIN=0
for p in "${POINTS[@]}"; do
  set -- $p
  f="$WORK/res_$1.log"; [ -f "$f" ] || continue
  N=$(grep -c '^frame ' "$f" || true)
  OKC=$(grep -c 'ok=1' "$f" || true)
  M=$(grep -c 'MISMATCH' "$f" || true)
  if   grep -q 'STAGE 11 PASSED' "$f"; then V=PASSED
  elif grep -q 'ERROR: timeout'  "$f"; then V=TIMEOUT; NOFIN=$((NOFIN+1))
  else V=$(grep -oE 'STAGE 11 FAILED.*' "$f" || echo UNKNOWN); fi
  TOTAL=$((TOTAL+N)); BAD=$((BAD+M))
  printf '  %-20s %6d %7d %7d %6d  %s\n' "$1" "$N" "$OKC" "$((N-OKC))" "$M" "$V"
done
echo "=============================================================="
echo "  $TOTAL frames, $BAD mismatches, $NOFIN point(s) timed out"

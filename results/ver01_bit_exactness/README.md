# REQ-VER-01 — the RTL is bit-exact against the L2 model: 11,000 frames, eleven points, zero mismatches

| Field | Value |
|---|---|
| Run by | Claude, Verilator in WSL |
| Date | 28 Oct 2026 |
| Commit | `62cee80` (each vector set records it in its `meta.json`) |
| DUT | `rtl/ldpc_decoder_chunk.sv`, `CN_CHUNKS = 4`, unchanged — no RTL was written for this campaign |
| Testbench | `tb/tb_ldpc_decoder_chunk.sv`, unchanged except frame count, vector path and watchdog |
| Tool | Verilator 5.052, four points at a time — 4 h 53 min of simulation in 55 min of wall clock |
| Vectors | 11 × 1,000 frames, seed 7, `tv/ver01/` (452 MB, gitignored) |
| Closes | REQ-VER-01, T-DEC-02 |

## The result this campaign existed for

| REQ-VER-01 | Target | Measured | |
|---|---|---|---|
| Frames per (QBER, rate) point | ≥ 1,000 | **1,000 at every one of 11 points** | ✅ |
| Mismatches against the L2 model | zero | **0 of 33,000 comparisons** | ✅ |

Before this run the largest RTL-vs-model comparison in the project was **20 frames**, and most stages were signed off on four. REQ-VER-01 has been the gap in the verification ladder since M2: every FER and efficiency number the project publishes comes from the L2 model, and the ladder's argument is that L2 describes the hardware *because L3 proves the RTL equals L2*. That argument now rests on 11,000 frames instead of 20.

## What "bit-exact" means here — three checks per frame

The testbench compares three independent things against `expected.csv` and the expected key words, and counts each as a separate failure:

| Check | Covers | Comparisons |
|---|---|---|
| `ok` — the syndrome-satisfied flag | REQ-FUN-05 | 11,000 |
| `iter_count` — iterations used, i.e. where early termination fired | REQ-FUN-04, REQ-FUN-05 | 11,000 |
| Every key bit, word by word | REQ-FUN-01, REQ-IF-03 | 11,000 frames × 37,888–63,488 bits |

All three agreed on every frame. The iteration check is the sharp one: it fails if the RTL terminates even one iteration early or late, so it pins the whole message-passing schedule and not just the final answer. **603 million key bits** were compared in total.

## The grid

Eleven points, chosen so that one campaign closes three requirements rather than one.

| Point | Mother code | Q | shortened | key bits | rate | decoded | FER | mean iters | max iters | mismatches |
|---|---|---|---|---|---|---|---|---|---|---|
| `r850_q01_m16s0` | r850 | 1% | 0 | 63,488 | 0.877 | 1000/1000 | 0.0% | 10.5 | 27 | **0** |
| `r850_q01_m16s32` | r850 | 1% | 32 | 59,392 | 0.869 | 1000/1000 | 0.0% | 8.1 | 11 | **0** |
| `r850_q02_m16s200` | r850 | 2% | 200 | 37,888 | 0.794 | 997/1000 | 0.3% | 11.6 | 31 | **0** |
| `r700_q03_m16s0` | r700 | 3% | 0 | 63,488 | 0.722 | 1000/1000 | 0.0% | 8.9 | 12 | **0** |
| `r700_q03_m16s32` | r700 | 3% | 32 | 59,392 | 0.703 | 1000/1000 | 0.0% | 7.1 | 9 | **0** |
| `r700_q04_m16s80` | r700 | 4% | 80 | 53,248 | 0.668 | 1000/1000 | 0.0% | 10.9 | 19 | **0** |
| `r700_q05_m16s125` | r700 | 5% | 125 | 47,488 | 0.628 | 906/1000 | 9.4% | 18.9 | 32 | **0** |
| `r700_q06_m16s180` | r700 | 6% | 180 | 40,448 | 0.563 | 995/1000 | 0.5% | 13.0 | 25 | **0** |
| `r400_q08_m16s0` | r400 | 8% | 0 | 63,488 | 0.413 | 1000/1000 | 0.0% | 6.7 | 8 | **0** |
| `r400_q08_m16s32` | r400 | 8% | 32 | 59,392 | 0.373 | 1000/1000 | 0.0% | 5.5 | 6 | **0** |
| `r400_q10_m16s64` | r400 | 10% | 64 | 55,296 | 0.326 | 1000/1000 | 0.0% | 7.0 | 8 | **0** |

Every point carries 16 punctured columns. Mean iterations are over converged frames; failed frames all ran the full 32.

### REQ-FUN-02 — the QBER range, endpoints included

Q = 1% and Q = 10% are points in this grid, not interpolations between measured ones. REQ-FUN-02's interval Q ∈ [1%, 10%] is covered at its edges, which is where a decoder is most likely to misbehave: at 1% the channel barely perturbs anything and early termination fires in 8 iterations, at 10% the code runs at rate 0.326 and the syndrome dominates the frame.

### REQ-FUN-03 — eleven rate points, but still three mother codes

Eleven distinct effective rates, 0.326 → 0.877, a 2.7× span, from one datapath and one matrix ROM per code:

```
0.326  0.373  0.413 | 0.563  0.628  0.668  0.703  0.722 | 0.794  0.869  0.877
|<------ r400 ---->| |<------------- r700 ------------>| |<------ r850 ----->|
```

REQ-FUN-03's measurable — "≥ 10 rate points" — is met. Its mechanism clause, "from **one mother code**", is not, and this campaign confirms why rather than fixing it: no single code supplies ten points. r700 gives five, r850 and r400 three each. That deviation was already recorded as an open item in [docs/03 §9](../../docs/03-requirements.md) after the C1 sweep, which found one code cannot cover 1–10% within the puncture budget. **The requirement should be amended to "≥ 10 rate points from a small fixed set of mother codes", with three as the measured number** — the hardware cost of the extra codes is one matrix ROM each, and all three already meet timing and resource budgets.

## Why Verilator, and what ties it to Vivado

[docs/10 §1](../../docs/10-verification-plan.md) names L3 as "cocotb + Verilator/Icarus, **or** xsim", and [docs/12](../../docs/12-toolflow.md) names Verilator 5.x as the primary simulator. xsim was not an option at this scale: the four-frame stage-11 run took minutes, and 11,000 frames across eleven points would have tied up the machine Vivado needs for days.

The two simulators are tied together by the vectors. The seed is the same 7 used for the committed 4- and 20-frame sets, so the leading frames of four points are **byte-identical** to vectors xsim has already run:

| Point | Committed frames | Hex files identical | `expected.csv` prefix |
|---|---|---|---|
| `r850_q01_m16s32` | 20 | 60/60 | matches |
| `r700_q03_m16s32` | 20 | 60/60 | matches |
| `r400_q08_m16s32` | 20 | 60/60 | matches |
| `r700_q05_m16s125` | 4 | 12/12 | matches |

On those vectors xsim and Verilator return the same `ok` and the same iteration count, frame for frame. Where both simulated the *same* decoder generation — `ldpc_decoder_chunk` at stage 11, on `r850_q01_m16s32` — the cycle counts agree exactly as well: 61,111 and 69,797 for 7 and 8 iterations, in both tools. Where they differ, it is because the archived log is from an earlier generation: the stage-8 and stage-10 logs ran `ldpc_decoder_deep` at 10,149 cycles an iteration, against the chunked decoder's 11,227. **Functional agreement is exact in every case; cycle counts track the DUT, as they should.**

This is evidence, not proof: it is 44 frames of overlap, and it says the two tools agree on this design rather than in general. Full xsim confirmation at scale is not needed — REQ-VER-03 already requires a post-implementation timing simulation in Vivado, and that is the run that checks the netlist with delays.

## The failure path got exercised 102 times

| | |
|---|---|
| Frames that hit I_max = 32 and gave up | **102** (3 + 94 + 5, across three points) |
| Mismatches among them | **0** |

T-DEC-03 ("I_max boundary; failure path", REQ-FUN-04/05) had never been run on more than a handful of frames, because at most operating points the decoder simply succeeds. Three points here fail often enough to cover it, `r700_q05_m16s125` contributing 94 of the failures. In every one the RTL ran all 32 iterations, raised `ok = 0`, reported `iters = 32`, and matched the model — so the give-up path reports itself correctly and does not corrupt the frame on the way out.

What this does **not** cover is REQ-FUN-04's configurability clause, I_max ∈ [1, 63]. Every frame here ran at the default 32. The register is written and read back in the stage-12 AXI tests, but the decoder has not been swept across I_max values in RTL.

## What the campaign measured on the way past

These are properties of the code set and the L2 model, not of the RTL — the RTL's contribution is that it reproduces them exactly. They are reported because 1,000 frames a point is the first sample size in this project large enough to mean anything, and two of them change a number the project has been quoting.

Throughput and latency are derived from the simulated cycle counts at the constrained 125 MHz. They are not measurements on hardware.

| Point | *f* | FER | mean iters | key Mbit/s | worst-case latency |
|---|---|---|---|---|---|
| `r850_q01_m16s0` | 1.522 | 0.0% | 10.5 | 86.8 | 1.88 ms |
| `r850_q01_m16s32` | 1.628 | 0.0% | 8.1 | 105.0 | 0.77 ms |
| `r850_q02_m16s200` | 1.457 | 0.3% | 11.6 | 46.6 | ⚠️ 2.23 ms |
| `r700_q03_m16s0` | 1.431 | 0.0% | 8.9 | 78.9 | 1.08 ms |
| `r700_q03_m16s32` | 1.530 | 0.0% | 7.1 | 92.7 | 0.81 ms |
| `r700_q04_m16s80` | 1.369 | 0.0% | 10.9 | 54.0 | 1.71 ms |
| `r700_q05_m16s125` | **1.299** | ⚠️ **9.4%** | 18.9 | ⚠️ **26.2** | ⚠️ 2.88 ms |
| `r700_q06_m16s180` | 1.334 | 0.5% | 13.0 | 34.2 | ⚠️ 2.88 ms |
| `r400_q08_m16s0` | 1.459 | 0.0% | 6.7 | 71.9 | 1.05 ms |
| `r400_q08_m16s32` | 1.560 | 0.0% | 5.5 | 81.6 | 0.79 ms |
| `r400_q10_m16s64` | 1.436 | 0.0% | 7.0 | 59.7 | 1.05 ms |

**1. The project's reference Q = 5% mask is worse than E3's 40-frame estimate said.** `r700_q05_m16s125` has been the Q = 5% oracle for stages 5, 7, 8, 12 and 14 — always at four frames, so its FER was never visible. At 1,000 frames it is **9.4%**, nine times REQ-PERF-03's 10⁻² ceiling, and its mean iteration count is 18.9 against [E3](../e3_throughput_tradeoff/README.md)'s 15.75. Both effects push throughput down: **26.2 Mbit/s, not the 37 E3 computed**, against REQ-PERF-04's 50 Mbit/s floor. The 94 failures make that a usable estimate — REQ-VER-02 asks for ≥ 100 frame errors per point, so call it 9.4% ± 1%.

This does not break anything that was working. E3 had already found both the cause and the fix: **the 16 punctured columns nearly double the decode time**, and dropping them at Q = 5% in favour of more shortening gives 71.6 Mbit/s and FER 0 on the same gates. What the campaign adds is confirmation, at a sample size that can see it, that the punctured reference mask is not a viable operating point. The masks E3 recommends have not yet been through RTL.

**2. The best efficiency in the grid belongs to the only point that fails.** *f* = 1.299 at `r700_q05_m16s125` is the lowest in the table, and it is the point with a 9.4% FER; every point that decodes 1,000 for 1,000 pays 1.37–1.63. That is the expected shape of the trade, and it is why REQ-PERF-01 (*f* ≤ 1.15) has been open since M3 at a measured 1.29–1.56. This grid widens the top of that range slightly, to **1.30–1.63**.

**3. Worst-case latency exceeds REQ-PERF-05 at three points.** At I_max = 32 a frame that runs to the limit takes 2.23–2.88 ms, over the 2 ms bound. This is not new — stage 11 recorded REQ-PERF-05 as met "at I_max = 21" — but it is now measured rather than extrapolated, and it argues for lowering the default I_max rather than for changing the RTL. Mean latency is 0.57–1.81 ms across the grid.

## Caveats

- **The campaign verifies the decoder core, not the system.** It drives `ldpc_decoder_chunk` through its native interface. The AXI wrapper, the DMA path and the Toeplitz tag are verified separately at stages 12 and 14, on far fewer frames.
- **One code header per point, applied by `sed`.** The decoder and its testbench both carry a code-parameter header and Verilator compiles them in one unit, so the driver rewrites both and then greps to confirm each substitution took. A silent `sed` miss would have run the wrong code rather than failed outright.
- **Verilator is a 2-state simulator.** It does not model X propagation, so a reset bug leaving a register undefined would show up here only if the undefined value happened to differ. xsim's 4-state runs at stages 5–12 cover that, and REQ-VER-03's post-implementation simulation covers it on the netlist.
- The vector sets are 452 MB and gitignored; `scripts/gen_ver01_vectors.sh` regenerates them bit-identically from seed 7.

## Files

| File | Contents |
|---|---|
| `summary.csv` | One row per point: rate, QBER, FER, iterations, cycles, derived throughput, mismatches |
| `sweep_all.log` | Driver output — per-point wall time and the final table |
| `logs/res_<point>.log` | Per-frame `ok`, iterations and cycles for all 1,000 frames, with the model's expected values on the same line. Every number in this README traces to these. |

The per-frame logs are kept in full rather than summarised, because REQ-REP-01 asks that every published number be traceable and these are the only record of the iteration and cycle distributions. They are 712 KB of text and pack to roughly 45 KB.

## Reproduce

```bash
bash scripts/gen_ver01_vectors.sh
```

```bash
JOBS=4 bash scripts/run_ver01_sweep.sh
```

Generation takes about 25 minutes and writes 452 MB to `tv/ver01/`; the sweep takes about 55 minutes with four points at a time. Both scripts derive every path from the repo root and accept `N` / `FRAMES` to change the frame count. The sweep works in `build/ver01/`, leaving each point's generated decoder, testbench and log there.

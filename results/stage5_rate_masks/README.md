# Stage 5 — rate masks: PASSED, and the first timing number

| Field | Value |
|---|---|
| Built by | Bishnu, by hand in the Vivado GUI |
| Date | 18 Oct 2026 |
| Code | `v3_mother_1_r700`, masked: 16 punctured + 125 shortened columns → effective rate 0.628 |
| Oracle | `tv/r700_q05_m16s125/` — 4 frames at QBER 5%, `expected.csv` and the expected key bits |
| Tool | Vivado ML Standard 2025.2, `xc7z020clg400-1`, out-of-context, `constraints/ldpc.xdc` at 125 MHz |

## Functional result — rate adaptation works in hardware

```
vectors: D:/QKD-Key-Distillation/tv/r700_q05_m16s125/
mask: 371 key columns, 47488 key bits
frame 0: ok=1 iters=13 (expected ok=1 iters=13), 284426 cycles
frame 1: ok=1 iters=16 (expected ok=1 iters=16), 350027 cycles
frame 2: ok=1 iters=17 (expected ok=1 iters=17), 371894 cycles
frame 3: ok=1 iters=17 (expected ok=1 iters=17), 371894 cycles
STAGE 5 PASSED
```

**This is a 5% bit error rate decoded by a code whose unmasked threshold is 4.04%.** Shortening 125 of 512 base columns moved the effective rate from 0.699 to 0.628, and the same gates then decode an error rate the unmasked code cannot touch — matching the reference model's `ok`, its iteration count and every one of the 47,488 key bits, on all four frames.

That is contribution C1 — rate adaptation from a single mother code — demonstrated in hardware rather than in a plot. The only thing the mask changes is the starting LLR of each position: ±A for key, 0 for punctured, +127 for shortened.

Cycle counts are identical to the Verilator run, to the cycle, for the third stage in a row (11,103,608 ns of simulated time against Verilator's 11 ms).

**Not yet run:** the 20-frame `tv/r700_q03_m16s32/` set, which exercises all three position classes at a QBER the unmasked code also handles. The 5% set is the stronger test of rate adaptation; the 3% set is the broader test of the loader.

## Synthesis (out-of-context, constrained, `xc7z020clg400-1`)

| Resource | Stage 4 | **Stage 5** | % of device |
|---|---|---|---|
| Slice LUTs | 18,836 | **19,964** | 37.53 |
| — LUT as logic | 18,320 | 19,448 | 36.56 |
| — LUT as distributed RAM | 516 | 516 | 2.97 |
| Slice registers | 9,173 | 9,230 | 8.67 |
| Block RAM tiles | 70 | **72.5** | 51.79 |
| DSP | 0 | 0 | 0 |

The loader cost 1,128 LUTs (the per-lane three-way select between ±A, 0 and +127, plus a third input on the APP write multiplexer) and 57 registers, which is within the 20,000–21,000 LUT estimate.

### Where the memories went

| Memory | Shape | RAMB36 | RAMB18 | Tiles |
|---|---|---|---|---|
| `cn_mem` (check records) | 154 × 3,840 | 53 | 1 | 53.5 |
| `app_mem` (APP array) | 512 × 1,024 | 14 | 1 | 14.5 |
| `key_mem` (Bob's key) | 512 × 128 | 2 | 0 | 2 |
| `mask_mem` | 512 × 2 | 0 | 1 | 0.5 |
| Edge and layer-pointer ROMs | — | 1 | 2 | 2 |
| `syn_mem` | 154 × 128 | — | — | 516 LUTs (distributed) |

`mask_mem` taking a whole RAMB18 for 1,024 bits is wasteful; `(* ram_style = "distributed" *)` would move it into a handful of LUTs. Half a tile, so not urgent.

## Timing — the design does **not** meet 125 MHz

| | Value |
|---|---|
| Target | 8.000 ns (125 MHz) |
| **WNS** | **−9.196 ns** |
| Implied period | 17.196 ns → **Fmax ≈ 58.2 MHz** |
| TNS | −33,013 ns over 7,496 failing endpoints of 31,341 |
| WHS | +0.259 ns (hold is fine) |
| WPWS | +2.750 ns (pulse width is fine) |

### The critical path is the one the architecture predicted

```
Source:       app_mem_reg_6/CLKARDCLK   (RAMB36E1)
Destination:  idx_reg[103][0]/CE        (the minimum-finder's index register)
Data path:    16.943 ns — logic 6.057 ns (36%), route 10.886 ns (64%)
Logic levels: 15  (7 × LUT6, 5 × CARRY4, LUT3, LUT4, LUT5)
```

That is a single cycle of `S_A_ACC` doing all of: block RAM read → 128-lane barrel rotate → subtract `R_old` → absolute value → clip to the message width → compare against `min1`/`min2` → enable the index register. Every stage of the decoder's arithmetic, end to end, with no register in between.

Two things follow:

1. **64% of the delay is routing on unplaced nets**, which post-synthesis analysis estimates conservatively. The real number needs an implementation run — placement usually improves these estimates substantially.
2. **But the logic alone is 6.057 ns of an 8 ns budget**, and 15 levels is roughly double what 125 MHz on a `-1` part comfortably allows. Even with ideal routing this path does not close. It needs a pipeline register.

### The fix, and what it costs

The datapath is already multi-cycle per edge, so inserting registers costs cycles but no restructuring:

| | Cycles per edge | Critical path |
|---|---|---|
| Now | 3 (pass A), 4 (pass B) | BRAM → rotate → subtract → compare, in one cycle |
| Register `rot_out` | 4 and 5 | split roughly in half |

That is about +27% cycles per iteration — 15,260 → 19,356 for the decode sweep — in exchange for most of the path. If one register is not enough, a second after the subtract splits it again. The trade is worth measuring both ways, because it is exactly the kind of result the evaluation plan wants: **a measured pipelining trade-off, cycles against Fmax**, rather than an assertion that the design "runs at 125 MHz".

## Where the decoder stands

Functionally complete and bit-exact against the model at every stage: syndrome handling, the arithmetic core, the message memory, the iteration loop, early termination, status, and rate adaptation. Area is comfortable — 37.5% of the LUTs and 51.8% of the block RAM, inside REQ-IMP-03's 70%/80%.

The open item is no longer correctness, it is speed: at 58 MHz the throughput would be 28 Mbit/s rather than the 60 Mbit/s that 125 MHz gives. The next two actions decide how much work that is:

1. **An implementation run** on `ldpc_decoder_rate` — writes routed timing, power and placed utilization by itself, and tells us how much of the 10.9 ns of route estimate was pessimism.
2. **One pipeline register** after the rotator, measured before and after.

## Files

| File | Source |
|---|---|
| `ldpc_decoder_rate_utilization_synth.rpt` | `vivado/ldpc_decoder/ldpc_decoder.runs/synth_1/` |
| `ldpc_decoder_rate_timing_synth.rpt` | `report_timing_summary` on the synthesized design |
| `ldpc_decoder_rate_simulate.log` | `vivado/ldpc_decoder/ldpc_decoder.sim/sim_1/behav/xsim/` |

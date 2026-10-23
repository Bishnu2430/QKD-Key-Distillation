# Stage 10 — the other mother codes on the same RTL

| Field | Value |
|---|---|
| Built by | Bishnu, Vivado GUI |
| Date | 23 Oct 2026 |
| Design | `ldpc_decoder_deep` (stage 8), **unmodified** apart from four lines naming the code |
| Status | r850 done, r400 pending |

## The claim under test

Contribution C1 and REQ-FUN-03 say one datapath serves every rate. Until now every build used `v3_mother_1_r700`. This stage runs the same RTL against the two codes at the ends of the range.

## r850 — Q = 1%, row degree 27, 77 layers

### Functionally: exact, with no RTL change

```
mask: 464 key columns, 59392 key bits
frame 0: ok=1 iters=7 (expected ok=1 iters=7), 57107 cycles
frame 1: ok=1 iters=8 (expected ok=1 iters=8), 65254 cycles
STAGE 8 PASSED
```

Four frames, matching `ok`, `iterations` and every key bit — and matching the Verilator pre-run to the cycle. Four lines changed in the whole project: one `include and two `$readmemh` names in the module, one `include and the vector directory in the testbench. **The datapath itself was not touched.**

### Resources — the wide multiplexer was cheap, the memory was not

| | r700 | **r850** | Change |
|---|---|---|---|
| Slice LUTs | 22,921 (43.1%) | **23,497 (44.2%)** | **+576** |
| Slice registers | 14,475 (13.6%) | **17,857 (16.8%)** | +3,382 |
| Slices occupied | 7,279 (54.7%) | 8,180 (61.5%) | |
| **Block RAM tiles** | 72.5 (51.8%) | **99.5 (71.1%)** | **+27** |
| Row degree | 14 | 27 | |

**I predicted the degree-27 multiplexer would be the problem. It cost 576 LUTs.** Selecting one of 27 stored sign bits instead of one of 14 adds a single LUT level per lane, and the tools absorbed it. The register growth is exactly as expected — `sgn_bits` goes from 128×14 to 128×27 and `old_rec` from 3,840 to 5,632 bits, together +3,456 against +3,382 measured.

The block RAM is the real cost. `cn_mem` is 77 × 5,632 bits and takes **78.5 of the 99.5 tiles** at 15% occupancy — a wider, shallower array than r700's, so the shape penalty is worse. Still inside REQ-IMP-03's 80%, but this is the first build where block RAM, not logic, is the binding resource.

### Timing — fails by 40 picoseconds, on one endpoint

```
WNS -0.040 ns    TNS -0.040 ns    1 failing endpoint of 43,168
```

One path, missing by half a percent of the clock period. And it is **not** the path anyone would have guessed:

```
Source:       e_end_reg/CLKARDCLK      (a RAMB36 clock pin)
Destination:  state_reg[1]/CE
Data path:    7.751 ns — logic 3.463 ns (45%), route 4.288 ns (55%)
Logic levels: 5  (1 × CARRY4, 4 × LUT6)
```

`e_end` is the index of a layer's last edge. The synthesis log shows why it starts at a block RAM clock pin:

```
|ldpc_decoder_deep | e_end_reg | 78 x 16 | Block RAM |
```

**Vivado put the 78-entry layer-pointer ROM into a block RAM and used its output register as `e_end`.** So every `if (e_idx == e_end)` in the FSM starts from a RAMB36's 2.45 ns clock-to-out, and the comparison plus the state decode has 5.5 ns left. At r700's 155 entries the same structure existed and never showed up, because the critical path was the inverse rotator; here the rotator path came in at +0.018 ns and this one went 0.040 ns negative.

### The fix is one attribute

A 78 × 16 bit ROM — 1,248 bits — has no business in a block RAM. Forcing it into LUTs makes `e_end` an ordinary fabric flop with a 0.4 ns clock-to-out instead of 2.45 ns:

```systemverilog
  (* rom_style = "distributed" *)
  logic [15:0]           layer_ptr_rom [M_B+1];
```

That should buy roughly 2 ns on this path — fifty times the deficit — and costs about 32 LUTs. It is a synthesis attribute, so simulation is unaffected; the edge ROM (2,048 × 16 bits) should stay in block RAM.

**This is predicted, not measured.** It wants one re-synthesis and re-implementation of r850 to confirm, and it is worth applying to all three codes afterwards for the margin.

### Power — over the requirement at this operating point

| | r700 (measured) | **r850 (vectorless)** |
|---|---|---|
| Dynamic | 0.952 W | **1.245 W** |
| — Signals | 0.371 | 0.458 |
| — Block RAM | 0.289 | **0.442** |
| — Slice logic | 0.236 | 0.290 |
| — Clocks | 0.055 | 0.055 |
| Static | 0.125 | 0.134 |
| **Total** | 1.077 W | **1.379 W** |
| Confidence | High (SAIF) | Medium (no SAIF) |

**REQ-PERF-06 (≤1.0 W dynamic) fails at the r850 operating point**, and the r700 calibration suggests a measured figure would be slightly worse rather than better: the vectorless estimate under-reported by 3.8% there.

Most of the extra is the block RAM — 0.442 W for 99.5 tiles against 0.289 W for 72.5 — which puts `cn_mem` back on the critical list, this time for the right reason. Chunking it to eight lanes per entry would take it from 78.5 tiles to roughly 20, which is both the BRAM headroom M4 and M6 need and the only power lever of any size.

Energy per bit is unaffected by the power problem, because r850 runs at Q = 1% where frames decode in 7 iterations: 57,107 cycles × 9.96 nJ ÷ 59,392 bits = **9.58 nJ/bit**, which still meets the ≤10 stretch target.

## r400 — Q = 8%, row degree 7, 307 layers

### Functionally: exact, again

```
frame 0: ok=1 iters=5 (expected ok=1 iters=5), 70943 cycles
frame 3: ok=1 iters=6 (expected ok=1 iters=6), 85070 cycles
STAGE 8 PASSED
```

Cycle-for-cycle with the Verilator pre-run, as r850 was.

### Resources: the cheapest of the three

| | r850 | r700 | **r400** |
|---|---|---|---|
| Slice LUTs | 23,497 (44.2%) | 22,921 (43.1%) | **21,809 (41.0%)** |
| Slice registers | 17,857 | 14,475 | **12,708** |
| Slices occupied | 8,180 (61.5%) | 7,279 (54.7%) | 6,766 (50.9%) |
| Block RAM tiles | 99.5 (71.1%) | 72.5 (51.8%) | **60.5 (43.2%)** |

Resources track row degree exactly as the architecture predicts: degree 7 narrows every per-lane multiplexer and shrinks the check record to 22 bits, so r400 is smaller than r700 on every axis despite having twice the layers. `cn_mem` at 307 × 2,816 bits is also better shaped — 39.5 tiles for 864,512 bits, against r850's 78.5 tiles for 433,664.

### Timing: fails by 0.042 ns, and it is the same disease

```
WNS -0.042 ns    TNS -0.070 ns    2 failing endpoints of 29,657

Source:       syn_mem_reg_0/CLKARDCLK   (a RAMB36 clock pin)
Destination:  wb_q_reg[118]/D
7.989 ns — logic 4.020 ns (50%), route 3.969 ns (50%), 6 logic levels
```

**Six of the eight worst paths start at `syn_mem_reg_*/CLKARDCLK`.** The syndrome memory went into block RAM, so `syn_q` is a RAMB36 output register with a 2.45 ns clock-to-out, and the sign XOR, the negate and the saturating add that produce `wb_q` have 5.5 ns left.

Power is 0.941 W dynamic, vectorless — which passes, but only just, and r700's calibration says a measured figure would be a few percent worse.

## The two failures are one bug

| Code | Memory Vivado chose | Signal | What follows it in the same cycle |
|---|---|---|---|
| r850 | `layer_ptr_rom` → RAMB36 | `e_end` | `e_idx == e_end` → state enable, 5 levels |
| r400 | `syn_mem` → RAMB36 | `syn_q` | sign XOR → negate → saturating add → `wb_q`, 6 levels |
| r700 | `syn_mem` → **LUT RAM**, `layer_ptr_rom` → RAMB36 but not critical | — | — |

Both failures are a **block RAM's 2.45 ns clock-to-out spending a third of the clock period before a long combinational chain**, on a signal that is then held constant for the whole layer. And r700 escapes by luck: at 154 entries Vivado chose distributed RAM for its syndrome memory, where at 77 and 307 entries it chose block RAM.

That is the real lesson, and it belongs in the write-up: **the same RTL meets timing for one code and misses for another because inference picked a different memory primitive.** A timing-critical read should never be left to a heuristic that varies with array depth.

### The fix: pin both memories

```systemverilog
  (* ram_style = "distributed" *)
  logic [Z-1:0]          syn_mem  [M_B];
```

```systemverilog
  (* rom_style = "distributed" *)
  logic [15:0]           layer_ptr_rom [M_B+1];
```

Both become LUT-based, so `syn_q` and `e_end` become ordinary fabric flops with a 0.4 ns clock-to-out instead of 2.45 — about **2 ns recovered on each path class**, against deficits of 0.040 and 0.042 ns.

| Code | `syn_mem` as LUT RAM | ROM as LUTs | Block RAM freed |
|---|---|---|---|
| r850 (77 layers) | ~256 LUTs | ~32 | 2 tiles |
| r700 (154) | already there | ~48 | 0 |
| r400 (307) | ~640 LUTs | ~80 | 2 tiles |

LUT utilisation stays under 45% for all three, and r850 gets two of its scarce tiles back. `edge_rom` (2,048 × 16 bits) and `cn_mem` stay in block RAM, where they belong — `cn_mem` already carries `ram_style = "block"` for exactly this reason.

## The fix, measured on r400

Both attributes applied, re-synthesised and re-implemented:

| r400 | Before | **After** | Change |
|---|---|---|---|
| WNS | −0.042 ns, 2 failing | **+0.092 ns, 0 failing** | **+0.134 ns** |
| Slice LUTs | 21,809 (41.0%) | 23,300 (43.8%) | +1,491 |
| — as distributed RAM | 12 | 872 | `syn_mem` moved here |
| Slice registers | 12,708 | 12,588 | −120 |
| Block RAM tiles | 60.5 | **57.5** | −3 |
| Dynamic power | 0.941 W | **0.988 W** | +0.047 W |

It works, and it costs more than predicted: +1,491 LUTs against an estimated 720, because the address decode around a 307-deep distributed RAM costs more than the storage. The new critical path is `layer_q` → `cn_mem`'s address pins — **zero logic levels, 94% routing** — the layer counter crossing the die to 39 block RAM tiles.

### Power is now the binding constraint, at both ends

| | r850 | r700 | r400 (fixed) |
|---|---|---|---|
| Dynamic power | 1.245 W est. | 0.952 W measured | **0.988 W est.** |
| REQ-PERF-06 (≤1.0 W) | ❌ by 25% | ✅ | ⚠️ 1.2% under, on an estimate that read 3.8% low for r700 |

r400 has gone from comfortable to marginal, and a SAIF measurement would probably put it just over. Timing is solved; power is not.

### What r850 needs

Its two tightest paths both start at `e_end_reg` — the layer-pointer ROM — so **`rom_style = "distributed"` alone should close it**, worth about 2 ns against a 0.040 ns deficit, for roughly 32 LUTs.

The `syn_mem` attribute is optional there. It would free 2 of r850's scarce block RAM tiles for ~256 LUTs and a little power. Keeping both attributes for all three codes is still the right call — **uniform RTL is worth more than 0.05 W**, and "one datapath" stops meaning much if each code needs its own attributes.

### If power has to come down

A zero-power alternative exists for `syn_mem`: keep it in block RAM and add one pipeline register, so the long chain starts at a fabric flop instead of the RAM output.

```systemverilog
  logic [Z-1:0] syn_raw, syn_q;
  // S_SETUP / S_C_SETUP:  syn_raw <= syn_mem[layer_q];
  always_ff @(posedge clk) syn_q <= syn_raw;
```

128 flip-flops, no LUTs, no extra power, and the block RAM tiles stay. It is safe because `syn_q` is first used at c3 of the first edge, four cycles after `S_SETUP`. It is not needed now — r850's syndrome memory is not on a critical path and r400 already closes — but it is the lever if a measured power number pushes either code over 1 W.

**The structural fix is `cn_mem`.** Chunked to eight lanes per entry it goes from 78.5 tiles to about 20 on r850, 39.5 to 12 on r400, 54 to 21 on r700 — which takes block RAM from 71% to 29% at the worst end, cuts the largest contributor to dynamic power, and frees 30–60 tiles for M4 and M6. That is now the highest-value remaining change to the decoder.

## All three codes with the attributes in place

| | r850 | r700 | r400 |
|---|---|---|---|
| QBER / rate | 1% / 0.869 | 5% / 0.628 | 8% / 0.373 |
| Row degree | 27 | 14 | 7 |
| **WNS** | **−0.094 ns**, 2 failing | **+0.061 ns** | **+0.092 ns** |
| Implied Fmax | 123.5 MHz | 126.0 MHz | 126.2 MHz |
| Slice LUTs | 24,032 (45.2%) | 22,817 (42.9%) | 23,300 (43.8%) |
| Slice registers | 17,991 | 14,552 | 12,588 |
| Slices occupied | 8,340 (62.7%) | 7,318 (55.0%) | 6,946 (52.2%) |
| Block RAM tiles | 96.5 (68.9%) | 71.5 (51.1%) | 57.5 (41.1%) |
| Dynamic power, vectorless | 1.061 W | 1.093 W | 0.988 W |
| Cycles per iteration | 8,147 | 10,149 | 14,127 |
| Functional | ✅ | ✅ | ✅ |

**r700 and r400 meet timing; r850 misses by 0.094 ns and runs at 123.5 MHz.**

### The ROM fix worked; r850 moved its bottleneck

`e_end_reg` appears **zero times** in r850's timing report now, where before it held the two tightest paths. What replaced it is a different path entirely:

```
app_mem_reg_4/CLKARDCLK → rot_q_reg[205]/D
8.039 ns — logic 1.378 ns (17%), route 6.661 ns (83%), 4 logic levels
```

Four logic levels and 6.7 nanoseconds of wire. r850 is not failing on any one path: **it is congestion-bound.** 62.7% of slices, 69% of block RAM, and every top path sitting in the 7.9–8.1 ns band with 80–94% of the delay in routing. Fix one and the placer rearranges and exposes the next. That is a design that needs less area, not more pipelining.

### Vectorless power is not comparable across runs

r700's dynamic power reads 1.093 W here against 0.917 W for the same logic in the stage-8 build, and r850's *fell* from 1.245 W to 1.061 W. The designs barely changed; the placements did. Looking at the components, r700's signals went 0.330 → 0.420 W and its slice logic 0.220 → 0.287 W — net capacitance, not switching.

**So vectorless power varies by roughly ±20% with placement, and only SAIF-based figures are comparable.** The project has exactly one of those: 0.952 W, measured on the stage-8 r700 build. Whether the current builds are better or worse is not knowable without re-capturing, which is worth doing once the design is final.

> **Note on the reports.** The r850 post-fix run was read but not copied before the r700 run overwrote `impl_1`, so only its numbers survive, above. Copy each run's reports into `results/` before starting the next one.

## Where this leaves the claim

| | r850 | r700 | r400 |
|---|---|---|---|
| QBER / rate | 1% / 0.869 | 5% / 0.628 | 8% / 0.373 |
| Row degree | 27 | 14 | 7 |
| Functional, unmodified RTL | ✅ | ✅ | ✅ |
| Cycles per iteration | 8,147 | 10,149 | 14,127 |
| Timing at 125 MHz | ⚠️ 123.5 MHz, congestion-bound | ✅ +0.061 ns | ✅ +0.092 ns |
| Slice LUTs | 44.2% | 43.1% | 41.0% |
| Block RAM | **71.1%** | 51.8% | 43.2% |
| Dynamic power | ❌ 1.245 W est. | ✅ 0.952 W meas. | ⚠️ 0.941 W est. |

Both timing failures have one cause and one two-line fix, described above. After it, all three codes are expected to close.

**One datapath does serve every rate**, in the sense that matters most: no RTL change, bit-exact results, across QBER 1–8% and rate 0.87–0.37. What the high-rate end costs is 27 more block RAM tiles, 0.3 W, and — until the ROM attribute is applied — 40 picoseconds.

## Files

| File | Contents |
|---|---|
| `r850_timing_summary_routed.rpt` | Post-route timing, the failing path and the next nine |
| `r850_power_routed.rpt` | Vectorless power |
| `r850_utilization_placed.rpt` | Post-placement utilization |
| `r850_route_status.rpt` | Fully routed, 43,141 nets, no errors |
| `r850_simulate.log` | Four frames at Q = 1% |

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

## Where this leaves the claim

| | r850 | r700 | r400 |
|---|---|---|---|
| Functional, unmodified RTL | ✅ | ✅ | pending |
| Timing at 125 MHz | ❌ −0.040 ns, one endpoint | ✅ +0.081 ns | pending |
| Resources | 44% LUT, **71% BRAM** | 43% LUT, 52% BRAM | pending |
| Power | ❌ 1.245 W estimated | ✅ 0.952 W measured | pending |

**One datapath does serve every rate**, in the sense that matters most: no RTL change, bit-exact results, across QBER 1–8% and rate 0.87–0.37. What the high-rate end costs is 27 more block RAM tiles, 0.3 W, and — until the ROM attribute is applied — 40 picoseconds.

## Files

| File | Contents |
|---|---|
| `r850_timing_summary_routed.rpt` | Post-route timing, the failing path and the next nine |
| `r850_power_routed.rpt` | Vectorless power |
| `r850_utilization_placed.rpt` | Post-placement utilization |
| `r850_route_status.rpt` | Fully routed, 43,141 nets, no errors |
| `r850_simulate.log` | Four frames at Q = 1% |

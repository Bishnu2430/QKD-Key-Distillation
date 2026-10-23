# Stage 8 — the deep pipeline: **timing closed at 125 MHz**

| Field | Value |
|---|---|
| Built by | Bishnu, by hand in the Vivado GUI |
| Date | 22 Oct 2026 |
| Design | `ldpc_decoder_deep` — the arithmetic stage split in three |
| Oracle | `tv/r700_q05_m16s125/` and `tv/r700_q03_m16s32/` |
| Tool | Vivado ML Standard 2025.2, `xc7z020clg400-1`, out-of-context, 125 MHz constraint |
| Route status | Fully routed, 37,415 nets, 0 routing errors |

## The headline

```
WNS(ns)   TNS(ns)   TNS Failing Endpoints   TNS Total Endpoints
  0.081     0.000                       0                 37850
```

**Timing is met.** WNS +0.081 ns post-route, +1.177 ns post-synthesis, zero failing endpoints of 37,850, hold +0.070 ns, pulse width +2.750 ns. REQ-IMP-02 — WNS ≥ 0 at 125 MHz — is satisfied for the first time in the project.

Functionally unchanged, as every stage has been: `ok`, `iterations` and every decoded key bit match the model on both mask sets, and the cycle counts match Verilator exactly (the fifth stage running).

## The whole pipelining study, in one table

| | Cycles / iteration | WNS synth | WNS route | Fmax | LUT | FF | Q=5% frame |
|---|---|---|---|---|---|---|---|
| Stage 5, sequential | 21,867 | −9.196 | −11.362 | 51.6 MHz | 20,700 | 9,240 | 6.68 ms |
| Stage 6, two registers | 36,203 | *not recovered* | *not recovered* | — | — | — | — |
| Stage 7, one edge per clock | 9,687 | — | −5.719 | 72.9 MHz | 24,397 | 11,327 | 2.09 ms |
| **Stage 8, split arithmetic** | **10,149** | **+1.177** | **+0.081** | **126.3 MHz** | **22,921** | **14,475** | **1.28 ms** |

**5.2× faster per frame than the design that first passed its functional tests**, with the same arithmetic and the same decisions throughout.

Two things in that table are worth a second look:

- **Stage 8 uses 1,476 fewer LUTs than stage 7** despite 3,148 more registers. The shallower stages removed the pressure that had made the placer replicate `pos4` three ways; retiming a design can make it smaller.
- Stage 6's two measurements are still missing, because they were saved in Vivado's binary interactive format. The endpoints of the study are solid; the decomposition between the block RAM register and the rotator register is not recoverable without re-running those two builds.

## Where the critical path ended up

```
Source:       sh6_reg[5]__0_rep__5/C
Destination:  wbr_q_reg[488]/D
Data path:    7.916 ns — logic 0.580 ns (7%), route 7.336 ns (93%)
Logic levels: 1  (LUT5)
```

One LUT and 7.3 nanoseconds of wire. The design is no longer logic-limited in any sense — it is **wire-limited on the inverse rotator**, a 1,024-bit crossbar whose shift amount has to reach every lane. The next three paths are the same shape or feed the APP memory's data input.

**The margin is 1% of the clock period.** That is closed, but it is not comfortable, and it has a practical consequence: when M4 wraps this in AXI and the placer has more to fit, this path is the one that will break first. If headroom is needed, the cut is to split the inverse rotator into two registered halves — one more cycle per edge in pass B, several nanoseconds of slack.

`TIMING-16` ("large setup violation") has gone from 112 instances to none. `SYNTH-6` still fires 11 times, but now for `cn_mem` rather than the APP memory: that memory is read once per layer, so its output register is not on any path that matters.

## Area and power

| Resource | Stage 7 | **Stage 8** | Device |
|---|---|---|---|
| Slice LUTs | 24,397 | **22,921** | 43.08% |
| — as logic | 23,872 | 22,392 | 42.09% |
| — as distributed RAM | 525 | 529 | 3.04% |
| Slice registers | 11,327 | **14,475** | 13.60% |
| Slices occupied | 7,259 | 7,279 | 54.73% |
| Block RAM tiles | 72.5 | 72.5 | 51.79% |
| Total on-chip power | 1.032 W | 1.041 W | |
| Dynamic power | 0.909 W | **0.917 W** | |

The new registers are `rold_q` (128 × 10 bits), `t_q` (128 × 8), `nrm_q` (128 × 7) and `sel2_q` (128 × 1) — 3,328 bits, against 3,148 measured after optimisation.

## Requirements, after stage 8

Energy per cycle is 0.917 W ÷ 125 MHz = 7.34 nJ.

| | Target | Measured | |
|---|---|---|---|
| REQ-IMP-02 timing closure | WNS ≥ 0 at 125 MHz | **+0.081 ns** | ✅ |
| REQ-IMP-03 resources | ≤70% LUT, ≤80% BRAM | 43.1% / 51.8% | ✅ |
| REQ-PERF-05 latency | ≤2 ms | **1.95 ms** at I_max = 24 | ✅ |
| REQ-PERF-06 PL dynamic power | ≤1.0 W | 0.917 W | ✅ on a vectorless estimate |
| REQ-PERF-07 energy per bit | ≤40 (stretch 10) | **24.7** at Q=5%, **8.8** at Q=3% | ✅ , and the 3% point beats the stretch |
| REQ-PERF-04 throughput | ≥50 Mbit/s at Q=5% | 104 Mbit/s at Q=3%, **37.1 at Q=5%** | ❌ |

**Every implementation requirement is now met except throughput at the 5% operating point**, and that one is not a hardware limit: it is 15.75 iterations per frame, which is what decoding at *f* = 1.30 costs. The lever is the mask the PS chooses — a lower rate means fewer iterations and more throughput at the price of efficiency — and that trade has not been measured yet.

Two caveats worth carrying forward:

1. **`I_max` must be 24, not 32**, for the latency figure. No frame in either vector set exceeds 17 iterations, and REQ-FUN-04 marks the default "TBC".
2. **The power number is still vectorless.** A SAIF from a post-implementation timing simulation would turn 0.917 W from an estimate into a measurement, and REQ-PERF-06 passes by 8%.

## Files

| File | Contents |
|---|---|
| `timing_synth.rpt` | Post-synthesis timing summary, saved as text from the Tcl console |
| `ldpc_decoder_deep_timing_summary_routed.rpt` | Post-route timing, the ten worst paths |
| `ldpc_decoder_deep_power_routed.rpt` | Vectorless power, medium confidence |
| `ldpc_decoder_deep_utilization_placed.rpt` | Post-placement utilization |
| `ldpc_decoder_deep_route_status.rpt` | Routing completeness |
| `ldpc_decoder_deep_simulate.log` | The 5% mask set, four frames |

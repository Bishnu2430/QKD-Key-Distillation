# Implementation, unpipelined decoder — routed, fully placed, **timing fails**

| Field | Value |
|---|---|
| Run by | Bishnu, Vivado GUI, `impl_1` |
| Date | 22 Oct 2026 |
| Design | `ldpc_decoder_rate` (bring-up stage 5), out-of-context |
| Device | `xc7z020clg400-1`, speed file `-1` PRODUCTION 1.12 |
| Constraint | `constraints/ldpc.xdc`, 8.000 ns (125 MHz) |
| Route status | **Fully routed**, 32,910 of 32,910 routable nets, 0 routing errors |

This is the project's first implementation run of the decoder, and the first power number of any kind. It is also the baseline the pipelined version will be measured against.

## Timing: WNS −11.362 ns, Fmax ≈ 51.6 MHz

| | Post-synthesis | **Post-route** |
|---|---|---|
| WNS at 8 ns | −9.196 ns | **−11.362 ns** |
| Implied period | 17.196 ns | **19.362 ns** |
| Implied Fmax | 58.2 MHz | **51.6 MHz** |
| TNS | −33,013 ns | −100,286 ns |
| Failing endpoints | 7,496 of 31,341 | **17,476 of 31,431** |
| Worst hold slack | +0.259 ns | +0.070 ns (met) |
| Pulse width | +2.750 ns | +2.750 ns (met) |

**Routing made it worse, not better.** The stage-5 write-up predicted the opposite — that the 64% of post-synthesis delay attributed to unplaced nets was conservative and placement would claw some back. It did not: route delay rose from 10.886 ns to 14.693 ns and is now **77% of the critical path**. The post-synthesis estimate was optimistic, and that is the useful lesson: for a design like this one, synthesis timing is not a safe proxy.

### The worst path, and why it moved

```
Source:       state_reg[2]/C      (FDRE)
Destination:  min2_reg[87][1]/CE  (FDRE)
Data path:    19.109 ns — logic 4.416 ns (23%), route 14.693 ns (77%)
Logic levels: 17  (8 × LUT6, 5 × CARRY4, 3 × LUT4, LUT5)
```

Post-synthesis the path started at the APP block RAM. Post-route it starts at the **state register** — and that is a direct consequence of the [stage-2 rotator sharing](../stage2_layer_datapath/README.md#rotator-sharing-stage-2-step-7). Sharing one 1,024-bit rotator between the read and the write-back put a multiplexer in front of it selected by `state == S_B_WR`, so the state register now sits at the head of the longest combinational chain in the design: state → rotator input mux → 128-lane barrel rotate → subtract `R_old` → absolute value → clip → compare → minimum-finder enable.

That optimisation saved about 3,500 LUTs. It also bought this path. Both halves of that trade belong in the write-up.

### What the methodology report says

| Rule | Count | Message |
|---|---|---|
| `TIMING-16` | 112 | "Large setup violation … could be the result of non-optimal XDC constraints or **non-optimal design architecture**" |
| `SYNTH-6` | 11 | "The timing for the instance `app_mem_reg_*`, implemented as a RAM block, might be sub-optimal as **no output register was merged into the block**" |

The second one is Vivado naming the fix: the block RAMs have an optional output register inside the block, unused because the design reads `app_q` combinationally into the datapath in the same cycle. Turning it on costs a cycle of latency and **no logic at all**, and it is the first register the pipelined version should add.

### The shape of the problem

Slices are 51.17% occupied while LUTs are only 38.91% — the placer had to spread the logic out. A 1,024-bit barrel rotator feeding 128 lanes of arithmetic has enormous net fan-out across the die, so the design is **routing-bound, not logic-bound**: logic is 4.4 ns of a 19.1 ns path. Cutting logic levels alone will not fix it; the registers have to break the long nets as well.

## Power: 1.036 W total, 0.912 W dynamic

| Component | Power (W) | Share of dynamic |
|---|---|---|
| Signals | 0.373 | 41% |
| Block RAM | 0.319 | 35% |
| Slice logic | 0.196 | 21% |
| Clocks | 0.024 | 3% |
| **Dynamic total** | **0.912** | |
| Device static | 0.124 | |
| **Total on-chip** | **1.036** | |

Junction temperature 36.9 °C, maximum ambient 73.1 °C, θ_JA 11.5 °C/W — thermally untroubled.

> **Confidence: Medium, and vectorless.** No SAIF was supplied, so Vivado assumed default switching activity; the estimate also assumes the 125 MHz clock the design does not meet. A real number needs a post-implementation timing simulation writing a SAIF, which is the flow in [doc 12 §3](../../docs/12-toolflow.md). Treat 0.912 W as an order of magnitude, not a measurement.

**Signals plus block RAM are three quarters of the dynamic power**, which is the same story the timing report tells: this design moves very wide words around. The `cn_mem` reshaping (54 tiles at 30% efficiency → ~21) would cut into the 0.319 W of BRAM power as well as the tile count.

## What this does to the requirements

Energy per cycle at 125 MHz is 0.912 W ÷ 125 MHz = **7.3 nJ**, and because dynamic power scales with frequency, energy per bit is roughly clock-independent — cycles are what matter.

| Requirement | Target | Measured | |
|---|---|---|---|
| REQ-IMP-02 timing | WNS ≥ 0 at 125 MHz | −11.362 ns, Fmax 51.6 MHz | ❌ |
| REQ-IMP-03 resources | ≤70% LUT, ≤80% BRAM | 38.9% LUT, 51.8% BRAM | ✅ |
| REQ-PERF-06 PL dynamic power | ≤1.0 W (stretch 0.5) | 0.912 W, vectorless | ⚠️ inside, barely, on a weak estimate |
| REQ-PERF-07 energy per bit | ≤40 nJ/bit (stretch 10) | **15.1** at Q=3%, **52.9** at Q=5% | ⚠️ met at 3%, missed at 5% |
| REQ-PERF-04 throughput at Q=5% | ≥50 Mbit/s | 17.2 at 125 MHz, **7.1 at 51.6 MHz** | ❌ |
| REQ-PERF-05 worst-case latency | ≤2 ms | 5.6 ms at 125 MHz, **13.6 ms at 51.6 MHz** | ❌ |

Four of the five performance requirements now hinge on the same thing: **21,867 cycles per iteration, and a clock that cannot reach 125 MHz**. Both come from the unpipelined edge loop.

## What to do about it

In order of value per unit of typing:

1. **Turn on the block RAM output registers.** Vivado asked for it 11 times. One extra cycle of read latency, no logic, and it moves the APP read out of the critical path entirely.
2. **Register the rotator output**, which also removes the state register from the head of the chain.
3. **Pipeline the edge walk to one edge per cycle**, which takes the iteration from 21,867 cycles to roughly 8,150 — and at that point the throughput and latency requirements come back into reach.

Items 1 and 2 are the timing fix; item 3 is the throughput fix; all three are the same piece of work on the same datapath, which is why they belong in one stage rather than three.

## Files

| File | Contents |
|---|---|
| `ldpc_decoder_rate_timing_summary_routed.rpt` | Post-route timing, including the worst 10 paths |
| `ldpc_decoder_rate_power_routed.rpt` | Vectorless power estimate, medium confidence |
| `ldpc_decoder_rate_utilization_placed.rpt` | Post-placement utilization |
| `ldpc_decoder_rate_route_status.rpt` | Routing completeness |

The methodology report (1.3 MB) is not copied here; its two findings are quoted above.

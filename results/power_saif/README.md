# Stage 9 — power, measured

| Field | Value |
|---|---|
| Run by | Bishnu, Vivado GUI and Tcl console |
| Date | 23 Oct 2026 |
| Design | `ldpc_decoder_deep` (stage 8), routed, 125 MHz |
| Activity | Post-implementation functional simulation, one full decode iteration |
| SAIF window | 85 µs — 20 µs to 105 µs, excluding reset and the once-per-frame loading |
| Confidence | **High** (was Medium) |
| Nets matched | 47% (23,810 of 50,632) |

Every power and energy number the project had quoted until now came from Vivado assuming a 12.5% toggle rate. This replaces that assumption with the decoder's own switching activity.

## The measurement

| | Vectorless estimate | **Measured** | Change |
|---|---|---|---|
| **Dynamic** | 0.917 W | **0.952 W** | **+3.8%** |
| Device static | 0.124 W | 0.125 W | — |
| **Total on-chip** | 1.041 W | **1.077 W** | +3.5% |
| Junction temperature | 37.0 °C | 37.4 °C | — |

**REQ-PERF-06 (≤1.0 W dynamic) is met, now on measured data, with 5% of margin.** The stretch goal of 0.5 W is not in reach for this architecture.

### The total barely moved; the composition did

| Component | Vectorless | Measured | Change | Share of dynamic |
|---|---|---|---|---|
| Signals | 0.330 W | **0.371 W** | +12% | 39% |
| Slice logic | 0.220 W | **0.236 W** | +7% | 25% |
| — LUT as logic | 0.211 | 0.227 | +8% | |
| — Registers | 0.002 | 0.003 | — | |
| Block RAM | 0.319 W | **0.289 W** | **−9%** | 30% |
| Clocks | 0.033 W | **0.055 W** | **+67%** | 6% |

Two of those are worth acting on:

**Block RAM power fell.** The vectorless model assumed the memories are enabled far more often than they are — the APP memory is read on one cycle in three and written on one in three, and `cn_mem` is touched twice per layer. That removes a reason to reshape `cn_mem`: it is still 54 of 72.5 tiles at 30% occupancy, and reclaiming 33 tiles is still worth doing for M4 and M6, but **it is no longer a power optimisation**. The earlier claim that block RAM was "35% of dynamic power and therefore the first lever" was based on the estimate and is wrong.

**Clock power rose two thirds.** 0.055 W for three clock nets reflects the real fan-out of a 14,475-register design across 7,279 slices. It is still only 6% of dynamic, so it does not change priorities, but clock gating the idle passes — the write-back path during pass A, most of the arithmetic during the check sweep — would now save a measurable amount rather than a notional one.

### Signals and logic are two thirds of it

0.607 W of 0.952 W is the datapath switching: two 1,024-bit rotators, 128 lanes of arithmetic and the pipeline registers between them, all active on nearly every cycle of every pass. That is inherent to the architecture, not an inefficiency to be tuned away — it is what a Z = 128 parallel decoder costs.

## Energy per bit — the number that goes in the paper

At 7.616 nJ per clock cycle (0.952 W ÷ 125 MHz):

| Operating point | Cycles | Time | Throughput | **Energy** |
|---|---|---|---|---|
| Q = 3%, 16 punctured + 32 shortened | 71,198 | 0.57 ms | 104.3 Mbit/s | **9.13 nJ/bit** |
| Q = 5%, 125 shortened, no puncturing | 86,433 | 0.69 ms | 71.6 Mbit/s | **13.29 nJ/bit** |
| Q = 5%, 16 punctured + 125 shortened | 159,847 | 1.28 ms | 37.1 Mbit/s | 25.64 nJ/bit |

**REQ-PERF-07 (≤40 nJ/bit) is met at every operating point, and the Q = 3% point meets the ≤10 nJ/bit stretch goal.**

Against the literature baseline the evaluation plan names — roughly 970 nJ/bit, estimated from Liao 2025 — this is **75–100× lower energy per corrected bit**, and it is now a measurement at both ends of the division rather than an estimate.

## What the 47% means

Vivado matched 23,810 of 50,632 nets to the SAIF; the rest keep their vectorless estimates, so the figure is a hybrid weighted towards the measured part. Vivado still grades it High. The shortfall comes from the post-implementation *functional* netlist and the routed database not naming every net identically — a post-implementation *timing* simulation would match more, at hours rather than minutes of runtime.

Two further caveats:

- **No glitch power.** A functional simulation records intended transitions only. On a 1,024-bit crossbar driven by a 7-bit shift amount, glitching is real; a timing simulation would capture it, and the gap between the two would itself be a result.
- **38 nets were dropped** from the SAIF before Vivado could read it — the simulator wrote names containing `(null)` from unnamed scopes, with escaped parentheses its own parser rejects. 38 of 90,125 records, documented in [the stage-9 guide](../../docs/stages/09-power-saif.md).

## Requirements after this measurement

| | Target | Measured | |
|---|---|---|---|
| REQ-PERF-06 power | ≤1.0 W dynamic (stretch 0.5) | **0.952 W** | ✅ |
| REQ-PERF-07 energy | ≤40 nJ/bit (stretch 10) | **9.13** at Q=3%, 13.29 at Q=5% | ✅ , stretch met at Q=3% |

With [stage 8](../stage8_deep_pipeline/README.md)'s timing closure and [E3](../e3_throughput_tradeoff/README.md)'s throughput result, **every implementation and performance requirement on the decoder is now met and measured**, except reconciliation efficiency — REQ-PERF-01's *f* ≤ 1.15, which is a property of the code, not the hardware, and has been open since M3.

## Files

| File | Contents |
|---|---|
| `power_saif.rpt` | Power from measured activity, High confidence |
| `power_hier.rpt` | The same, broken down three levels of hierarchy |
| `decoder.saif`, `decoder_clean.saif` | The raw activity dump and the filtered copy Vivado can read. Not tracked — 8.4 MB, regenerable |

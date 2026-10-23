# Stage 7 — the pipelined decoder: 2.26× fewer cycles, 1.41× the clock, timing still fails

| Field | Value |
|---|---|
| Built by | Bishnu, by hand in the Vivado GUI |
| Date | 22 Oct 2026 |
| Design | `ldpc_decoder_pipe`, one edge issued per clock |
| Oracle | `tv/r700_q03_m16s32/` (10 frames) and `tv/r700_q05_m16s125/` (4 frames) |
| Tool | Vivado ML Standard 2025.2, `xc7z020clg400-1`, out-of-context, 125 MHz constraint |
| Route status | Fully routed, 36,908 nets, 0 routing errors |

## Functional result — unchanged decisions, far fewer cycles

```
frame 0: ok=1 iters=7 (expected ok=1 iters=7), 67964 cycles
frame 7: ok=1 iters=6 (expected ok=1 iters=6), 58277 cycles
STAGE 7 PASSED
```

Fourteen frames across two mask sets: `ok`, `iterations` and every decoded key bit match the reference model, and the cycle counts match the Verilator run **exactly** — the fourth stage running where xsim and Verilator agree cycle for cycle.

| | Stage 5 | Stage 6 | **Stage 7** |
|---|---|---|---|
| Cycles per iteration | 21,867 | 36,203 | **9,687** |
| Q = 3% frame, 7 iterations | 153,224 | — | **67,964** |
| Q = 5% frame, mean 15.75 iterations | 344,560 | 570,352 | **152,725** |

## Timing: WNS −5.719 ns, Fmax 72.9 MHz

| | Unpipelined (stage 5) | **Pipelined (stage 7)** |
|---|---|---|
| WNS at 8 ns | −11.362 ns | **−5.719 ns** |
| Implied Fmax | 51.6 MHz | **72.9 MHz** |
| TNS | −100,286 ns | −31,207 ns |
| Failing endpoints | 17,476 of 31,431 | 13,927 of 35,280 |
| Hold / pulse width | met | met (+0.070 / +2.750) |

**The clock improved by 41% and the cycle count by 2.26×, so a frame now takes 3.2× less time** — but the constraint is still missed by 5.7 ns.

### Every worst path is the same stage

The six worst paths are indistinguishable in shape:

| Source | Destination | Levels | Slack |
|---|---|---|---|
| `pos4_reg[2]…replica_9` | `min2_reg[17][1]/CE` | 17 | −5.719 |
| `pos4_reg[2]…replica_9` | `idx_reg[17][1]/CE` | 17 | −5.679 |
| `pos4_reg[2]…rep__1` | `wb_q_reg[817]/D` | 16 | −5.665 |
| `pos4_reg[2]…rep` | `min2_reg[103][1…3]/CE` | 17 | −5.644 |

```
Data path: 13.430 ns — logic 3.750 ns (28%), route 9.680 ns (72%)
```

All of them start at **`pos4`**, the pipeline's position register at the arithmetic stage, and end in the minimum finder or the write-back word. That is the whole of c4 in one cycle: reconstruct `R_old` from the record, subtract it, take the absolute value, clip, compare against `min1`/`min2`, update.

`pos4` is the slowest input because of what it feeds, 128 times over: a 4-bit comparison against the stored index, a 14-to-1 multiplexer selecting that edge's stored sign bit, and in pass B a second comparison against `idx[i]`. The placer has already replicated the register several times (`_rep`, `_rep__0`, `_replica_9`) trying to cope with the fan-out.

So the pipeline did its job — the old path through the block RAM, the state decode and the rotator is gone — and what remains is a single arithmetic stage that is simply too deep.

## Area and power

| Resource | Stage 5 | **Stage 7** | Device |
|---|---|---|---|
| Slice LUTs | 20,700 | **24,397** | 45.86% |
| Slice registers | 9,240 | 11,327 | 10.65% |
| Slices occupied | 6,806 | 7,259 | 54.58% |
| Block RAM tiles | 72.5 | 72.5 | 51.79% |
| Total on-chip power | 1.036 W | **1.032 W** | |
| Dynamic power | 0.912 W | **0.909 W** | |

The second rotator cost 3,697 LUTs, within the 3,500 estimate. Registers rose by only 2,087 rather than the ~5,000 predicted, because Vivado absorbed several pipeline words into block RAM output registers and shift-register LUTs.

**Power is unchanged while the work per frame fell 2.26×**, and that is the headline for the energy requirement. At 7.27 nJ per cycle (0.909 W ÷ 125 MHz, and energy per bit is clock-independent because dynamic power scales with frequency):

| | Cycles per frame | Energy | Per key bit | REQ-PERF-07 (≤40, stretch ≤10) |
|---|---|---|---|---|
| Q = 3%, 16+32 mask | 66,027 | 0.480 mJ | **8.1 nJ/bit** | **beats the stretch target** |
| Q = 5%, 16+125 mask | 152,725 | 1.110 mJ | **23.4 nJ/bit** | met (was 52.9 — missed) |

## Requirements, after stage 7

| | Target | Stage 5 | **Stage 7** | |
|---|---|---|---|---|
| REQ-IMP-03 resources | ≤70% LUT, ≤80% BRAM | 38.9 / 51.8 | 45.9 / 51.8 | ✅ |
| REQ-PERF-07 energy | ≤40 nJ/bit | 52.9 at Q=5% | **23.4** | ✅ |
| REQ-PERF-06 power | ≤1.0 W dynamic | 0.912 | 0.909 | ⚠️ vectorless estimate |
| REQ-PERF-04 throughput Q=5% | ≥50 Mbit/s | 7.1 | **22.7** at 72.9 MHz, 38.9 at 125 | ❌ |
| REQ-IMP-02 timing | WNS ≥ 0 at 125 MHz | −11.362 | **−5.719** | ❌ |
| REQ-PERF-05 latency | ≤2 ms at I_max | 13.6 ms | **4.25 ms** at 72.9 MHz | ❌ |

Two of these have cheap answers that are not more RTL:

- **Latency** is `I_max × 9,687` cycles. At 125 MHz, I_max = 32 gives 2.48 ms and **I_max = 24 gives 1.86 ms** — and no frame in either vector set needs more than 17 iterations. REQ-FUN-04 marks the default as "TBC"; 24 is the number to confirm it at.
- **Throughput at Q = 5%** is dominated by 15.75 iterations, which is what running at *f* = 1.30 costs. A lower-rate mask trades efficiency for iterations and the PS picks it per frame.

## What is actually in the way

One pipeline stage. Splitting c4 so that the `pos`-dependent work happens a cycle earlier — reconstructing `R_old` at c3, in parallel with the rotate, and registering `T` — would halve the deepest chain and take the `pos4` fan-out off it entirely. That is the next stage, and it is the only thing between this design and timing closure.

## Not recovered

Stage 6's two measurements (pass A, the block RAM output register; pass B, the rotator register) were saved from the GUI as `results/stage5_passA.rpt` and `stage5_passB.rpt`, which are Vivado's **binary interactive report format** despite the `.rpt` name — the same trap as `timing_1.rpx`. Their WNS values cannot be read outside Vivado, so the decomposition between the two registers is still unknown. They can be reopened in the GUI, or regenerated with `report_timing_summary -file …` from the Tcl console, which writes text.

## Files

| File | Contents |
|---|---|
| `ldpc_decoder_pipe_timing_summary_routed.rpt` | Post-route timing, with the ten worst paths |
| `ldpc_decoder_pipe_power_routed.rpt` | Vectorless power, medium confidence |
| `ldpc_decoder_pipe_utilization_placed.rpt` | Post-placement utilization |
| `ldpc_decoder_pipe_route_status.rpt` | Routing completeness |
| `ldpc_decoder_pipe_simulate.log` | The 10-frame run on the 3% mask set |

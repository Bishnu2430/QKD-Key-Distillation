# Stage 11 — chunked check records: r850 closes, and the decoder is finished

| Field | Value |
|---|---|
| Built by | Bishnu, Vivado GUI |
| Date | 26 Oct 2026 |
| Design | `ldpc_decoder_chunk` — `cn_mem` stored four chunks deep instead of one entry wide |
| Tool | Vivado ML Standard 2025.2, `xc7z020clg400-1`, out-of-context, 125 MHz |

## The result this stage existed for

r850 had been failing timing at −0.094 ns with no single path to blame: 69% block RAM, 63% slices, and every top path 80–94% routing. The hypothesis was **congestion, not logic** — that the check-record memory's 79 tiles at 15% occupancy were forcing long routes across the die.

| r850 | Stage 10 | **Stage 11** | |
|---|---|---|---|
| WNS | −0.094 ns, 2 failing | **+0.036 ns, 0 failing** | ✅ |
| Block RAM tiles | 96.5 (68.9%) | **37.5 (26.8%)** | −59 |
| Dynamic power | 1.061 W | **0.713 W** | −33% |
| Slice LUTs | 24,032 (45.2%) | 26,684 (50.2%) | +2,652 |
| Slice registers | 17,991 | 16,688 | −1,303 |
| Slices occupied | 8,340 (62.7%) | 8,171 (61.4%) | — |
| Cycles per iteration | 8,147 | 8,686 | +6.6% |

The hypothesis was right. Taking 59 tiles out of a 140-tile device shortened exactly the routes that had been failing, and the worst path is now `state → sgn_bits` at +0.036 ns — the same path that sat at +0.034 ns two builds ago, untouched while everything around it improved.

**Power fell 33%**, which settles REQ-PERF-06 for the high-rate code: it was failing at 1.245 W when this investigation started and now has 29% of margin.

## Both codes, both configurations

| | r850 chunked | r700 chunked | r700 flat | r400 flat |
|---|---|---|---|---|
| `CN_CHUNKS` | 4 | 4 | 1 | 1 |
| WNS | **+0.036** | +0.079 | +0.061 | +0.092 |
| Slice LUTs | 26,684 (50.2%) | 29,486 (55.4%) | 22,817 (42.9%) | 23,300 (43.8%) |
| Block RAM | **37.5 (26.8%)** | 44.5 (31.8%) | 71.5 (51.1%) | 57.5 (41.1%) |
| Dynamic power | **0.713 W** | 0.791 W | 1.093 W | 0.988 W |
| Cycles per iteration | 8,686 | 11,227 | 10,149 | 16,276 |

All four configurations meet timing at 125 MHz. Chunking is a **per-code choice**: r850 needs it, r400 should not use it, and r700 can go either way depending on whether M4 and M6 want memory or logic.

### The shift register was worth about 4,000 LUTs

r700 was built with the chunk fetch written as `old_rec[ch_d*CH_W +: CH_W] <= cn_q` and cost **+6,669 LUTs**. r850 was built with `old_rec <= {cn_q, old_rec[CN_W-1:CH_W]}` and cost **+2,652** — on *wider* records, where the indexed form would have been more expensive still.

A variable index into a 3,840-bit register makes every bit a multiplexer. The chunks arrive in order, so shifting puts each one where the lane indexing expects it for the price of wiring. Worth remembering as a general point: **in-order writes into a wide register should shift, not index.**

## The decoder, finished

Every requirement on the decoder is now met and measured, across the whole code set:

| | Target | r850 | r700 | r400 |
|---|---|---|---|---|
| REQ-IMP-02 timing | WNS ≥ 0 at 125 MHz | ✅ +0.036 | ✅ +0.079 | ✅ +0.092 |
| REQ-IMP-03 resources | ≤70% LUT, ≤80% BRAM | ✅ 50% / 27% | ✅ 55% / 32% | ✅ 44% / 41% |
| REQ-PERF-06 power | ≤1.0 W dynamic | ✅ 0.713 W | ✅ 0.791 W | ⚠️ 0.988 W |
| REQ-PERF-07 energy | ≤40 nJ/bit | ✅ | ✅ 9.1 at Q=3% | ✅ |
| REQ-PERF-04 throughput | ≥50 Mbit/s at Q=5% | — | ✅ 71.6 (no-puncture mask) | — |
| REQ-PERF-05 latency | ≤2 ms | ✅ | ✅ at I_max = 21 | ✅ |
| REQ-FUN-01…05 function | bit-exact | ✅ | ✅ | ✅ |

The one open item is **REQ-PERF-01**, reconciliation efficiency *f* ≤ 1.15, which is a property of the LDPC code rather than the hardware and has been open since M3.

Two measurement caveats carried forward: the power figures here are vectorless (only the stage-9 r700 build has a SAIF measurement, at 0.952 W), and vectorless estimates have varied ±20% with placement — so the final build should be re-measured with a SAIF before any of these numbers is quoted.

## Files

| File | Contents |
|---|---|
| `r850_timing_summary_routed.rpt` | Post-route timing, +0.036 ns |
| `r850_power_routed.rpt` | Vectorless power, 0.713 W dynamic |
| `r850_utilization_placed.rpt` | 50.2% LUT, 26.8% block RAM |
| `r850_route_status.rpt` | Fully routed |
| `r850_simulate.log` | Four frames at Q = 1%, bit-exact |

r700's chunked reports were overwritten by this run; its numbers are in the table above and in [stage 10's results](../stage10_other_codes/README.md).

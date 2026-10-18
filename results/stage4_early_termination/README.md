# Stage 4 — early termination and status: PASSED, all 20 frames

| Field | Value |
|---|---|
| Built by | Bishnu, by hand in the Vivado GUI |
| Date | 18 Oct 2026 |
| Code | `v3_mother_1_r700` — n = 65,536, Z = 128, 154 layers, unmasked (R₀ = 0.699) |
| Oracle | `tv/r700_q03/` — 20 frames at QBER 3%, with `expected.csv` and the expected decoded bits |
| Tool | Vivado ML Standard 2025.2, `xc7z020clg400-1`, out-of-context, `constraints/ldpc.xdc` at 125 MHz |

## Functional result — the end-to-end claim

```
frame 0: ok=1 iters=6 (expected ok=1 iters=6), 131357 cycles
frame 4: ok=1 iters=7 (expected ok=1 iters=7), 153224 cycles
...
frame 19: ok=1 iters=6 (expected ok=1 iters=6), 131357 cycles
STAGE 4 PASSED
```

For all twenty frames, three independent things match the bit-true model:

1. **Whether** the frame decoded — `ok` on every frame.
2. **How long** it took — `iterations`, exactly: 6 for sixteen frames, 7 for frames 4, 5, 11 and 12.
3. **What it decoded to** — all 65,536 hard decisions per frame, 1.31 million bits in total.

That is what licenses the rest of the project: **the FER and efficiency curves measured in Python describe this hardware**, because on every frame tested the hardware reaches the same decision, after the same number of iterations, as the model those curves came from. Nothing weaker would do — a decoder that is "nearly right" would show up as a quietly worse curve, not as a failure.

The cycle counts also match the Verilator run exactly (131,357 and 153,224, total simulated time 21,987,944 ns against Verilator's 22 ms), as they did for stage 3. Two independent simulators, identical cycle counts.

## Throughput

| | Value |
|---|---|
| Cycles per iteration | 21,867 (15,260 decode + 6,606 check + 1) |
| Iterations per frame | 6.20 mean over 20 frames |
| Cycles per frame | 135,730 mean |
| Time per frame at 125 MHz | 1.086 ms |
| Raw key throughput | **60.3 Mbit/s** at QBER 3% |
| Same decoder, fixed 32 iterations | 699,744 cycles, 5.60 ms, 11.7 Mbit/s |

Early termination is therefore worth **5.15×** on this operating point, for bit-identical output. The measured difference between a 6-iteration frame and a 7-iteration one is 21,867 cycles — exactly the predicted per-iteration cost, so the controller has no hidden overhead.

## Synthesis (out-of-context, `xc7z020clg400-1`)

| Resource | Stage 3 | Stage 4 | Change |
|---|---|---|---|
| Slice LUTs | 22,389 (42.08%) | **18,836 (35.41%)** | **−3,553** |
| — LUT as logic | 22,389 | 18,320 | −4,069 |
| — LUT as distributed RAM | 0 | 516 | +516 |
| Slice registers | 8,914 (8.38%) | 9,173 (8.62%) | +259 |
| Block RAM tiles | 72 (51.43%) | **70 (50.00%)** | −2 |
| DSP | 0 | 0 | — |
| F7 muxes | 91 | 126 | +35 |

**The decoder got smaller as it got more capable.** Two effects, both worth recording:

**1. Removing the clearing multiplexer saved more than predicted.** Stage 3 chose `cn_wdata` between the new record and all-zeros: 3,840 bits of 2:1 multiplexer, which I estimated at ~1,900 LUTs. Zeroing the per-lane registers at `start` instead removed about 4,000 LUTs of logic — the multiplexer plus the fan-out tree that drove it. The syndrome check sweep it paid for costs almost nothing, as predicted: 128 XOR gates, a 128-bit comparison, and reuse of the existing rotator, APP port and ROMs. Compare stage 1's standalone checker at 1,282 LUTs.

**2. The syndrome memory moved from block RAM to LUT RAM.** `syn_mem` was 2 RAMB36 in stage 3 and is 516 LUTs of distributed RAM here. The obvious explanation — stage 4 reads it in two places (`S_SETUP` and `S_C_SETUP`) — is **wrong**, and it is worth recording why, because the real cause is more useful:

> Re-synthesising the *unchanged* stage-3 module with `constraints/ldpc.xdc` in the project (18 Oct, 21:53) gives 516 LUTs of distributed RAM and 70 BRAM tiles too — the same swap, with one reader. So the trigger is the **clock constraint**, not the second reader: given a 125 MHz target, Vivado prefers LUT RAM for a 154 × 128 memory because distributed RAM has no mandatory output register and so a shorter path to the first logic stage. Without a constraint it had no reason to care and chose the denser option.

A good trade either way — BRAM is the binding resource and LUTs are not — but it is an inference decision driven by a constraint, which is exactly the kind of thing that changes under the user's feet between runs.

### Stage 3's module, re-synthesised with the clock constraint

| Resource | No constraints (16 Oct) | With `ldpc.xdc` (18 Oct) |
|---|---|---|
| Slice LUTs | 22,389 | 22,556 |
| — of which LUT as memory | 0 | 516 |
| Slice registers | 8,914 | 9,008 |
| Block RAM tiles | 72 | 70 |

Same RTL, same part, same tool. The lesson for the write-up: **area numbers quoted without the constraint set are not reproducible**, so every figure in the paper needs to come from a constrained run.

### Where the block RAM is now

| Memory | Tiles | Share |
|---|---|---|
| `cn_mem` (check records, 154 × 3,840) | 54 | 77% |
| `app_mem` (APP array, 512 × 1,024) | 15 | 21% |
| Edge and layer-pointer ROMs | ~1 | 2% |
| `syn_mem` | 0 (now LUT RAM) | — |

The check-record memory is still three quarters of the block RAM at 30% tile efficiency. Reshaping it to eight lanes per entry (240 bits × 2,464) would return about 33 tiles for 32 extra cycles per layer — now the single largest optimisation left in the decoder.

## Budget position

| | LUT | BRAM tiles |
|---|---|---|
| REQ-IMP-03 limit | 70% (37,240) | 80% (112) |
| Stage 4 | **35.4%** | **50.0%** |
| Headroom | 18,404 LUT | 42 tiles |

The functionally complete decoder (bar rate masks, which are a handful of LUTs on the load path) fits in half the device. That leaves room for the AXI wrapper, the verification tag and privacy amplification — and the `cn_mem` reshaping is in hand if BRAM gets tight.

## Not yet measured

**Timing.** `constraints/ldpc.xdc` is now in the project and the synthesis log confirms it was parsed, but no timing report was produced, so WNS and Fmax at 125 MHz are still unknown — for every stage so far. One action closes it: *Open Synthesized Design → Report Timing Summary*, then save the report. Note that the I/O delay constraints are reported as implementation-only in out-of-context mode, which is expected; `create_clock` is what matters for the internal paths.

Also still open: the stage-2 rotator-sharing before/after LUT pair ([stage 2's results](../stage2_layer_datapath/README.md)).

## Files

| File | Source |
|---|---|
| `ldpc_decoder_utilization_synth.rpt` | `vivado/ldpc_decoder/ldpc_decoder.runs/synth_1/` |
| `ldpc_decoder_simulate.log` | `vivado/ldpc_decoder/ldpc_decoder.sim/sim_1/behav/xsim/` |
| `../../constraints/ldpc.xdc` | The 125 MHz constraint set, tracked in the repository |

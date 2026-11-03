# Stage 15 — privacy amplification: 31 Mbit/s for 6,784 LUTs, and the last functional block is done

| Field | Value |
|---|---|
| Built by | Bishnu, Vivado GUI |
| Date | 3 Nov 2026 |
| Design | `toeplitz_pa` — output-chunk Toeplitz hashing, `B = 256` |
| Tool | Vivado ML Standard 2025.2, `xc7z020clg400-1`, out-of-context, 125 MHz |
| Pre-check | Verilator 5.052, five cases bit-exact against the L2 model |
| Closes | REQ-FUN-07, REQ-PERF-08 |

## The result this stage existed for

| | Target | Measured | |
|---|---|---|---|
| REQ-PERF-08 PA throughput at *N* = 2¹⁷ | ≥ 25 Mbit/s | **31.1 Mbit/s** | ✅ |
| REQ-IMP-02 timing at 125 MHz | WNS ≥ 0 | **+0.156 ns**, 0 failing of 2,047 | ✅ |
| REQ-FUN-07 runtime *N* and ℓ | configurable | *N* from `TLAST`, ℓ from `n_chunks` | ✅ |
| Slice LUTs | — | **6,784 (12.75%)** | |
| Slice registers | — | 775 (0.73%) | |
| Block RAM | — | **11.5 tiles (8.21%)** | |
| Dynamic power | — | **0.054 W** | |

Privacy amplification is contribution **C3** and the last functional block in the chain: the decoder corrects Bob's key, the stage-14 tag proves it matches Alice's, and this compresses what remains into a key Eve has negligible information about. All three now exist in RTL and meet timing.

## B = 256 was forced, and the measurement confirms the arithmetic it was chosen on

`B` is the only free parameter and it trades LUTs against time one for one. The choice was made from stage 14's measured density of 2.5 AND-XOR terms per LUT, and the array is `W·B = 16,384` terms wide:

| B | AND-XOR/cycle | LUTs predicted | LUTs measured | Mbit/s at *N* = 2¹⁷ | |
|---|---|---|---|---|---|
| 128 | 8,192 | ~3,300 | — | 15.6 | ✗ misses REQ-PERF-08 |
| **256** | **16,384** | **~6,550** | **6,784** | **31.1** | ✅ |
| 1024 | 65,536 | ~26,200 | — | 124.6 | ✗ 103% of the device |

**6,784 against 6,550 predicted — 3.6% out.** Stage 14's density figure transferred at four times the array width, which is the first time a resource prediction in this project has landed inside its own error bar. The measured density here is 16,384/6,784 = **2.42 AND-XOR terms per LUT**, close enough to stage 14's 2.57 to treat 2.4–2.6 as the device constant for this kind of array.

So `B = 256` is not a tuning choice. REQ-PERF-08's 25 Mbit/s sets the floor, REQ-IMP-03's 70% LUT ceiling sets the roof, and one power of two lies between them.

## Timing: four LUT levels, and the path is exactly where the architecture said it would be

```
Slack (MET):       0.156 ns
Source:            blk_mem_reg_2/CLKBWRCLK   (block RAM output)
Destination:       acc_reg[21]/D             (the accumulator)
Data Path Delay:   7.792 ns  (logic 3.202 ns / 41%, route 4.590 ns / 59%)
Logic Levels:      4  (LUT4=1, LUT5=1, LUT6=2)
```

The critical path is block RAM → AND-XOR tree → accumulator, four LUT levels deep, which is what the design note predicted: a 64-term AND-XOR is about 22 LUT6 of first level and a three-deep XOR tree. Nothing unexpected limits this design.

> **The margin is 59% routing at 12.75% occupancy, and that number will not survive integration.** Stage 11 is the precedent: r850 failed at −0.094 ns with every top path 80–94% routing, and the fix was removing 59 block RAM tiles to shorten routes — congestion, not logic. This build has the whole device to itself. In the full system the device is 66% full, and +0.156 ns of out-of-context slack is not a prediction that it closes there.
>
> If it does fail, synthesis has already named the first thing to try:
>
> ```
> INFO: [Synth 8-7052] The timing for the instance blk_mem_reg_0 (implemented as a
>   Block RAM) might be sub-optimal as no optional output register could be merged
>   into the ram block. Providing additional output register may help...
> ```
>
> The critical path starts at that block RAM. Adding a pipeline register on `blk_q` would move the delay inside the BRAM primitive and cost one cycle per chunk out of 2,058.

## Block RAM: the 1,024 boundary was not the whole lesson

| Array | Shape | RAMB36 | RAMB18 | Tiles | Predicted |
|---|---|---|---|---|---|
| `blk_mem` | 2 K × 64 | 4 | 0 | 4.0 | 4 |
| `seed_mem` | 3 K × 64 | 7 | 1 | 7.5 | 6 |

`blk_mem` landed exactly on the estimate. `seed_mem` cost 7.5 tiles where 6 would have held the data — 1.875× the cost of an array only 1.5× as deep.

Stage 14's lesson was to keep memory depths on the 1,024 boundary, after `SEED_DEPTH = 1032` cost 4 tiles where 2 would have done. 3,072 *is* on a 1,024 boundary and still pays a premium, so the refined rule is that **Vivado's cascade wants powers of two, not multiples of 1,024** — 2,048 is clean, 3,072 is not. That explanation is inference from these two numbers, not something the reports state.

It cannot be fixed by resizing: the seed genuinely needs *N* + ℓ − 1 = 196,607 bits = 3,072 words at *N* = 2¹⁷ and ℓ = *N*/2. The 1.5 extra tiles are the price of the operating point, and at 8.21% of the device they do not matter. The rule matters for the next array that does.

## Power

| | |
|---|---|
| Total on-chip | 0.158 W |
| **Dynamic** | **0.054 W** |
| Device static | 0.104 W |
| Confidence | Medium (vectorless) |

Dynamic breaks down as 0.018 W signals, 0.017 W slice logic, 0.011 W clocks, 0.007 W block RAM. For the LUT count this is very low, because the array is combinational and only 775 registers toggle — and because PA runs once per block, not once per frame.

As ever this is **estimated, vectorless, Medium confidence**, and vectorless estimates in this project have moved ±20% with placement. REQ-VER-04 wants SAIF-annotated power, which is still outstanding for the whole design.

## What this does to the system budget

| | Stage 13 system | + stage 15 | REQ-IMP-03 | |
|---|---|---|---|---|
| Slice LUTs | 28,241 (53.08%) | **35,025 (65.84%)** | ≤ 70% | ✅ 4.2 points spare |
| Block RAM | 53.5 (38.21%) | **65.0 (46.43%)** | ≤ 80% | ✅ |
| PL dynamic power | 0.847 W | **0.901 W** | ≤ 1.0 W (REQ-PERF-06) | ✅ 10% spare |

These are sums of two separate out-of-context builds, not a measurement of an integrated design. PA is not in the block design yet — it has no AXI wrapper.

**This is the stage that nearly fills the device.** 4.2 points of LUT margin is the tightest this project has run, and the AXI wrapper PA still needs will consume some of it: stage 12's wrapper cost about 450 LUTs around the decoder.

## Verification status

| Case | *N* | ℓ | chunks | Verilator | xsim |
|---|---|---|---|---|---|
| `n1024_l256` | 1,024 | 256 | 1 | ✅ PASSED | — |
| `n1024_l512` | 1,024 | 512 | 2 | ✅ PASSED | **✅ PASSED** |
| `n8192_l4096` | 8,192 | 4,096 | 16 | ✅ PASSED | — |
| `n65536_l32768` | 65,536 | 32,768 | 128 | ✅ PASSED | — |
| `n131072_l65536` | 131,072 | 65,536 | 256 | ✅ PASSED | — |

All five are bit-exact against `model.hashing.privacy_amplify`, which computes the whole ℓ-bit output in one numpy expression while the RTL computes it in ℓ/B sliding-window passes — so agreement is a genuine cross-check and not a restatement of the same loop.

**Six mutations were injected into the design and five were caught** (wrong per-chunk seed step, wrong emit word order, window shifting two words, accumulator not cleared between chunks, prime one cycle short). The sixth — making the seed read enable a constant `1'b1` — passes every vector, and correctly so: unlike stage 14, the pass phase reads the block out of block RAM and cannot stall, so that gating is defensive rather than load-bearing. The RTL comment says so rather than claiming a correctness argument it does not have.

### The open item

**Only the 2-chunk case has been run in xsim.** The 31.1 Mbit/s figure is a Verilator cycle count. xsim and Verilator agree on the answer and differ by one cycle in 55 on the case both ran, because the testbench's driver and sink share one xorshift state and the two simulators interleave their processes differently. On the 256-chunk case that difference would be a handful of cycles in 527,281, so the number is sound — but `n131072_l65536` is the only case that exercises all 256 chunks of seed-offset stepping, and it has not yet been through a 4-state simulator. Giving the two processes separate RNG states would also make the cycle count reproducible across tools.

## Files

| File | Contents |
|---|---|
| `toeplitz_pa_utilization_placed.rpt` | 6,784 LUTs (12.75%), 775 registers, 11.5 block RAM |
| `toeplitz_pa_timing_summary_routed.rpt` | WNS +0.156 ns, 0 failing endpoints |
| `toeplitz_pa_power_routed.rpt` | 0.054 W dynamic, vectorless, Medium confidence |
| `toeplitz_pa_route_status.rpt` | 10,035 nets, fully routed |
| `pa_simulate.log` | xsim, `n1024_l512`, `STAGE 15 PASSED` |

## Reproduce

```bash
uv run python scripts/export_pa_vectors.py --out tv/pa
```

Then in Vivado, with `-mode out_of_context` set and `constraints/ldpc.xdc` enabled:

```bash
set_property top toeplitz_pa [get_filesets sources_1]
```

Full click-by-click in `docs/stages/15-privacy-amplification.md` (kept locally, not tracked).

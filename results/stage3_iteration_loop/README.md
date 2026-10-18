# Stage 3 — the check-message memory and the iteration loop: PASSED

| Field | Value |
|---|---|
| Built by | Bishnu, by hand in the Vivado GUI |
| Date | 18 Oct 2026 |
| Code | `v3_mother_1_r700` — n = 65,536, Z = 128, 154 layers, 2,048 base edges |
| Oracle | `tv/r700_q03_iters/` — per-iteration APP snapshots from the bit-true L2 model |
| Tool | Vivado ML Standard 2025.2, `xc7z020clg400-1`, out-of-context |

## Functional result

```
running 1 iteration(s) ...
after 1 iteration(s): 0 lane mismatches
running 3 iteration(s) ...
after 3 iteration(s): 0 lane mismatches
running 6 iteration(s) ...
after 6 iteration(s): 0 lane mismatches
STAGE 3 PASSED
```

All 65,536 APP values match the bit-true model after 1, 3 and 6 iterations. The model's convergence record for this frame is 5,514 → 2,912 → 1,726 → 718 → 124 → 3 → **0** unsatisfied checks, so **the sixth snapshot is a decoded frame**: the hardware corrected a 3% bit error rate across 65,536 bits, bit for bit with the reference.

That also rules out a decoder that ignores its stored messages — one iteration alone leaves 2,912 broken checks, so matching iterations 3 and 6 means `T = L − R_old` is being reconstructed correctly from the compressed record.

### Cross-check against a second simulator

The same module and testbench were run in Verilator 5.052 before the Vivado run. The two agree on every reported event, to the picosecond:

| Event | xsim | Verilator |
|---|---|---|
| iteration 1 done | 128,716,000 | 128,716,000 |
| 6-iteration run, iteration 6 done | 1,254,540,000 | 1,254,540,000 |

Two independent simulators producing identical cycle counts and identical results means the RTL has no race or event-ordering dependence — the kind of bug that makes a design pass in one tool and fail in another.

## Synthesis (out-of-context, `xc7z020clg400-1`)

| Resource | Used | Device | % |
|---|---|---|---|
| Slice LUTs | 22,389 | 53,200 | **42.08** |
| Slice registers | 8,914 | 106,400 | 8.38 |
| Block RAM tiles | 72 (70 × RAMB36 + 4 × RAMB18) | 140 | **51.43** |
| LUT as memory | 0 | 17,400 | 0.00 |
| DSP | 0 | 220 | 0.00 |
| F7 muxes | 91 | 26,600 | 0.34 |

### Where the block RAM went

From the synthesis log's final mapping report:

| Memory | Shape | RAMB36 | RAMB18 | Tiles | Bits stored | Tile efficiency |
|---|---|---|---|---|---|---|
| `cn_mem` (check records) | 154 × 3,840 | 53 | 1 | **54** | 591,360 | 30% |
| `app_mem` (APP array) | 512 × 1,024 | 14 | 1 | 15 | 524,288 | 94% |
| `syn_mem` (syndrome) | 154 × 128 | 2 | 0 | 2 | 19,712 | 27% |
| Edge and layer-pointer ROMs | — | 1 | 2 | 2 | 36,864 | — |

**The check-message memory is three quarters of the block RAM and uses 30% of what it occupies.** This was predicted and accepted: 591,360 bits is 17 RAMB36 worth of *bits*, but the array is only 154 deep against a block's native 512 or 1,024, so most of each block is empty. The fix — eight lanes per entry, 240 bits × 2,464, about 21 tiles, at the cost of 16-cycle bursts in and out — is written up in [docs/stages/03 §3](../../docs/stages/03-iteration-loop.md) and deferred so that a stage-3 failure could not be in the burst logic.

Worth noting separately: **`LUT as memory` is 0.** The syndrome memory, which has an asynchronous read and would normally become distributed RAM, was inferred as block RAM instead. That is why the LUT count is purely logic.

### LUTs against the estimate

Predicted 16,000–20,000; measured 22,389. The overshoot is concentrated in two places that the stage-4 work can address:

1. **The `cn_mem` write multiplexer.** `cn_wdata` chooses between the new record and all-zeros during the clearing pass — 3,840 bits of 2:1 multiplexer, roughly 1,900 LUTs. It is avoidable: clear the per-lane registers instead and let `rec_w` be zero on its own during `S_CLEAR`.
2. **The per-lane `R_old` reconstruction**, which is the real cost of stage 3 and is not avoidable: 128 copies of a magnitude multiplexer, a 14-to-1 sign select on a variable index, a shift-add and a saturating subtract.

## Budget position

| | LUT | BRAM tiles |
|---|---|---|
| REQ-IMP-03 limit | 70% (37,240) | 80% (112) |
| Stage 3 now | 42.1% | 51.4% |
| Headroom | 14,851 LUT | 40 tiles |

Still inside, with the syndrome check (stage 4, roughly stage 1's 1,282 LUTs), the rate masks (stage 5, small) and then the AXI wrapper, verification hash and privacy amplification still to come. The `cn_mem` reshaping alone would return 33 tiles, which is most of what the rest of the system needs.

## Not yet measured

- **No timing numbers.** The synthesis log records `No constraint files found`, so there is no clock definition and nothing to report against: WNS and Fmax are both unknown. A constraints file is the first step of [stage 4](../../docs/stages/04-early-termination.md), because from here on the critical path is the real one — APP read → rotate → subtract `R_old` → compare → select → add → rotate → write.
- **The stage-2 rotator-sharing figure.** Stage 2 passed with the shared rotator but was not re-synthesised, so the before/after LUT pair in [stage 2's results](../stage2_layer_datapath/README.md) is still open. It is one *Set as Top* and one synthesis run away.

## Files

| File | Source |
|---|---|
| `ldpc_core_utilization_synth.rpt` | `vivado/ldpc_decoder/ldpc_decoder.runs/synth_1/` |
| `ldpc_core_simulate.log` | `vivado/ldpc_decoder/ldpc_decoder.sim/sim_1/behav/xsim/` |

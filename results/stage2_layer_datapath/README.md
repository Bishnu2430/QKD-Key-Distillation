# Stage 2 — one layer of the datapath: PASSED

| Field | Value |
|---|---|
| Built by | Bishnu, by hand in the Vivado GUI |
| Date | 16 Oct 2026 |
| Code | `v3_mother_1_r700` — n = 65,536, Z = 128, 154 layers, row degree 14 |
| Oracle | `tv/r700_q03_layers/` — per-layer APP snapshots from the bit-true L2 model |
| Tool | Vivado ML Standard 2025.2, `xc7z020clg400-1`, out-of-context |

## Functional result

```
layer 0: 0 lane mismatches
layer 1: 0 lane mismatches
STAGE 2 PASSED
```

Every one of the 65,536 APP values matches the bit-true model after layer 0, and again after layer 1 — including the 1,792 values layer 0 touches and the 1,664 that layer 1 touches.

## What this proves

The decoder's arithmetic core is bit-exact with the model:

1. **Lane-granular rotation** in both directions — forward to check order, inverse on write-back.
2. **Minimum finding** with strict comparison, so ties keep the first neighbour in increasing-column order.
3. **min2 routing** — the neighbour owning the minimum receives the second-smallest magnitude.
4. **Sign handling**, including the syndrome twist `(−1)^s` folded into the sign XOR.
5. **Normalisation** as `(v>>1)+(v>>2)`, truncating rather than rounding.
6. **Saturating addition** that clamps at ±127 and never wraps.

Those six are exactly the places where a decoder can be "nearly right" and silently lose a fraction of a decibel. Being bit-exact against the model means the FER curves measured in software describe this hardware.

## Synthesis (out-of-context, `xc7z020clg400-1`)

| Resource | Used | Device | % |
|---|---|---|---|
| Slice LUTs | 15,040 | 53,200 | **28.27** |
| Slice registers | 2,341 | 106,400 | 2.20 |
| Block RAM tiles | 18 (17 × RAMB36 + 2 × RAMB18) | 140 | 12.86 |
| DSP | 0 | 220 | 0.00 |
| Bonded IOB | 0 | 125 | 0.00 |

Compared with the [architecture estimate](../../docs/blocks/ldpc-decoder.md#11-resource-estimate) of 12–20k LUTs and 35–45 BRAM for the *whole* decoder:

- **LUTs are at the top of the predicted range for a single layer datapath.** The two 1,024-bit lane rotators dominate. The known optimisation — splitting `S_B_WR` into two states so one rotator serves both the read and the write-back — should remove a few thousand.
- **BRAM is as expected and inference now works.** The APP memory alone is 512 × 1,024 = 512 Kb ≈ 15 RAMB36; the syndrome memory, edge ROM and layer pointers account for the rest.
- **Registers match the per-lane state**: 128 lanes × (min1 7 + min2 7 + idx 4 + sign 1) = 2,432, close to the 2,341 observed after optimisation.

### What this implies for the full decoder

At 28% of the LUTs for the datapath alone, REQ-IMP-03 (≤ 70% LUT, ≤ 80% BRAM) is still reachable, but the margin is not generous. Stage 3 adds the check-message memory — roughly 19,712 checks × 30 bits ≈ 600 Kb, another 17 BRAM36 — which would put BRAM near 35 tiles, in line with the estimate. The rotator sharing is worth doing before the design grows further.

## Files

| File | Source |
|---|---|
| `layer_datapath_utilization_synth.rpt` | Copied from `vivado/ldpc_decoder/ldpc_decoder.runs/synth_1/` |

## Note on how this was reached

The first version of the reference module simulated correctly but failed synthesis with `[Synth 8-3391] Unable to infer a block/distributed RAM … 524288 bits is too large`: the APP array had two write ports and two read ports spread across two `always_ff` blocks, and block RAM has two ports in total. Restructuring to a single muxed read port and a single muxed write port, both in one `always_ff`, fixed it without changing any arithmetic — the simulation result was identical before and after.

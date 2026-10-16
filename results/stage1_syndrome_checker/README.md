# Stage 1 — syndrome checker: PASSED

| Field | Value |
|---|---|
| Built by | Bishnu, by hand in the Vivado GUI ([stages/01](../../docs/stages/01-syndrome-checker.md)) |
| Date | 16 Oct 2026 |
| Code | `v3_mother_1_r700` — n = 65,536, Z = 128, 154 layers, 2,048 base edges |
| Vectors | `tv/r700_q03/frames/000_*` (QBER 3%, all 20 frames decoded) |
| Tool | Vivado ML Standard 2025.2, `xc7z020clg400-1`, out-of-context |

## Functional result

```
clean  : match=1 bad_layers=0
flipped: match=0 bad_layers=8
STAGE 1 PASSED
```

A valid decoded word satisfies all 154 layers; flipping one bit breaks 8 of them, which is the expected order (a variable of degree 3–8 sits in that many checks, and the lifted graph spreads them across layers).

## What this proves

1. The edge-ROM packing `{shift[6:0], column[8:0]}` is read correctly.
2. The address arithmetic `var = c·Z + ((i + shift) mod Z)` is implemented correctly — the rotation `dbl[k +: Z]` matches the spec's convention.
3. The layer walk covers all 154 layers using `layer_ptr`.
4. `$readmemh` resolves the generated `.mem` files by bare filename inside the project.
5. The 64-bit hex vector format (LSB-first within a word) assembles correctly into 128-bit column words.

## Synthesis (out-of-context, `xc7z020clg400-1`)

| Resource | Used | Device | % |
|---|---|---|---|
| Slice LUTs | 1,282 | 53,200 | 2.41 |
| Slice registers | 195 | 106,400 | 0.18 |
| Block RAM tiles | 4 (3 × RAMB36 + 2 × RAMB18) | 140 | 2.86 |
| DSP | 0 | 220 | 0.00 |
| Bonded IOB | **0** | 125 | 0.00 |

Reading those numbers:

- **BRAM is as expected.** `xhat_mem` is 512 × 128 = 65,536 bits (2 × RAMB36), `syn_mem` is 154 × 128 = 19,712 bits, `edge_rom` is 2,048 × 16 = 32,768 bits, and the layer pointers are small. Everything inferred as block memory — no accidental LUT RAM.
- **The LUTs are mostly the rotator.** A 128-bit rotate by a 7-bit amount is a seven-stage mux tree; that and the 128-bit XOR and compare account for most of the 1,282.
- **IOB = 0** confirms out-of-context synthesis was active.
- No timing data yet: implementation was not run, and at this size it would not be informative.

## Files

| File | Source |
|---|---|
| `syndrome_checker_utilization_synth.rpt` | Copied from `vivado/ldpc_decoder/ldpc_decoder.runs/synth_1/` |

## Notes for later stages

The rotator synthesised here is the same structure the full decoder needs, except 8 bits wide per lane instead of 1 (1,024-bit words rather than 128-bit). Expect roughly 8× the LUTs for that block, which is consistent with the 2–4k LUT estimate in [blocks/ldpc-decoder §11](../../docs/blocks/ldpc-decoder.md#11-resource-estimate).

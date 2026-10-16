# Decoder Bring-Up — Overview

| Tool | Vivado ML Standard 2025.2, part `xc7z020clg400-1` |
|---|---|
| Prerequisite | The week-1 flow test in [15-vivado-gui-guide](../15-vivado-gui-guide.md) |
| Target | [`blocks/ldpc-decoder`](../blocks/ldpc-decoder.md) micro-architecture, [spec §3.6](../05-algorithm-spec.md#36-decoding-layered-normalized-min-sum-l2-bit-true) |

> **You do every Vivado step by hand.** These documents give the complete RTL, the complete testbench and every click. Claude generates the code memories and the test vectors, explains failures, and records results. Claude does not create your project, your RTL or your runs.

---

## Why staged

A 65,536-bit decoder that "doesn't work" is almost impossible to diagnose from the outside. Each stage below ends in a simulation that passes or fails against bit-exact vectors from the reference model, so a bug is localised to the thing you just added.

| Stage | What you build | What it proves | Document |
|---|---|---|---|
| **1** | Syndrome checker | Edge ROM format, the address arithmetic `c·Z + ((i+shift) mod Z)`, the layer walk | [01-syndrome-checker](01-syndrome-checker.md) |
| **2** | One layer of datapath | APP memory, cyclic shifter, subtract, check-node minimum-finder, normalisation, write-back | *next* |
| **3** | Full iteration loop | The controller, iteration counting, decoded output | — |
| **4** | Early termination and status | Stopping at the iteration boundary; `ok` / `iterations` match the model exactly | — |
| **5** | Rate masks | LLR initialisation for punctured and shortened positions | — |

Stage 1 is written in full. Each later stage is written when you reach it, because its structure depends on choices you make in the one before (pipeline depth, memory banking) — and a document written against guesses would be worth less than one written against your actual stage-2 code.

---

## The code this uses

Three mother codes exist ([results/m3_code_design_v3](../../results/m3_code_design_v3/README.md)); bring-up uses `v3_mother_1_r700`, the middle one.

| | `v3_mother_0_r850` | `v3_mother_1_r700` | `v3_mother_2_r400` |
|---|---|---|---|
| Serves | Q = 1–2% | **Q = 3–6%** | Q = 8% |
| Layers `M_B` | 77 | **154** | 307 |
| Syndrome bits | 9,856 | **19,712** | 39,296 |
| `MAX_ROW_DEG` | **27** | 14 | 7 |

All three share `N_BITS` = 65,536, `Z` = 128, `N_B` = 512, `N_EDGES` = 2,048, `EDGE_BITS` = 16.

**Size the check-node minimum-finder for 27**, the widest row across the set, so one datapath serves all three codes. Everything else comes from the `.svh`.

---

## Files Claude generates for you

Both commands run in WSL from the repository root. Neither touches Vivado.

**Code memories** — the parity-check matrix, as `.mem` plus a SystemVerilog header:

```bash
uv run python scripts/export_code_mem.py --code codes/v3_mother_1_r700.npz --out rtl/gen
```

Already generated and committed. **These are inputs, not build products** — Vivado never creates them.

**Test vectors** — bit-exact expectations from the L2 model:

```bash
uv run python scripts/export_test_vectors.py --code codes/v3_mother_1_r700.npz \
    --qber 0.05 --frames 20 --out tv/r700_q05
```

| File | Contents |
|---|---|
| `frames/NNN_y.hex` | Bob's received key bits |
| `frames/NNN_syndrome.hex` | Alice's syndrome |
| `frames/NNN_xhat.hex` | Expected decoded bits |
| `expected.csv` | Per frame: `ok`, `iterations`, channel amplitude `A` |
| `meta.json` | Code shape, mask, fixed-point configuration, seeds |

All hex files are **one 64-bit word per line, LSB-first inside the word** ([spec §2](../05-algorithm-spec.md#2-conventions)). Use the same order in the testbench or everything mismatches for a trivial reason.

---

## Project setup (once)

1. **Create Project** → name `ldpc_decoder`, location `D:/QKD-Key-Distillation/vivado`, **RTL Project**, *do not specify sources*, part **`xc7z020clg400-1`**.
2. *Tools → Settings → Project Settings → General*: Target language **Verilog**, Simulator language **Mixed**.
3. *Settings → Synthesis → More Options*: `-mode out_of_context`.
4. **Add Sources → Add or create design sources → Add Directories** → `D:/QKD-Key-Distillation/rtl`.
5. **Add Sources → Add or create simulation sources → Add Directories** → `D:/QKD-Key-Distillation/tb`.
6. **Add the generated files separately**: *Add Sources → Add or create design sources → Add Files*, file filter **All Files**, pick `rtl/gen/v3_mother_1_r700_params.svh`, `_edges.mem`, `_layer_ptr.mem`, and **untick "Copy sources into project"**.

Step 6 is separate because *Add Directories* takes a snapshot at the moment you add it and its filter excludes `.mem`. The `.svh` lands in the Verilog-header group and the `.mem` files under *Design Sources → Non-module Files*; both are correct.

---

## Reporting back

After each stage send: the console output, and for failures the symptom plus the values of the state and counters at the first divergence. Claude will re-run that exact frame in the model and hand back the per-layer values to compare against.

# 16 — Vivado Guide: Building the LDPC Decoder

| Version | 0.1, 12 Oct 2026 |
|---|---|
| Tool | Vivado ML Standard 2025.2, part `xc7z020clg400-1` |
| Prerequisite | The week-1 flow test in [15-vivado-gui-guide](15-vivado-gui-guide.md) |
| Implements | [blocks/ldpc-decoder](blocks/ldpc-decoder.md) micro-architecture, [05-algorithm-spec §3.6](05-algorithm-spec.md#36-decoding-layered-normalized-min-sum-l2-bit-true) |

> **The rule stands.** You do every Vivado step by hand. Claude supplies the specification, the reference models, the generated code memories and the test vectors, and reads the numbers you report. Claude does not create your Vivado project, your RTL or your runs.

This is a staged bring-up: five stages, each one simulating against test vectors before the next begins. Do not write the whole decoder and then debug it — a 65,536-bit decoder that "doesn't work" is almost impossible to diagnose from the outside.

---

## 1. What you are building

A layered normalized min-sum **syndrome** decoder: one frame in, corrected key bits out. Per iteration it walks the layers (block rows) of the code; per layer it reads the a-posteriori LLRs of the connected variables, rotates them into place, subtracts the old check message, finds the two smallest magnitudes, writes the new messages back, and updates the LLRs in place. After each full iteration it checks whether the hard decisions satisfy Alice's syndrome, and stops when they do.

The micro-architecture, memory sizes and port list are in [blocks/ldpc-decoder](blocks/ldpc-decoder.md). Read that first; this document is the *procedure*, not the design.

---

## 2. Files I generate for you

Run these in WSL from the repository root. They write into the repo; you then add them to your Vivado project.

**Code memories and parameters** (from the M3 mother codes):

```bash
uv run python scripts/export_code_mem.py --code codes/v3_mother_1_r700.npz --out rtl/gen
```

> **These files are inputs, not build products.** Vivado never generates them: they carry the parity-check matrix from the code design into your RTL. Regenerate them only when the code changes, and keep them in the repository alongside the sources.

Produces, for each code:

| File | Contents | Use in Vivado |
|---|---|---|
| `<name>_params.svh` | `N_B`, `M_B`, `Z`, `N_BITS`, `M_BITS`, `N_EDGES`, `COL_BITS`, `SHIFT_BITS`, `EDGE_BITS`, `MAX_ROW_DEG` | `` `include `` it in your RTL |
| `<name>_edges.mem` | One hex word per base-matrix entry: `{shift, column}`, in layer order then increasing column | `$readmemh` into the edge ROM |
| `<name>_layer_ptr.mem` | First edge index of each layer | `$readmemh` into the layer-pointer ROM |
| `<name>_edges.coe` | The same edge list for the Block Memory Generator | If you use the IP instead of inference |

The three M3 mother codes ([results/m3_code_design_v3](../results/m3_code_design_v3/README.md)), all at `N_BITS` = 65,536, `Z` = 128, `N_B` = 512, `N_EDGES` = 2,048, `EDGE_BITS` = 16:

| Code | serves | `M_B` (layers) | `M_BITS` (syndrome) | `MAX_ROW_DEG` |
|---|---|---|---|---|
| `v3_mother_0_r850` | Q = 1–2% | 77 | 9,856 | **27** |
| `v3_mother_1_r700` | Q = 3–6% | 154 | 19,712 | 14 |
| `v3_mother_2_r400` | Q = 8% | 307 | 39,296 | 7 |

**Size the check-node unit's serial minimum-finder for `MAX_ROW_DEG` = 27**, the widest row across the three codes, so one datapath serves all of them. Everything else is parameterised by the `.svh`.

**Test vectors** (bit-exact expectations from the L2 model):

```bash
uv run python scripts/export_test_vectors.py --code codes/mother_low.npz \
    --qber 0.05 --frames 20 --out tv/low_q05
```

| File | Contents |
|---|---|
| `meta.json` | Code shape, mask, fixed-point configuration, channel amplitude `A`, seeds |
| `base_matrix.txt` | The base matrix, one row per line, `-1` for a zero block |
| `frames/NNN_y.hex` | Bob's received key bits |
| `frames/NNN_syndrome.hex` | Alice's syndrome |
| `frames/NNN_xhat.hex` | **Expected** decoded key bits |
| `expected.csv` | Per frame: `ok`, `iterations`, `amplitude`, `errors_in` |

Hex files are one 64-bit word per line, 16 digits, **LSB-first within the word** ([spec §2](05-algorithm-spec.md#2-conventions)). Your testbench must use the same order or everything will look wrong for a trivial reason.

---

## 3. Project setup

1. **Create Project** → name `ldpc_decoder`, location `D:/QKD-Key-Distillation/vivado`, **RTL Project**, *do not specify sources*, part **`xc7z020clg400-1`**.
2. *Tools → Settings → Project Settings → General*: target language Verilog, simulator language Mixed.
3. *Settings → Synthesis → More Options*: `-mode out_of_context` (the decoder has far more ports than the package has pins).
4. **Add Sources → Add or create design sources → Add Directories**: add `D:/QKD-Key-Distillation/rtl`. This picks up your `.sv` files.
5. **Add Sources → Add or create simulation sources**: add `D:/QKD-Key-Distillation/tb`.

### 3.1 Adding the generated files (they need their own pass)

*Add Directories* will **not** bring in the `.mem` and `.svh` files, for two reasons that bite independently:

- **It is a snapshot.** Vivado records the files present when you add the directory and never looks again. Anything generated afterwards is invisible until you add it.
- **The file filter excludes them.** The dialog defaults to HDL extensions, and `.mem` is not one.

So add them explicitly:

1. **Add Sources → Add or create design sources → Next → Add Files**.
2. Set the file-type dropdown to **All Files**.
3. Select, from `rtl/gen`, the three files for the code you are working on, for example `v3_mother_1_r700_params.svh`, `v3_mother_1_r700_edges.mem`, `v3_mother_1_r700_layer_ptr.mem`.
4. **Leave "Copy sources into project" unticked** — the project should reference the repository copies, so regenerating a code takes effect without re-adding anything.
5. **Finish**.

**Where they appear, and why that is correct:** the `.svh` is classified as a Verilog header, so it sits in its own group and stays out of the Hierarchy view until something `` `include ``s it. The `.mem` files land under *Design Sources → Non-module Files*. Both are right. What matters is that they are in the project, which is what makes `$readmemh("v3_mother_1_r700_edges.mem", rom)` resolve by bare filename in simulation **and** synthesis. An absolute path works in simulation and often fails in synthesis.

**After regenerating a code:** if the filenames are unchanged, nothing to do — the project points at the files on disk. If a filename changes (a different mother code), repeat this section for the new files and remove the stale ones.

---

## 4. Bring-up, stage by stage

Each stage ends with a simulation you can pass or fail. Do not move on from a failing stage.

### Stage 1 — syndrome checker
**Build:** a module that reads the edge ROM and layer-pointer ROM, walks every layer, computes the parity of the connected hard-decision bits, and compares against the syndrome.

**Why first:** it exercises the memory format, the address arithmetic `var = col*Z + ((z + shift) mod Z)` and the layer walk — the three things that break first — with no LLR arithmetic in the way.

**Simulate:** feed `frames/000_xhat.hex` as the hard decisions and `frames/000_syndrome.hex` as the syndrome. For a frame whose `expected.csv` says `ok=1`, the checker must report *match*. Flip one bit of the input and it must report *mismatch*.

### Stage 2 — one layer of the datapath
**Build:** APP memory, the cyclic shifter, the subtractor, the check-node unit (min1/min2/index/sign tracking), the normalisation `(v>>1)+(v>>2)`, and the write-back.

**Simulate:** this is where a **debug dump** pays for itself. Ask me for a per-layer APP dump from the L2 model for one frame; compare your RTL's APP memory against it after layer 0, then after layer 1. A mismatch at layer 0 is an addressing or initialisation bug; a mismatch that appears later is usually the message memory.

**Watch for:** saturation (every sum clamps to ±127 with `W_APP=8`), tie-breaking (the *first* minimum in increasing-column order wins), and sign handling (`sign(0) = +1`).

### Stage 3 — full iteration loop
**Build:** the controller that repeats stage 2 over all layers, counts iterations, and stops at `i_max`.

**Simulate:** run a frame from `tv/` to completion. Compare the decoded key bits against `frames/NNN_xhat.hex` and the iteration count against `expected.csv`. **Both must match exactly** — the iteration count is a strong signal: if the bits match but the count differs, your early-termination or scheduling differs from the spec.

### Stage 4 — early termination and status
**Build:** run the stage-1 checker at each iteration boundary (not mid-iteration — [spec §3.6](05-algorithm-spec.md#36-decoding-layered-normalized-min-sum-l2-bit-true) requires it) and output `ok`, `iterations`, `busy`.

**Simulate:** the full 20-frame vector set. Every frame must match on bits, iteration count and `ok` flag.

### Stage 5 — rate masks
**Build:** LLR initialisation from the mask: key positions `±A`, punctured `0`, shortened `+127`.

**Simulate:** regenerate vectors with puncturing and shortening and repeat stage 4:

```bash
uv run python scripts/export_test_vectors.py --code codes/mother_high.npz \
    --qber 0.02 --frames 20 --puncture-cols 40 --out tv/high_q02_p40
```

---

## 5. Memories: inference or IP?

| Memory | Size | Recommendation |
|---|---|---|
| APP LLRs | `N_B` words × (`Z` × `W_APP`) bits | **Infer** it: a simple `logic [W-1:0] mem [DEPTH]` with a registered read, exactly as in the week-1 core. Inference keeps the design portable and the code readable |
| Check-node state | `M_BITS` entries × (2 × `W_MSG` + index + signs) | **Infer** |
| Edge ROM / layer pointers | `N_EDGES` × `EDGE_BITS` | **Infer** with `$readmemh` in an `initial` block — Vivado synthesises that into a ROM |
| Frame buffers (later) | `N_BITS` + `M_BITS` bits | Infer, or use an AXI-Stream FIFO |

Use the **Block Memory Generator** IP only if inference gives you the wrong shape — for example if you need a true dual-port memory with different widths per port. To add it: *IP Catalog → Memory & Storage Elements → Block Memory Generator*, set the port widths and depth, load the `.coe` under *Other Options → Load Init File*, then instantiate it from your RTL. The downside is that the IP is tool-specific, so Verilator cannot simulate it — and the bit-exact regression runs in Verilator.

> **Rule of thumb for this project: infer everything that must be simulated in Verilator.** That is the whole datapath.

---

## 6. Simulating against the test vectors

In SystemVerilog, read the hex files into arrays:

```systemverilog
logic [63:0] y_words   [0:(N_KEY+63)/64-1];
logic [63:0] syn_words [0:(M_BITS+63)/64-1];
initial begin
  $readmemh("tv/low_q05/frames/000_y.hex", y_words);
  $readmemh("tv/low_q05/frames/000_syndrome.hex", syn_words);
end
```

Bit `j` of a vector is `words[j/64][j%64]` — LSB-first, matching [spec §2](05-algorithm-spec.md#2-conventions). Drive those into the DUT, then compare the output against `000_xhat.hex` word by word and the iteration count against `expected.csv`.

**When a frame mismatches**, report to me: the frame number, the first mismatching bit index, your iteration count against the expected one, and the vector directory. I can re-run that exact frame in the model and give you the per-layer APP values to compare.

---

## 7. Synthesis, implementation and reports

Exactly as in [15 §5–§7](15-vivado-gui-guide.md#5-run-synthesis): run synthesis, check messages and BRAM inference, run implementation, read WNS and utilisation, copy the reports into `results/` with a `result.yaml`.

**Expectations for a first pass** (from the model's estimates in [07 §5.1](07-hw-architecture.md#51-working-estimate-from-the-learning-guide-16); treat as a sanity range, not a target):

| Quantity | Ballpark |
|---|---|
| LUTs | 12–20k (23–38% of the device) |
| BRAM36 | 35–45 (25–32%) |
| DSP | 0 |
| Fmax | ≥ 125 MHz; the first attempt often lands lower |

If your first implementation is far outside this, stop and tell me the numbers before optimising — it usually means a structural difference from the intended micro-architecture, not a tuning problem.

---

## 8. Timing-closure playbook for this design

The week-1 test already showed the shape of the problem: the critical path ran **block RAM output → logic → register**, with zero logic levels. In the decoder the same memories carry real arithmetic behind them, so expect the critical path to be one of these:

| Likely critical path | Fix |
|---|---|
| APP memory read → subtract → magnitude → min-finder | Register the memory output, and pipeline the min-finder into compare and select stages |
| Cyclic shifter (7 stages for Z = 128) | Pipeline the barrel shifter; it is a pure permutation, so stages are free to insert |
| Min-finder over a long row (up to `MAX_ROW_DEG` neighbours) | Process neighbours serially with a running min1/min2 — the standard trick, and it is what the model's tie-breaking assumes |
| Syndrome checker fan-in | Compute the parity incrementally during the layer walk rather than in one wide XOR |

Pipelining changes *when* values appear, never *what* they are — the bit-exact comparison against the model must still pass after every pipeline change. That is exactly what the test vectors are for.

---

## 9. Pitfalls specific to this design

| Symptom | Cause |
|---|---|
| Everything decodes in 1 iteration and `ok` is always high | The syndrome checker is comparing against itself; check you feed Alice's syndrome, not a recomputed one |
| Bits match but iteration count is one higher | Early termination evaluated mid-iteration instead of at the boundary |
| First frame passes, later frames fail | Check-node or APP memory not cleared between frames |
| Off-by-one across a layer boundary | `(z + shift) mod Z` applied with the wrong operand order — compare against `base_matrix.txt` |
| Results differ from the model only at high QBER | Saturation: a sum is wrapping instead of clamping |
| BRAM inference fails on the APP memory | Read-modify-write in one cycle; register the read and write in the following cycle |
| Verilator passes, Vivado simulation differs | Uninitialised memory; Verilator zeroes arrays, Vivado uses X |

---

## 10. What to send me after each stage

1. Stage number and whether the vector set passed.
2. For failures: frame number, first mismatching bit, your iteration count against expected.
3. After implementation: WNS, Fmax, LUT/FF/BRAM/DSP, and the power estimate.
4. Anything in the message log you do not recognise.

I will record the numbers in [results/](../results/), update [blocks/ldpc-decoder](blocks/ldpc-decoder.md), and generate whatever extra vectors or model dumps the next stage needs.

# Project File Index

Every file in the repository: what it is for, and the part of it that matters. Updated 16 Oct 2026.

**If you are looking for…**

| …this | go to |
|---|---|
| How the algorithm must behave, exactly | [`docs/05-algorithm-spec.md`](05-algorithm-spec.md) |
| How to build something in Vivado | [`docs/stages/`](stages/) — one document per bring-up stage, with complete RTL and every click |
| The reference implementation of a stage | `model/*.py` — each module names the spec section it implements |
| Why a choice was made | [`docs/14-rationale.md`](14-rationale.md) and [`docs/decisions/`](decisions/) |
| A measured result | `results/<experiment>/README.md` |
| The code the decoder uses | `codes/v3_mother_*.npz` → generated into `rtl/gen/` |

---

## Top level

| File | Purpose | Focus point |
|---|---|---|
| `README.md` | Entry point: what the project is, the document map, repository layout | The document table — it is the index to everything |
| `pyproject.toml` | uv project: dependencies, test configuration | `[project.optional-dependencies] sim` holds cocotb and pytest, so model work does not drag in the RTL tooling |
| `uv.lock` | Exact resolved versions of every Python package | Commit it; it is what makes the Python side reproducible |
| `.gitignore` | Keeps build artefacts out of git | `vivado/` — Vivado projects are regenerable and churn constantly |

---

## `model/` — the reference models

The L1 (floating point) and L2 (bit-true) implementations of the spec. Every module states the spec section it implements; if code and spec disagree, the spec wins.

| File | Purpose | Focus point |
|---|---|---|
| `__init__.py` | Package docstring and the module map | Read this first — it is the two-paragraph tour of the model |
| `bits.py` | Bit ordering and 64-bit packing (spec §2) | `pack_words` / `unpack_words`: **LSB-first within each word**. Every hex file and every RTL interface depends on this one convention |
| `info.py` | Entropy and rate arithmetic | `h(p)`, `efficiency(leak, n_key, qber)`, `effective_rate(r0, pi, sigma)` — the Elkouss rate formula for puncturing and shortening |
| `code.py` | QC-LDPC representation, syndrome, rate masks (spec §3.1–3.3, 3.5) | `QCCode.variables_of_layer(r)` is the address arithmetic `c*Z + ((i + shift) mod Z)` the RTL must reproduce. `RateMask.leakage_bits` is the `m − p` accounting |
| `frame.py` | Alice's word, BSC channel, Bob's initial LLRs (spec §3.3–3.4) | `build_alice_word`: key bits, **private random** fill at punctured positions, zeros at shortened ones. Getting the fill wrong breaks the leakage argument, not just the decoder |
| `decoder.py` | L1 float layered normalized min-sum (spec §3.6–3.7) | `_check_update_minsum`: `np.argmin` picks the **first** minimum — that is the tie-break rule the RTL must copy |
| `fixed.py` | **L2 bit-true model** — the oracle for the RTL (spec §2.1, 3.4, 3.6) | `normalise()` is `(v>>1)+(v>>2)`, truncating, not rounding; `saturate()` clamps, never wraps. These two make it bit-exact rather than approximately right |
| `fast.py` | Numba kernels, bit-exact with `decoder.py` and `fixed.py` | `_decode_fixed_kernel` — the scalar loop. 5–21× faster; `tests/test_fast.py` enforces exact equality, which is what licenses using it for published curves |
| `hashing.py` | Toeplitz verification tag and privacy amplification (spec §4–5) | Two implementations: `window` (the oracle) and `kronecker` (big-integer multiply, the only practical one past 10⁵ bits). They must agree bit for bit |
| `pipeline.py` | Frame and block processing, leakage accounting, `measure()` | `measure()` is the unit every sweep calls. `backend="float"|"fixed"` picks the model level; `leak_below_limit` flags an accounting error |
| `de.py` | Density evolution for normalized min-sum on the BSC | `check_update` — the **exact** (sign, magnitude) formulation: `U = T₊+T₋`, `D = T₊−T₋`, outgoing tails `(U^d ± D^d)/2`. The naive independence shortcut gave thresholds above the Shannon limit |
| `peg.py` | Progressive edge growth construction | `peg_adjacency` places each edge into the check furthest from the variable; `degrees_from_profile(heavy_first=True)` puts heavy columns at the front so masks have a contiguous puncturable region |
| `rank.py` | GF(2) rank of punctured columns | `columns_are_independent` decides whether `leak = m − p` is licensed or the conservative `leak = m` applies. Bit-packed elimination in Numba |
| `keyrate.py` | Channel model, asymptotic decoy rate, finite-key estimate | `asymptotic_rate` is quotable; `finite_key_length` returns `provisional=True` because the ε bookkeeping of arXiv:2405.16578v3 Eq. (121) is **not** transcribed |
| `sweeps.py` | Parallel driver for measurement points | `run_points(points, workers)` — 12 points take 6.4 s on one core, 1.2 s on eleven |

---

## `scripts/` — experiments and generators

Each writes into `results/` with a header recording the commit, parameters and seed (REQ-REP-01).

### Generators (these feed the RTL)

| File | Produces | Focus point |
|---|---|---|
| `export_code_mem.py` | `rtl/gen/<code>_edges.mem`, `_layer_ptr.mem`, `_edges.coe`, `_params.svh` | Packs each base-matrix entry as `{shift[6:0], column[8:0]}`. **These are inputs to Vivado, never outputs of it** |
| `export_test_vectors.py` | `tv/<name>/` — frames, syndromes, expected outputs, `expected.csv`, `mask.mem` | Bit-exact expectations from the L2 model. This is the Python↔SystemVerilog handover. `mask.mem` is one digit per base column (0 key, 1 punctured, 2 shortened), which is what the RTL's mask memory loads |
| `export_layer_dump.py` | `tv/<name>/app_init.hex`, `app_after_lNNN.hex` (per layer, stage 2) or `app_after_iNNN.hex` (per iteration, stage 3), `syndrome.hex` | Snapshots of the whole APP array so a mismatch localises to one layer or one iteration. `meta.json` also records unsatisfied checks per snapshot — the convergence trace the RTL must reproduce |

### Experiments

| File | Experiment | Focus point |
|---|---|---|
| `sweep_e1.py` | E1: FER and efficiency against QBER | The first sweep that showed a fixed-rate code leaking 4.3× the minimum at 1% QBER |
| `sweep_e3.py` | E3: the mask rate and I_max against throughput, latency, energy and secret key rate | Puts the model's iteration counts through the *implemented* decoder's cycle model, so the throughput column describes real hardware |
| `sweep_c1.py` | C1: which mask covers which QBER | Selects the lowest-leakage mask meeting a FER target — the choice the PS makes at run time |
| `probe_puncturing.py` | Does puncturing high-degree columns help? | It helps inside a 10% budget and backfires beyond it |
| `sweep_e2.py` | E2: quantisation study | Compares every fixed-point configuration against the float model on identical frames |
| `sweep_e5.py` | E5: secret key rate against distance | Shows efficiency deciding the maximum range |
| `bench_decoder.py` | Decoder throughput, reference against Numba | Reports hours per 10⁵ frames — the number that decides whether a sweep is affordable |

### Code design (three passes, each kept because each taught something)

| File | Pass | Why it is still here |
|---|---|---|
| `design_codes.py` | v1: masks built for a target efficiency | Records the failure that proves efficiency is an outcome, not an input |
| `design_codes2.py` | v2: rates driven by the DE threshold | Computes the threshold curve that `design_codes3.py` reuses |
| `design_codes3.py` | **v3: mother code at the top of its range** | The current design. `choose_mother_rates()` implements the rule |

---

## `tests/` — 82 tests

| File | Guards | Focus point |
|---|---|---|
| `test_model.py` | Bit packing, entropy, code structure, masks, decoder, hashing, pipeline | Contains the **documented worked examples**: the Toeplitz `10110`/`1101` → `01` case and the GF(2) product. A doc change that breaks behaviour fails here |
| `test_fixed.py` | The L2 model | `test_alpha_is_a_sum_of_shifts` and `test_channel_amplitude_table` pin the arithmetic the RTL must match |
| `test_fast.py` | Numba kernels equal the reference | Exact equality of bits, iteration counts and final LLRs — the licence to use the fast path |
| `test_de.py` | Density evolution | `test_threshold_is_below_the_shannon_limit` — the canary that caught the independence-approximation bug |
| `test_peg_rank.py` | PEG construction and rank checking | No 4-cycles in the lifted graph; duplicate columns are detected as dependent |
| `test_keyrate.py` | Channel and key-rate model | `test_finite_key_is_flagged_provisional` keeps the unverified part honest |
| `test_sweeps.py` | Parallel driver | Parallel results equal serial results |

---

## `docs/` — specification and guides

### Core specification

| File | Purpose | Focus point |
|---|---|---|
| `00-learning-guide.md` | Every concept used in the project, with worked examples and self-checks | 21 chapters, five parts. Start here if the theory is unfamiliar |
| `01-charter.md` | Problem, research questions, contributions C1–C5, scope, timeline, risks | §3 contributions and §6 success criteria |
| `02-related-work.md` + `related-work.csv` | Prior art and the gap statement | The gap statement in §5 is what the paper's introduction argues |
| `03-requirements.md` | ~40 numbered testable targets | REQ-PERF-01 (efficiency) is currently **not met** — the row records the measured 1.29–1.56 |
| `04-system-model.md` | Protocol, channel, security assumptions, notation | §5 key-length formula and the notation table everything else uses |
| `05-algorithm-spec.md` | **Bit-exact behaviour** of every stage | §3.6 decoder pseudocode and §2.1 fixed-point parameters. This is the contract between model and RTL |
| `06-ldpc-code-design.md` | The code design (contribution C1) | The design rule, the threshold curve, and the three mother codes |
| `07-hw-architecture.md` | PS/PL split, dataflow, budgets | The partition rationale: per-bit work in fabric, per-block decisions in software |
| `08-interfaces-regmap.md` | AXI4-Stream frame formats, AXI4-Lite registers | Proposed register map; freeze at M4 |

### Plans

| File | Purpose | Focus point |
|---|---|---|
| `10-verification-plan.md` | The L1–L6 ladder, tests mapped to requirements | Why FER curves come from L2 rather than RTL simulation |
| `11-evaluation-plan.md` | Experiments E1–E7, metric definitions | Metrics are defined **before** measurement, so they cannot be chosen to flatter |
| `12-toolflow.md` | Environment, pinned versions, reproducibility | §4 version pins; the Verilator build recipe (apt's 5.020 is too old for cocotb) |
| `13-rtl-coding-guidelines.md` | SystemVerilog conventions | Reset style, naming, saturation helper, lint rule |
| `14-rationale.md` | Problem, solution, **reason for every choice**, methodology | §4 is the decision log in prose; §6 is the threats to validity |

### Vivado guides (you drive; nothing here is run by Claude)

These live on disk but are **not tracked in git** (see "Not in git" below).

| File | Purpose | Focus point |
|---|---|---|
| `stages/00-overview.md` | The decoder bring-up: what each stage delivers, project setup once | The staging order and why it is that order |
| `stages/01-syndrome-checker.md` | **Stage 1, complete**: full RTL, full testbench, every click | The rotation function `dbl[k +: Z]` — get it backwards and every layer mismatches |
| `stages/02-layer-datapath.md` | **Stage 2, complete**: the arithmetic core, plus the rotator-sharing optimisation in step 7 | The APP memory needs exactly one read and one write port, or synthesis cannot infer block RAM |
| `stages/03-iteration-loop.md` | **Stage 3, complete**: the check-message memory and the iteration loop | The compressed record (min1, min2, idx, one sign bit per edge) is a *lossless* encoding of every message a layer sent, in a quarter of the bits |
| `stages/09-power-saif.md` | **Stage 9**: capture switching activity from the implemented netlist and report power from it | `Simulation Activity File ---` in a power report means Vivado guessed the toggle rates |
| `stages/08-split-arithmetic.md` | **Stage 8**: R_old reconstructed beside the rotate, T registered | Everything `pos` feeds can be computed a cycle early — the record and the syndrome are fixed for the whole layer |
| `stages/07-pipelined-walk.md` | **Stage 7**: the pipelined edge walk, one edge per clock | Two rotators again — in a pipeline the forward rotate of edge k+2 and the inverse rotate of edge k land in the same cycle, so stage 2's sharing has to be undone |
| `stages/06-timing-fixes.md` | **Stage 6**: the block RAM output register and the rotator register, measured separately | A block RAM's output register only merges when two registers sit in series on the read path |
| `stages/05-rate-masks.md` | **Stage 5, complete**: the loader, mask memory and key memory | The key stream is indexed by key position, not by variable — the key-column counter advances only on key columns |
| `stages/04-early-termination.md` | **Stage 4, complete**: the syndrome check in the loop, status outputs, and the first clock constraint | The check must be its own pass over the edges — a layer's parity is only meaningful once every variable it touches has its final value for the iteration |

### Blocks, decisions, log

| File | Purpose |
|---|---|
| `blocks/ldpc-decoder.md` | Decoder micro-architecture: ports, datapath, memory geometry, hazards, throughput model |
| `blocks/verify-hash.md` | Verification tag block (M6) |
| `blocks/privacy-amp.md` | Privacy amplification block (M6), with the method comparison |
| `decisions/ADR-001…006` | One file per major decision: docs format, Vivado version, LDPC over Cascade/polar, security parameters, SystemVerilog, target device |
| `decisions/ADR-000-template.md` | Template for the next one |
| `log/2026-W39…W42.md` | Weekly notes: done, decided, next |
| `FILES.md` | This file |

---

## `rtl/` — hardware sources

| File | Purpose | Focus point |
|---|---|---|
| `axis_smoke.sv` | Week-1 flow test: AXI4-Stream FIFO with an XOR checksum | Not part of the accelerator. It proved BRAM inference, handshake correctness and timing closure |
| `syndrome_checker.sv` | **Bring-up stage 1**: walks the edge list and checks a word against a syndrome | The address arithmetic `c·Z + ((i+shift) mod Z)`, in its simplest possible setting |
| `layer_datapath.sv` | **Bring-up stage 2**: one layer of the decoder, first-iteration semantics | One lane rotator shared between the read and the write-back, which is why `S_B_WR` is split in two |
| `ldpc_core.sv` | **Bring-up stage 3**: the check-record memory and the iteration loop | `cn_mem` is 154 × 3,840 bits and needs `ram_style = "block"`, or it becomes LUT RAM and eats the device |
| `ldpc_decoder.sv` | **Bring-up stage 4**: the decoder, with early termination and status | The syndrome check is its own pass over the edges — a layer's parity only means something once the iteration is finished |
| `ldpc_decoder_deep.sv` | **Bring-up stage 8**: the arithmetic stage split in three. The version that meets 125 MHz | R_old is reconstructed beside the rotate, not after it, because the record and the syndrome are fixed for the whole layer |
| `ldpc_decoder_pipe.sv` | **Bring-up stage 7**: the pipelined decoder, one edge issued per clock | Two rotators, because the forward rotate of one edge and the inverse rotate of another now fall in the same cycle. The c4 arithmetic stage is the remaining critical path |
| `ldpc_decoder_rate.sv` | **Bring-up stages 5 and 6**: the mask-aware loader, plus the block RAM and rotator output registers | Punctured positions start at 0, shortened at +127, key positions at ±A — and only key columns consume key bits |
| `gen/*_params.svh` | Generated SystemVerilog parameters per code | `MAX_ROW_DEG` differs per code: 27 / 14 / 7. Size the CNU for 27 |
| `gen/*_edges.mem` | Generated edge list, 2,048 words of `{shift, column}` | Read with `$readmemh` by bare filename |
| `gen/*_layer_ptr.mem` | First edge index of each layer | 155 / 308 lines depending on the code |
| `gen/*_edges.coe` | Same edges for the Block Memory Generator IP | Only if you use the IP instead of inference |

## `constraints/` and `tb/`

| File | Purpose | Focus point |
|---|---|---|
| `constraints/ldpc.xdc` | The decoder's 125 MHz clock, 2 ns I/O budget, false path on reset | Added at stage 4. Stages 1–3 were synthesised with no constraints at all, so their timing numbers do not exist |
| `constraints/timing_125mhz.xdc` | The same idea for the week-1 `axis_smoke` core | Belongs to the other Vivado project; keep it out of `ldpc_decoder`, or two `create_clock` commands fight over `clk` |
| `tb/tb_axis_smoke.sv` | Testbench for the week-1 core | Drives random back-pressure; samples on the falling edge to avoid races |
| `tb/tb_syndrome_checker.sv` | Stage 1 testbench | Checks a clean word and a deliberately flipped one — a checker that always says yes passes the first test only |
| `tb/tb_layer_datapath.sv` | Stage 2 testbench | Compares all 65,536 APP values against the per-layer snapshots, reporting the first five mismatching lanes |
| `tb/tb_ldpc_core.sv` | Stage 3 testbench | Reloads the starting state before each run, because the DUT clears its record memory at every `start` |
| `tb/tb_ldpc_decoder.sv` | Stage 4 testbench | Reads `expected.csv` with `$fscanf` and checks `ok`, `iterations` and every decoded bit, for 20 frames |

---

## `codes/` — designed LDPC codes

Each `.npz` holds the base matrix, the lifting size and metadata. All are `n = 65,536`, `Z = 128`, `n_b = 512`.

| File | Status | Serves |
|---|---|---|
| `v3_mother_0_r850.npz` | **current** | Q = 1–2% (77 layers, max row degree 27) |
| `v3_mother_1_r700.npz` | **current** | Q = 3–6% (154 layers, max row degree 14) |
| `v3_mother_2_r400.npz` | **current** | Q = 8% (307 layers, max row degree 7) |
| `v3_mother_*_r875/r725/r750/r450/r575.npz` | variants | Produced by the margin sweep; kept so those results reproduce |
| `mother_high/low.npz`, `v2_mother_high/low.npz` | superseded | From design passes v1 and v2; kept because their results are cited |

---

## `results/` — evidence

Each directory holds raw data, a machine-readable header and a `README.md` that interprets it.

| Directory | Records |
|---|---|
| `axis_smoke_xc7z020clg400-1/` | Week-1 toolflow proof: WNS +2.565 ns, 2 BRAM, 0.111 W, plus the three Vivado reports |
| `e1_l1/` | First L1 sweep: a fixed-rate code leaks 4.3× the minimum at 1% QBER |
| `c1_rate_adaptation/` | The 10% puncture budget, and the high-degree puncturing probe |
| `e2_quantisation/` | Word widths: 6-bit messages and 7–8-bit APP are the cliff edge |
| `bench_decoder/` | Numba speed-up and the cost of a 10⁵-frame point |
| `e3_throughput_tradeoff/` | E3: REQ-PERF-04 is met at a mask without puncturing (71.6 Mbit/s at Q=5%), and the secret-key optimum sits 1–2 mask steps below the efficiency optimum |
| `e5_key_rate/` | Key rate against distance; efficiency decides maximum range |
| `m3_code_design/`, `_v2/`, `_v3/` | The three code-design passes; `_v3/README.md` tells the whole story |
| `m3_margin_1.05/`, `_1.10/` | Efficiency against iterations trade-off |
| `stage1_syndrome_checker/` | Bring-up stage 1: edge ROM and address arithmetic, 1,282 LUT |
| `stage2_layer_datapath/` | Bring-up stage 2: the arithmetic core, bit-exact per layer, 15,040 LUT — and the rotator-sharing before/after |
| `stage3_iteration_loop/` | Bring-up stage 3: a decoded frame, bit-exact after 1, 3 and 6 iterations. 22,389 LUT, 72 BRAM tiles, of which 54 are the check-record memory |
| `stage4_early_termination/` | Bring-up stage 4: all 20 frames match `ok`, `iterations` and every decoded bit. 18,836 LUT (35.4%), 70 BRAM tiles, 60.3 Mbit/s at 125 MHz |
| `stage8_deep_pipeline/` | **Timing closed**: WNS +0.081 ns at 125 MHz, 22,921 LUT, 0.917 W, 10,149 cycles an iteration. The whole pipelining study in one table |
| `stage7_pipelined_decoder/` | **Pipelined decoder, implemented**: 9,687 cycles an iteration, WNS −5.719 ns (72.9 MHz), 23.4 nJ/bit. Every worst path is the same arithmetic stage |
| `impl_decoder_unpipelined/` | **First implementation run**: fully routed, WNS −11.362 ns (Fmax 51.6 MHz), 1.036 W total / 0.912 W dynamic. The baseline the pipelined version is measured against |
| `stage5_rate_masks/` | Bring-up stage 5: QBER 5% decoded at rate 0.628 by a code whose unmasked threshold is 4.04%. 19,964 LUT (37.5%), 72.5 BRAM tiles — **and the first timing number: WNS −9.196 ns, Fmax ≈ 58 MHz** |

---

## Not in git

| Path | What it is |
|---|---|
| `docs/stages/`, `docs/blocks/`, `docs/decisions/`, `docs/log/` | Kept on disk as working documents, untracked by choice (16 Oct 2026) |
| `vivado/` | Your Vivado projects (`axis_smoke`, `ldpc_decoder`). Regenerable from the sources, so ignored |
| `.venv/` | The uv environment |
| `paper/` | LaTeX drafts (empty until M5) |

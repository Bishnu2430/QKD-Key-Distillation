# 13 — RTL Coding Guidelines (SystemVerilog)

| Version | 0.0 (outline), 21 Sep 2026 · Freeze before M4 |
|---|---|

## Rules (initial)
1. **Language:** synthesisable SystemVerilog-2012 subset. `logic` everywhere; `always_ff` / `always_comb` only.
2. **Clocks and resets:** one clock `clk`; synchronous active-low `rst_n`. Reset only control state, not datapath registers or memories.
3. **Naming:** `snake_case`. Suffixes: `_q` (register), `_d` (next state), `_n` (active low). Prefixes: `s_axis_` / `m_axis_` / `s_axil_`.
4. **Parameters:** every width and size is a `parameter` (REQ-IMP-05). Derived values go in `localparam`.
5. **Fixed point:** name signals with their format, for example `llr_app_s8` (signed, 8 bits). Saturate with a shared `sat` function that matches [05 §2](05-algorithm-spec.md#2-conventions).
6. **Memories:** infer BRAM with the Vivado templates. Register the outputs. No asynchronous reads on large arrays.
7. **No latches.** Every `always_comb` assigns defaults first.
8. **Interfaces:** AXI4-Stream handshake `valid && ready`. Never make `valid` depend combinationally on `ready`.
9. **Simulation-only code** goes inside `` `ifdef SIMULATION ``.
10. **Lint:** `verilator --lint-only -Wall` must be clean before commit.

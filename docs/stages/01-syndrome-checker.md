# Stage 1 — Syndrome Checker (complete walkthrough)

| Goal | A module that reads the code memories, walks all 154 layers, computes the parity of the connected bits and compares it with Alice's syndrome |
| Why first | It exercises the edge ROM format, the address arithmetic and the layer walk — the three things that break first — with no LLR arithmetic in the way |
| Code used | `v3_mother_1_r700` (Q = 3–6%): N_B = 512, M_B = 154, Z = 128, N_EDGES = 2,048, EDGE_BITS = 16 |
| You will write | `rtl/syndrome_checker.sv` and `tb/tb_syndrome_checker.sv`, both by hand in Vivado |
| Time | About an hour, most of it typing |

---

## Step 0 — Get the test vectors (one command, outside Vivado)

In WSL, from the repository root:

```bash
uv run python scripts/export_test_vectors.py --code codes/v3_mother_1_r700.npz \
    --qber 0.03 --frames 20 --out tv/r700_q03
```

> **Why 3% and not 5%.** These vectors use the r700 code **unmasked**, so it runs at its mother rate 0.700, whose decoding threshold is 4.04% ([06 §4](../06-ldpc-code-design.md#4-degree-profile-and-the-threshold-curve)). At 5% QBER every frame fails, `expected.csv` shows `ok=0`, and the exported word does *not* satisfy the syndrome — your checker would correctly report all 154 layers bad and you would spend the evening debugging working RTL. That code serves 5% only with shortening, which arrives in stage 5.
>
> **Always check `expected.csv` says `ok=1` before trusting a vector set.**

This writes `tv/r700_q03/`. The files you need in this stage:

| File | Size | Meaning |
|---|---|---|
| `frames/000_xhat.hex` | 1,024 lines | The decoded 65,536-bit word, 64 bits per line |
| `frames/000_syndrome.hex` | 308 lines | Alice's 19,712-bit syndrome, 64 bits per line |
| `expected.csv` | — | `ok=1` means that word satisfies the syndrome |

No mask is applied (no puncturing, no shortening), so `xhat` is the full 65,536-bit word — exactly what the syndrome check needs. Pick a frame whose `expected.csv` row says `ok=1`; frame 000 normally does.

**Tell me if you want me to run this** — it is a Python command in the repo, not a Vivado action.

---

## Step 1 — Create the project

1. **Vivado 2025.2 → Create Project** → name `ldpc_decoder`, location `D:/QKD-Key-Distillation/vivado`, tick *Create project subdirectory* → **Next**
2. **RTL Project**, tick *Do not specify sources at this time* → **Next**
3. **Parts** tab → Family **Zynq-7000**, Package **clg400**, Speed **-1** → select **`xc7z020clg400-1`** → **Next** → **Finish**
4. *Tools → Settings → Project Settings → General*: Target language **Verilog**, Simulator language **Mixed** → **OK**
5. *Settings → Synthesis → More Options*: type `-mode out_of_context` → **OK**

(If you already created this project, skip to step 2.)

---

## Step 2 — Add the generated code memories

1. **Add Sources → Add or create design sources → Next → Add Files**
2. File-type dropdown → **All Files**
3. Navigate to `D:/QKD-Key-Distillation/rtl/gen` and select exactly these three:
   - `v3_mother_1_r700_params.svh`
   - `v3_mother_1_r700_edges.mem`
   - `v3_mother_1_r700_layer_ptr.mem`
4. **Untick "Copy sources into project"** → **Finish**

**Check:** in the Sources pane, expand *Design Sources*. The `.mem` files appear under **Non-module Files**; the `.svh` appears as a Verilog header. Both are correct.

---

## Step 3 — Create the RTL file

1. **Add Sources → Add or create design sources → Next → Create File**
2. File type **SystemVerilog**, name `syndrome_checker.sv`, location → **Choose Location…** → `D:/QKD-Key-Distillation/rtl` → **OK** → **Finish**
3. The **Define Module** dialog appears → **Cancel** → **Yes**
4. Double-click `syndrome_checker.sv` in the Sources pane and type the code below.

### The code

```systemverilog
`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Stage 1: walk every layer, XOR the connected bits, compare with the syndrome.
// Deliberately simple: three cycles per edge, no pipelining. Stage 2 speeds it up.
module syndrome_checker (
    input  wire                     clk,
    input  wire                     rst_n,

    // load port: the testbench fills the two memories through this
    input  wire                     wr_x_en,
    input  wire [ADDR_X-1:0]        wr_x_addr,   // base column index
    input  wire [Z-1:0]             wr_x_data,   // 128 bits of x_hat
    input  wire                     wr_s_en,
    input  wire [ADDR_S-1:0]        wr_s_addr,   // layer index
    input  wire [Z-1:0]             wr_s_data,   // 128 syndrome bits

    // control
    input  wire                     start,
    output logic                    busy,
    output logic                    done,
    output logic                    match,       // 1 = every layer agreed
    output logic [15:0]             bad_layers   // how many disagreed
);

  localparam int unsigned ADDR_X = $clog2(N_B);        // 9
  localparam int unsigned ADDR_S = $clog2(M_B);        // 8
  localparam int unsigned ADDR_E = $clog2(N_EDGES);    // 11

  // ---------------------------------------------------------------- memories
  logic [Z-1:0]          xhat_mem [N_B];   // 512 x 128 = 65,536 bits
  logic [Z-1:0]          syn_mem  [M_B];   // 154 x 128 = 19,712 bits
  logic [EDGE_BITS-1:0]  edge_rom [N_EDGES];
  logic [15:0]           layer_ptr_rom [M_B+1];

  initial begin
    $readmemh("v3_mother_1_r700_edges.mem",     edge_rom);
    $readmemh("v3_mother_1_r700_layer_ptr.mem", layer_ptr_rom);
  end

  always_ff @(posedge clk) begin
    if (wr_x_en) xhat_mem[wr_x_addr] <= wr_x_data;
    if (wr_s_en) syn_mem [wr_s_addr] <= wr_s_data;
  end

  // ------------------------------------------------------- rotate left by k
  // lane i of a check must read bit (i + shift) mod Z of the column word.
  function automatic logic [Z-1:0] rotl(input logic [Z-1:0] w,
                                        input logic [SHIFT_BITS-1:0] k);
    logic [2*Z-1:0] dbl;
    begin
      dbl  = {w, w};
      rotl = dbl[k +: Z];
    end
  endfunction

  // ------------------------------------------------------------------- FSM
  typedef enum logic [2:0] {
    S_IDLE, S_LAYER, S_EDGE_ROM, S_EDGE_MEM, S_EDGE_ACC, S_CMP, S_DONE
  } state_t;

  state_t                 state;
  logic [ADDR_S:0]        layer;      // one extra bit: counts up to M_B
  logic [ADDR_E:0]        e_idx, e_end;
  logic [Z-1:0]           acc;
  logic [EDGE_BITS-1:0]   rom_q;
  logic [SHIFT_BITS-1:0]  shift_q;
  logic [Z-1:0]           word_q;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state      <= S_IDLE;
      busy       <= 1'b0;
      done       <= 1'b0;
      match      <= 1'b1;
      bad_layers <= '0;
      layer      <= '0;
    end else begin
      case (state)
        S_IDLE: begin
          done <= 1'b0;
          if (start) begin
            busy       <= 1'b1;
            match      <= 1'b1;
            bad_layers <= '0;
            layer      <= '0;
            state      <= S_LAYER;
          end
        end

        S_LAYER: begin                       // set up one layer
          e_idx <= layer_ptr_rom[layer];
          e_end <= layer_ptr_rom[layer + 1];
          acc   <= '0;
          state <= S_EDGE_ROM;
        end

        S_EDGE_ROM: begin                    // fetch one edge record
          if (e_idx == e_end) begin
            state <= S_CMP;
          end else begin
            rom_q <= edge_rom[e_idx];
            state <= S_EDGE_MEM;
          end
        end

        S_EDGE_MEM: begin                    // read that column, latch the shift
          word_q  <= xhat_mem[rom_q[COL_BITS-1:0]];
          shift_q <= rom_q[EDGE_BITS-1:COL_BITS];
          state   <= S_EDGE_ACC;
        end

        S_EDGE_ACC: begin                    // rotate into place and accumulate
          acc   <= acc ^ rotl(word_q, shift_q);
          e_idx <= e_idx + 1'b1;
          state <= S_EDGE_ROM;
        end

        S_CMP: begin                         // compare this layer
          if (acc != syn_mem[layer[ADDR_S-1:0]]) begin
            match      <= 1'b0;
            bad_layers <= bad_layers + 1'b1;
          end
          if (layer == M_B - 1) begin
            state <= S_DONE;
          end else begin
            layer <= layer + 1'b1;
            state <= S_LAYER;
          end
        end

        S_DONE: begin
          busy  <= 1'b0;
          done  <= 1'b1;
          state <= S_IDLE;
        end

        default: state <= S_IDLE;
      endcase
    end
  end

endmodule

`default_nettype wire
```

Press **Ctrl+S**. In the Sources pane `syndrome_checker` should now be bold (top module). If not: right-click → **Set as Top**.

### The three lines that matter most

| Line | Why |
|---|---|
| `rotl` using `{w, w}` then `dbl[k +: Z]` | Result bit `i` is `w[(i+k) mod Z]`, which is exactly the spec's `var = c*Z + ((i + shift) mod Z)`. Get the direction wrong and every layer mismatches |
| `rom_q[COL_BITS-1:0]` is the column, `rom_q[EDGE_BITS-1:COL_BITS]` the shift | The generator packs `{shift[6:0], column[8:0]}` into 16 bits. Swap them and nothing works |
| `$readmemh` with bare filenames | Works because step 2 added the `.mem` files to the project. An absolute path works in simulation and can fail in synthesis |

---

## Step 4 — Create the testbench

1. **Add Sources → Add or create simulation sources → Next → Create File**
2. Type **SystemVerilog**, name `tb_syndrome_checker.sv`, location `D:/QKD-Key-Distillation/tb` → **OK** → **Finish** → **Cancel** the Define Module dialog
3. Type this in:

```systemverilog
`timescale 1ns/1ps
`default_nettype none
`include "v3_mother_1_r700_params.svh"

module tb_syndrome_checker;

  localparam int unsigned ADDR_X   = $clog2(N_B);
  localparam int unsigned ADDR_S   = $clog2(M_B);
  localparam int unsigned X_WORDS  = N_BITS / 64;   // 1024
  localparam int unsigned S_WORDS  = M_BITS / 64;   // 308

  logic clk = 1'b0, rst_n = 1'b0;
  always #4 clk = ~clk;                              // 125 MHz

  logic               wr_x_en = 1'b0, wr_s_en = 1'b0, start = 1'b0;
  logic [ADDR_X-1:0]  wr_x_addr = '0;
  logic [ADDR_S-1:0]  wr_s_addr = '0;
  logic [Z-1:0]       wr_x_data = '0, wr_s_data = '0;
  wire                busy, done, match;
  wire [15:0]         bad_layers;

  syndrome_checker dut (.*);

  // test vectors, 64 bits per line, LSB-first inside each word
  logic [63:0] xhat_words [0:X_WORDS-1];
  logic [63:0] syn_words  [0:S_WORDS-1];

  task automatic load_memories(input logic corrupt);
    begin
      for (int c = 0; c < N_B; c++) begin
        @(negedge clk);
        wr_x_en   = 1'b1;
        wr_x_addr = c[ADDR_X-1:0];
        // a 128-bit column word is two consecutive 64-bit file words
        wr_x_data = {xhat_words[2*c+1], xhat_words[2*c]};
        if (corrupt && c == 7) wr_x_data[3] = ~wr_x_data[3];   // flip one bit
      end
      @(negedge clk);
      wr_x_en = 1'b0;

      for (int r = 0; r < M_B; r++) begin
        @(negedge clk);
        wr_s_en   = 1'b1;
        wr_s_addr = r[ADDR_S-1:0];
        wr_s_data = {syn_words[2*r+1], syn_words[2*r]};
      end
      @(negedge clk);
      wr_s_en = 1'b0;
    end
  endtask

  task automatic run_check(output logic result, output logic [15:0] bad);
    begin
      @(negedge clk) start = 1'b1;
      @(negedge clk) start = 1'b0;
      wait (done);
      result = match;
      bad    = bad_layers;
      @(negedge clk);
    end
  endtask

  logic        result;
  logic [15:0] bad;
  int          errors = 0;

  initial begin
    $readmemh("tv/r700_q03/frames/000_xhat.hex",     xhat_words);
    $readmemh("tv/r700_q03/frames/000_syndrome.hex", syn_words);

    repeat (5) @(negedge clk);
    rst_n = 1'b1;

    // 1. the real decoded word must satisfy the syndrome
    load_memories(1'b0);
    run_check(result, bad);
    $display("clean  : match=%0d bad_layers=%0d", result, bad);
    if (result !== 1'b1) begin
      $display("ERROR: a valid word was rejected");
      errors++;
    end

    // 2. one flipped bit must be caught
    load_memories(1'b1);
    run_check(result, bad);
    $display("flipped: match=%0d bad_layers=%0d", result, bad);
    if (result !== 1'b0) begin
      $display("ERROR: a corrupted word passed");
      errors++;
    end

    if (errors == 0) $display("STAGE 1 PASSED");
    else             $display("STAGE 1 FAILED");
    $finish;
  end

  initial begin
    #5_000_000;
    $display("ERROR: timeout");
    $finish;
  end

endmodule

`default_nettype wire
```

4. **Ctrl+S**. In *Sources → Simulation Sources → sim_1*, right-click `tb_syndrome_checker` → **Set as Top**.

---

## Step 5 — Point the simulator at the test vectors

`$readmemh("tv/r700_q03/...")` is relative to the **simulation working directory**, which is
`vivado/ldpc_decoder/ldpc_decoder.sim/sim_1/behav/xsim`.

Pick one of these:

- **Simplest:** change the two `$readmemh` paths in the testbench to absolute, for example
  `"D:/QKD-Key-Distillation/tv/r700_q03/frames/000_xhat.hex"`. Absolute paths are fine in a
  testbench; only synthesis dislikes them.
- **Or** add the two `.hex` files as simulation sources (All Files filter) and use bare filenames.

---

## Step 6 — Run it

1. Flow Navigator → **SIMULATION → Run Simulation → Run Behavioral Simulation**
2. In the Tcl console at the bottom type `run all` (or press the ⏩ **Run All** button)
3. Read the console

**What a pass looks like:**

```
clean  : match=1 bad_layers=0
flipped: match=0 bad_layers=1
STAGE 1 PASSED
```

`bad_layers` after the flip is typically 3–6, not 1 — a single bit sits in several checks. Any non-zero value is a pass.

---

## Step 7 — When it fails

| Symptom | Almost certainly |
|---|---|
| `match=0` on the clean word, `bad_layers` = 154 (every layer) | **First check `expected.csv` says `ok=1` for that frame.** A frame the model failed to decode does not satisfy the syndrome, and your checker is right to reject it |
| `match=0` on the clean word, every layer bad, and `ok=1` in `expected.csv` | Rotation direction. Swap `dbl[k +: Z]` for `dbl[(Z-k) +: Z]` and see if it flips to passing — if it does, your shift convention was inverted |
| `match=0`, a handful of bad layers | Column/shift fields swapped, or the 128-bit word assembled in the wrong order. Check `{xhat_words[2*c+1], xhat_words[2*c]}` — the **higher** index is the **upper** half |
| `match=1` on both the clean and the flipped word | The syndrome memory never loaded, so `acc` is being compared against zeros. Check `wr_s_en` timing in the waveform |
| Every value is `X` | `$readmemh` found no file. Vivado prints a warning in the console — read it; it names the path it tried |
| Simulation hangs, timeout fires | `done` never asserts. Look at `state` in the waveform: stuck in `S_EDGE_ROM` means `e_end` is wrong, so check `layer_ptr_rom` loaded |

**To see inside:** in the simulation window, select `dut` in the **Scope** pane, drag `state`, `layer`, `e_idx`, `e_end`, `acc` from **Objects** into the waveform, then **Restart** and **Run All**.

---

## Step 8 — Synthesise it (optional but informative)

Flow Navigator → **Run Synthesis** → **Open Synthesized Design** → *Reports → Report Utilization*.

Measured on the first working build ([results/stage1_syndrome_checker](../../results/stage1_syndrome_checker/README.md)):

| Resource | Used | % of device |
|---|---|---|
| Slice LUTs | 1,282 | 2.41 |
| Slice registers | 195 | 0.18 |
| Block RAM tiles | 4 (3 × RAMB36 + 2 × RAMB18) | 2.86 |
| DSP | 0 | 0.00 |
| Bonded IOB | **0** | 0.00 |

Most of the LUTs are the rotator — a 128-bit rotate by a 7-bit amount is a seven-stage mux tree. If BRAM comes out as 0, the memories became distributed RAM; tell me and we will look at the inference conditions together.

---

## Step 9 — Report back

Send me:
1. The console output of step 6.
2. If it failed: which symptom from step 7, plus a screenshot or the values of `state`, `layer` and `acc` at the first bad layer.
3. If you synthesised: LUT, FF, BRAM counts.

Then we go to **stage 2**, the one layer of real datapath: APP memory, subtract, min-finder, normalisation and write-back — in the same format as this document, with the complete module.

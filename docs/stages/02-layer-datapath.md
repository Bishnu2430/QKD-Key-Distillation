# Stage 2 — One Layer of the Datapath (complete walkthrough)

| Goal | Process **one layer**: read the APP memory, rotate into check order, find the two smallest magnitudes per lane, compute the new check messages, add them back, write the APP memory |
| Why now | This is the decoder's arithmetic core. Everything later (iterations, early termination, masks) is control around it |
| Scope limit | First iteration only, so the old check messages are zero and `T = L`. Message memory arrives in stage 3 |
| Checked against | Per-layer APP snapshots from the bit-true model — a mismatch localises to one layer, not one frame |
| You will write | `rtl/layer_datapath.sv` and `tb/tb_layer_datapath.sv`, by hand |

---

## Step 0 — Get the layer snapshots (one command, outside Vivado)

```bash
uv run python scripts/export_layer_dump.py --code codes/v3_mother_1_r700.npz \
    --qber 0.03 --layers 2 --out tv/r700_q03_layers
```

Already generated. It writes:

| File | Lines | Contents |
|---|---|---|
| `app_init.hex` | 8,192 | APP array before any layer runs |
| `app_after_l000.hex` | 8,192 | APP array after layer 0 |
| `app_after_l001.hex` | 8,192 | APP array after layer 1 |
| `syndrome.hex` | 308 | The frame's syndrome |
| `meta.json` | — | Code shape, fixed-point configuration, amplitude |

**APP serialisation:** one signed 8-bit value per variable, in variable order, eight values per 64-bit word. Variable `v = c·Z + j` sits in word `v/8` at byte `v%8`, so **base column `c` occupies the 16 consecutive words starting at `16·c`**, word `16c` holding the lowest 64 bits.

Sanity check you can do by eye: `app_init.hex` is full of `f2` and `0e` — that is −14 and +14, the channel amplitude A = 14 for QBER 3%. And `meta.json` reports 1,792 values changed by layer 0: exactly 128 lanes × 14 neighbours, the row degree of this code.

---

## Step 1 — Create the RTL file

**Add Sources → Add or create design sources → Create File**, type **SystemVerilog**, name `layer_datapath.sv`, location `D:/QKD-Key-Distillation/rtl` → **OK** → **Finish** → **Cancel** the Define Module dialog. Then type:

```systemverilog
`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Stage 2: process one layer, first-iteration semantics (old messages are zero).
// Two passes over the layer's edges:
//   pass A - find min1/min2/index and the sign product for each of the Z lanes
//   pass B - write back L = sat(T + R_new)
// Three cycles per edge in each pass; stage 3 pipelines this.
//
// MEMORY STRUCTURE MATTERS AS MUCH AS THE ARITHMETIC. app_mem is 512 x 1024
// bits and must become block RAM, which means exactly ONE write port and ONE
// read port, both registered, both inside one always_ff. The read address is
// muxed between the datapath and the test port; the write is muxed between the
// load path and the datapath. Spread those accesses over two always_ff blocks
// and Vivado reports "Unable to infer a block/distributed RAM ... 524288 bits
// is too large".
module layer_datapath (
    input  wire                     clk,
    input  wire                     rst_n,

    // APP memory load / read-back port (the testbench uses this)
    input  wire                     wr_app_en,
    input  wire [ADDR_X-1:0]        wr_app_addr,
    input  wire [APP_W-1:0]         wr_app_data,
    input  wire [ADDR_X-1:0]        rd_app_addr,
    output wire [APP_W-1:0]         rd_app_data,

    // syndrome load port
    input  wire                     wr_s_en,
    input  wire [ADDR_S-1:0]        wr_s_addr,
    input  wire [Z-1:0]             wr_s_data,

    // control
    input  wire                     start,
    input  wire [ADDR_S-1:0]        layer_sel,
    output logic                    busy,
    output logic                    done
);

  // ------------------------------------------------------------ parameters
  localparam int unsigned ADDR_X   = $clog2(N_B);          // 9
  localparam int unsigned ADDR_S   = $clog2(M_B);          // 8
  localparam int unsigned ADDR_E   = $clog2(N_EDGES);      // 11
  localparam int unsigned W_APP    = 8;                    // spec 2.1
  localparam int unsigned W_MSG    = 6;
  localparam int          MAX_APP  = 127;   // signed: sat_add compares against it
  localparam int unsigned MAX_MSG  = 31;    // unsigned: only compared with |T|
  localparam int unsigned APP_W    = Z * W_APP;            // 1024 bits per column
  localparam int unsigned IDX_BITS = $clog2(MAX_ROW_DEG + 1);

  // --------------------------------------------------------------- state
  typedef enum logic [3:0] {
    S_IDLE, S_SETUP, S_A_ROM, S_A_MEM, S_A_ACC,
    S_B_SETUP, S_B_ROM, S_B_MEM, S_B_WR, S_DONE
  } state_t;

  state_t                state;
  logic [ADDR_E:0]       e_start, e_end, e_idx;
  logic [IDX_BITS-1:0]   pos;
  logic [EDGE_BITS-1:0]  rom_q;
  logic [SHIFT_BITS-1:0] shift_q;
  logic [COL_BITS-1:0]   col_q;

  logic [W_MSG:0]        min1 [Z];      // one bit wider than W_MSG for the sentinel
  logic [W_MSG:0]        min2 [Z];
  logic [IDX_BITS-1:0]   idx  [Z];
  logic                  sgn  [Z];      // running sign product, 1 = negative
  logic [Z-1:0]          syn_q;

  // --------------------------------------------------------------- memories
  logic [APP_W-1:0]      app_mem  [N_B];
  logic [Z-1:0]          syn_mem  [M_B];
  logic [EDGE_BITS-1:0]  edge_rom [N_EDGES];
  logic [15:0]           layer_ptr_rom [M_B+1];

  initial begin
    $readmemh("v3_mother_1_r700_edges.mem",     edge_rom);
    $readmemh("v3_mother_1_r700_layer_ptr.mem", layer_ptr_rom);
  end

  // syndrome memory: small, one write, asynchronous read in S_SETUP
  always_ff @(posedge clk) begin
    if (wr_s_en) syn_mem[wr_s_addr] <= wr_s_data;
  end

  // ------------------------------------------------------------- functions
  // rotate the Z lanes left by k: lane i of the result is lane (i+k) mod Z
  function automatic logic [APP_W-1:0] rot_lanes(input logic [APP_W-1:0] w,
                                                 input logic [SHIFT_BITS-1:0] k);
    logic [2*APP_W-1:0] dbl;
    begin
      dbl       = {w, w};
      rot_lanes = dbl[k * W_APP +: APP_W];
    end
  endfunction

  // saturating add into the APP word width; clamps, never wraps (spec 2)
  function automatic logic signed [W_APP-1:0] sat_add(
      input logic signed [W_APP-1:0]   a,
      input logic signed [W_APP+1:0]   b);
    logic signed [W_APP+2:0] s;
    begin
      s = a + b;
      if      (s >  MAX_APP) sat_add =  MAX_APP;
      else if (s < -MAX_APP) sat_add = -MAX_APP;
      else                   sat_add = s[W_APP-1:0];
    end
  endfunction

  // ---------------------------------------------------- APP memory ports
  // ONE read port, ONE write port. This is what makes it a BRAM.
  logic [ADDR_X-1:0] app_raddr;
  logic [APP_W-1:0]  app_q;        // registered read data, used by both users
  logic              app_we;
  logic [ADDR_X-1:0] app_waddr;
  logic [APP_W-1:0]  app_wdata;

  assign rd_app_data = app_q;

  // combinational write-back word, built from the registered read data
  logic [APP_W-1:0]        t_word, new_word;
  logic signed [W_APP-1:0] tl;
  logic [W_APP-1:0]        magv;
  logic [W_MSG:0]          nrm;
  logic signed [W_APP+1:0] rval;
  logic                    rneg;

  // temporaries used only inside the control block (pass A accumulation)
  logic signed [W_APP-1:0] ta;
  logic [W_APP-1:0]        ma;
  logic [W_MSG:0]          aa;

  always_comb begin
    t_word = rot_lanes(app_q, shift_q);
    for (int i = 0; i < Z; i++) begin
      tl   = t_word[i*W_APP +: W_APP];
      magv = (pos == idx[i]) ? {1'b0, min2[i]} : {1'b0, min1[i]};
      nrm  = (magv >> 1) + (magv >> 2);                 // alpha = 0.75, truncating
      rneg = sgn[i] ^ syn_q[i] ^ tl[W_APP-1];           // final sign of R
      rval = rneg ? -$signed({2'b00, nrm}) : $signed({2'b00, nrm});
      new_word[i*W_APP +: W_APP] = sat_add(tl, rval);
    end
  end

  always_comb begin
    // read: the datapath while it is fetching a column, the test port otherwise
    app_raddr = ((state == S_A_MEM) || (state == S_B_MEM))
                ? rom_q[COL_BITS-1:0] : rd_app_addr;

    // write: the load path has priority, otherwise the datapath write-back
    if (wr_app_en) begin
      app_we    = 1'b1;
      app_waddr = wr_app_addr;
      app_wdata = wr_app_data;
    end else begin
      app_we    = (state == S_B_WR);
      app_waddr = col_q;
      app_wdata = rot_lanes(new_word, (Z - shift_q) & (Z - 1));  // back to column order
    end
  end

  always_ff @(posedge clk) begin
    if (app_we) app_mem[app_waddr] <= app_wdata;
    app_q <= app_mem[app_raddr];
  end

  // --------------------------------------------------------------- control
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= S_IDLE;
      busy  <= 1'b0;
      done  <= 1'b0;
    end else begin
      case (state)
        S_IDLE: begin
          done <= 1'b0;
          if (start) begin
            busy  <= 1'b1;
            state <= S_SETUP;
          end
        end

        S_SETUP: begin
          e_start <= layer_ptr_rom[layer_sel];
          e_end   <= layer_ptr_rom[layer_sel + 1];
          e_idx   <= layer_ptr_rom[layer_sel];
          pos     <= '0;
          syn_q   <= syn_mem[layer_sel];
          for (int i = 0; i < Z; i++) begin
            min1[i] <= MAX_MSG + 1;          // sentinel: larger than any |T|
            min2[i] <= MAX_MSG + 1;
            idx[i]  <= '0;
            sgn[i]  <= 1'b0;
          end
          state <= S_A_ROM;
        end

        // ---------------------------------------------------------- pass A
        S_A_ROM: begin
          if (e_idx == e_end) state <= S_B_SETUP;
          else begin
            rom_q <= edge_rom[e_idx];
            state <= S_A_MEM;
          end
        end

        S_A_MEM: begin                       // app_raddr points at this column now
          col_q   <= rom_q[COL_BITS-1:0];
          shift_q <= rom_q[EDGE_BITS-1:COL_BITS];
          state   <= S_A_ACC;
        end

        S_A_ACC: begin                       // app_q holds the column
          for (int i = 0; i < Z; i++) begin
            ta = t_word[i*W_APP +: W_APP];
            ma = ta[W_APP-1] ? (-ta) : ta;                  // |T|
            aa = (ma > MAX_MSG) ? MAX_MSG[W_MSG:0] : ma[W_MSG:0];
            sgn[i] <= sgn[i] ^ ta[W_APP-1];                 // sign product
            if (aa < min1[i]) begin                         // strict: first wins
              min2[i] <= min1[i];
              min1[i] <= aa;
              idx[i]  <= pos;
            end else if (aa < min2[i]) begin
              min2[i] <= aa;
            end
          end
          e_idx <= e_idx + 1'b1;
          pos   <= pos + 1'b1;
          state <= S_A_ROM;
        end

        // ---------------------------------------------------------- pass B
        S_B_SETUP: begin
          e_idx <= e_start;
          pos   <= '0;
          state <= S_B_ROM;
        end

        S_B_ROM: begin
          if (e_idx == e_end) state <= S_DONE;
          else begin
            rom_q <= edge_rom[e_idx];
            state <= S_B_MEM;
          end
        end

        S_B_MEM: begin
          col_q   <= rom_q[COL_BITS-1:0];
          shift_q <= rom_q[EDGE_BITS-1:COL_BITS];
          state   <= S_B_WR;
        end

        S_B_WR: begin                        // the write happens in the memory block
          e_idx <= e_idx + 1'b1;
          pos   <= pos + 1'b1;
          state <= S_B_ROM;
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

### Why the memory is written the way it is

`app_mem` is 512 × 1,024 = 524,288 bits. It **must** become block RAM, and block
RAM has two ports in total. So the module gives it exactly one write port and
one read port, both registered, both inside a single `always_ff`:

* the **read address** is muxed — the datapath's column while fetching, the test
  port's address otherwise;
* the **write** is muxed — the load path has priority, otherwise the datapath's
  write-back;
* `app_q` is the one registered read output, used by the datapath *and* wired to
  `rd_app_data`.

Spread those accesses across two `always_ff` blocks, or give the array two write
ports, and synthesis reports:

```
[Synth 8-3391] Unable to infer a block/distributed RAM for 'app_mem_reg' because
the memory pattern used is not supported. Failed to dissolve the memory into bits
because the number of bits (524288) is too large.
```

That message means "I could not make this a RAM, so I tried to build half a
million flip-flops instead". Simulation passes regardless, which is why this
only shows up at synthesis.

### The five things that decide whether this works

| Detail | Why it matters |
|---|---|
| `rot_lanes` uses `k * W_APP` | Rotation is by **lanes**, not bits. Rotating a 1,024-bit word by 7 bits instead of 7 lanes gives garbage that still looks plausible |
| Write-back rotates by `(Z - shift) & (Z-1)` | The inverse of the read rotation. `& (Z-1)` works because Z = 128 is a power of two, and it handles `shift = 0` without a 128-wide result |
| `if (av < min1[i])` is **strict** | Ties keep the *first* minimum in increasing-column order, which is what the model does ([spec §3.6](../05-algorithm-spec.md#36-decoding-layered-normalized-min-sum-l2-bit-true)) |
| `rneg = sgn[i] ^ syn_q[i] ^ tl[sign]` | The syndrome twist `(−1)^s` and "product of all the *other* signs" in one XOR. Drop `syn_q` and half the layers come out inverted |
| `sat_add` clamps | Spec §2: values saturate, never wrap. A wrap turns a confident 0 into a confident 1 |

Also note `magv` is compared against `pos` using `idx[i]`: in pass B the neighbour at the minimum's own position gets **min2**, everyone else gets **min1**.

---

## Step 2 — Create the testbench

**Add Sources → Add or create simulation sources → Create File**, SystemVerilog, `tb_layer_datapath.sv`, location `D:/QKD-Key-Distillation/tb`:

```systemverilog
`timescale 1ns/1ps
`default_nettype none
`include "v3_mother_1_r700_params.svh"

module tb_layer_datapath;

  localparam int unsigned ADDR_X  = $clog2(N_B);
  localparam int unsigned ADDR_S  = $clog2(M_B);
  localparam int unsigned W_APP   = 8;
  localparam int unsigned APP_W   = Z * W_APP;          // 1024
  localparam int unsigned APP_WORDS = N_BITS / 8;       // 8192 lines
  localparam int unsigned S_WORDS   = M_BITS / 64;      // 308
  localparam int unsigned WORDS_PER_COL = Z / 8;        // 16

  localparam string DIR = "D:/QKD-Key-Distillation/tv/r700_q03_layers/";

  logic clk = 1'b0, rst_n = 1'b0;
  always #4 clk = ~clk;

  logic              wr_app_en = 1'b0, wr_s_en = 1'b0, start = 1'b0;
  logic [ADDR_X-1:0] wr_app_addr = '0, rd_app_addr = '0;
  logic [APP_W-1:0]  wr_app_data = '0;
  wire  [APP_W-1:0]  rd_app_data;
  logic [ADDR_S-1:0] wr_s_addr = '0, layer_sel = '0;
  logic [Z-1:0]      wr_s_data = '0;
  wire               busy, done;

  layer_datapath dut (.*);

  logic [63:0] app_init  [0:APP_WORDS-1];
  logic [63:0] app_exp   [0:APP_WORDS-1];
  logic [63:0] syn_words [0:S_WORDS-1];

  // assemble base column c from its 16 consecutive 64-bit words
  function automatic logic [APP_W-1:0] column_of(ref logic [63:0] src [0:APP_WORDS-1],
                                                 input int c);
    logic [APP_W-1:0] out;
    begin
      for (int w = 0; w < WORDS_PER_COL; w++)
        out[w*64 +: 64] = src[c*WORDS_PER_COL + w];
      column_of = out;
    end
  endfunction

  task automatic load_all;
    begin
      for (int c = 0; c < N_B; c++) begin
        @(negedge clk);
        wr_app_en   = 1'b1;
        wr_app_addr = c[ADDR_X-1:0];
        wr_app_data = column_of(app_init, c);
      end
      @(negedge clk); wr_app_en = 1'b0;

      for (int r = 0; r < M_B; r++) begin
        @(negedge clk);
        wr_s_en   = 1'b1;
        wr_s_addr = r[ADDR_S-1:0];
        wr_s_data = {syn_words[2*r+1], syn_words[2*r]};
      end
      @(negedge clk); wr_s_en = 1'b0;
    end
  endtask

  task automatic run_layer(input int unsigned layer);
    begin
      @(negedge clk) begin layer_sel = layer[ADDR_S-1:0]; start = 1'b1; end
      @(negedge clk) start = 1'b0;
      wait (done);
      @(negedge clk);
    end
  endtask

  // compare the whole APP memory against a snapshot file
  task automatic compare(input string label, output int mismatches);
    logic [APP_W-1:0] expected, got;
    begin
      mismatches = 0;
      for (int c = 0; c < N_B; c++) begin
        @(negedge clk) rd_app_addr = c[ADDR_X-1:0];
        @(negedge clk);                       // registered read
        got      = rd_app_data;
        expected = column_of(app_exp, c);
        if (got !== expected) begin
          for (int i = 0; i < Z; i++)
            if (got[i*W_APP +: W_APP] !== expected[i*W_APP +: W_APP]) begin
              if (mismatches < 5)
                $display("  %s: column %0d lane %0d expected %0d got %0d", label, c, i,
                         $signed(expected[i*W_APP +: W_APP]),
                         $signed(got[i*W_APP +: W_APP]));
              mismatches++;
            end
        end
      end
      $display("%s: %0d lane mismatches", label, mismatches);
    end
  endtask

  int bad, errors = 0;

  initial begin
    $readmemh({DIR, "app_init.hex"},  app_init);
    $readmemh({DIR, "syndrome.hex"},  syn_words);

    repeat (5) @(negedge clk);
    rst_n = 1'b1;

    // ---- layer 0 -------------------------------------------------------
    load_all();
    run_layer(0);
    $readmemh({DIR, "app_after_l000.hex"}, app_exp);
    compare("layer 0", bad);
    if (bad != 0) errors++;

    // ---- layer 1, continuing from the layer-0 state ---------------------
    run_layer(1);
    $readmemh({DIR, "app_after_l001.hex"}, app_exp);
    compare("layer 1", bad);
    if (bad != 0) errors++;

    if (errors == 0) $display("STAGE 2 PASSED");
    else             $display("STAGE 2 FAILED");
    $finish;
  end

  initial begin
    #20_000_000;
    $display("ERROR: timeout");
    $finish;
  end

endmodule

`default_nettype wire
```

Set `tb_layer_datapath` as the simulation top (right-click → **Set as Top**).

---

## Step 3 — Run it

**SIMULATION → Run Simulation → Run Behavioral Simulation**, then `run all`.

**A pass looks like:**

```
layer 0: 0 lane mismatches
layer 1: 0 lane mismatches
STAGE 2 PASSED
```

---

## Step 4 — When it fails

The compare prints the first five mismatching lanes with expected and actual values. Read them against this table:

| Pattern | Cause |
|---|---|
| Touched lanes read back as **x**, and the mismatch count equals the number of values the layer should have changed | An out-of-range part select somewhere: SystemVerilog returns x rather than erroring. `min1`/`min2` are `W_MSG+1` = 7 bits, so `min1[i][W_APP-1:0]` asks for a bit that does not exist. Zero-extend with `{1'b0, min1[i]}` instead |
| Everything clamps to +127 | `MAX_APP` declared `int unsigned`, so the comparison in `sat_add` goes unsigned and every negative sum looks huge. Declare it `int` |
| **Every** lane of every touched column is wrong | Rotation granularity: you rotated bits, not lanes. Check `k * W_APP` in `rot_lanes` |
| Values are right but land in the **wrong columns** | The write-back rotation. It must be `(Z - shift) & (Z-1)`, not `shift` |
| About half the lanes have the **right magnitude, wrong sign** | The syndrome twist. `rneg` must XOR `syn_q[i]` |
| One lane per column wrong, the rest right | The min2 selection: `pos == idx[i]` picks the neighbour that owns the minimum |
| Magnitudes slightly too large | `nrm` must be `(magv>>1)+(magv>>2)`, truncating. Not `magv*3/4`, not rounded |
| Values pinned at ±127 everywhere | Saturation is firing because `rval` has the wrong width or sign extension |
| Layer 0 passes, layer 1 fails | Per-lane state not cleared in `S_SETUP`, so layer 1 inherits layer 0's minima |
| Nothing changes at all | The `app_mem` write is being overridden by the `wr_app_en` load path — check `wr_app_en` is low during the run |
| Simulation passes but **synthesis** reports `[Synth 8-3391] Unable to infer a block/distributed RAM ... 524288 bits is too large` | The APP memory has more than one write port or more than one read port, or its accesses are split across two `always_ff` blocks. See "Why the memory is written the way it is" above |

To see inside: add `state`, `e_idx`, `pos`, `min1[0]`, `min2[0]`, `idx[0]`, `sgn[0]` to the waveform. Layer 0 of this code has 14 edges, so pass A should take 14 × 3 cycles.

---

## Step 5 — Synthesise

**Run Synthesis → Open Synthesized Design → Report Utilization.**

Expect substantially more than stage 1: two 1,024-bit lane rotators, 128 lanes of compare-select logic, and the APP memory (512 × 1,024 bits = 512 Kb, so 15–16 BRAM36). Rough expectation 8–15k LUTs and 18–22 BRAM tiles. Report the numbers and we will compare against the [architecture estimate](../blocks/ldpc-decoder.md#11-resource-estimate).

**Known optimisation, deliberately not done yet:** `S_B_WR` uses two rotators in the same cycle (forward for the read, inverse for the write). Splitting it into two states lets one rotator serve both and should roughly halve the rotator LUTs. Do that only after this version passes.

---

## Step 6 — Report back

Send: the console output; if it failed, the first five mismatch lines; and the synthesis numbers if you ran it. Stage 3 then adds the check-message memory and the iteration loop, which turns this into a decoder.

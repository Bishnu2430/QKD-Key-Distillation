`timescale 1ns/1ps
`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Activity generator for power measurement. No checking: it loads one frame
// and decodes, so that the SAIF window contains exactly the switching the
// real accelerator does. Two iterations is enough - every iteration looks
// like every other.
module tb_power;

  localparam int unsigned ADDR_X    = $clog2(N_B);
  localparam int unsigned ADDR_S    = $clog2(M_B);
  localparam int unsigned ITER_BITS = 6;
  localparam int unsigned W_APP     = 8;
  localparam int unsigned APP_W     = Z * W_APP;
  localparam int unsigned KEY_WORDS = N_BITS / 64;
  localparam int unsigned S_WORDS   = M_BITS / 64;

  localparam string DIR = "D:/QKD-Key-Distillation/tv/r700_q05_m16s125/";

  logic clk = 1'b0, rst_n = 1'b0;
  always #4 clk = ~clk;

  logic                 wr_app_en = 1'b0, wr_s_en = 1'b0, wr_m_en = 1'b0, wr_k_en = 1'b0;
  logic                 load_start = 1'b0, start = 1'b0;
  logic [ADDR_X-1:0]    wr_app_addr = '0, rd_app_addr = '0, wr_m_addr = '0, wr_k_addr = '0;
  logic [APP_W-1:0]     wr_app_data = '0;
  wire  [APP_W-1:0]     rd_app_data;
  logic [ADDR_S-1:0]    wr_s_addr = '0;
  logic [Z-1:0]         wr_s_data = '0, wr_k_data = '0;
  logic [1:0]           wr_m_data = '0;
  logic signed [W_APP-1:0] ch_amp = 8'sd12;        // A = 12 for the 5% set
  logic [ITER_BITS-1:0] max_iters = 6'd2;          // two iterations of activity
  wire  [ITER_BITS-1:0] iter_count;
  wire                  busy, done, ok;

  ldpc_decoder_deep dut (.*);

  logic [63:0] y_words   [0:KEY_WORDS-1];
  logic [63:0] syn_words [0:S_WORDS-1];
  logic [1:0]  mask_cls  [0:N_B-1];

  int n_key_cols;

  initial begin
    $readmemh({DIR, "mask.mem"},                mask_cls);
    $readmemh({DIR, "frames/000_y.hex"},        y_words);
    $readmemh({DIR, "frames/000_syndrome.hex"}, syn_words);

    repeat (5) @(negedge clk);
    rst_n = 1'b1;

    n_key_cols = 0;
    for (int c = 0; c < N_B; c++) begin
      @(negedge clk);
      wr_m_en = 1'b1; wr_m_addr = c[ADDR_X-1:0]; wr_m_data = mask_cls[c];
      if (mask_cls[c] == 2'd0) n_key_cols++;
    end
    @(negedge clk); wr_m_en = 1'b0;

    for (int k = 0; k < n_key_cols; k++) begin
      @(negedge clk);
      wr_k_en = 1'b1; wr_k_addr = k[ADDR_X-1:0];
      wr_k_data = {y_words[2*k+1], y_words[2*k]};
    end
    @(negedge clk); wr_k_en = 1'b0;

    for (int r = 0; r < M_B; r++) begin
      @(negedge clk);
      wr_s_en = 1'b1; wr_s_addr = r[ADDR_S-1:0];
      wr_s_data = {syn_words[2*r+1], syn_words[2*r]};
    end
    @(negedge clk); wr_s_en = 1'b0;

    @(negedge clk) load_start = 1'b1;
    @(negedge clk) load_start = 1'b0;
    wait (done);
    @(negedge clk);
    $display("loading finished at %0t", $time);

    @(negedge clk) start = 1'b1;
    @(negedge clk) start = 1'b0;
    $display("decode starts at %0t", $time);
    wait (done);
    @(negedge clk);
    $display("two iterations finished at %0t", $time);
    $finish;
  end

endmodule

`default_nettype wire

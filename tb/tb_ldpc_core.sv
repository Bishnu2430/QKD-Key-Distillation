`timescale 1ns/1ps
`default_nettype none
`include "v3_mother_1_r700_params.svh"

module tb_ldpc_core;

  localparam int unsigned ADDR_X    = $clog2(N_B);
  localparam int unsigned ADDR_S    = $clog2(M_B);
  localparam int unsigned ITER_BITS = 6;
  localparam int unsigned W_APP     = 8;
  localparam int unsigned APP_W     = Z * W_APP;          // 1024
  localparam int unsigned APP_WORDS = N_BITS / 8;         // 8192 lines
  localparam int unsigned S_WORDS   = M_BITS / 64;        // 308
  localparam int unsigned WORDS_PER_COL = Z / 8;          // 16

  localparam string DIR = "D:/QKD-Key-Distillation/tv/r700_q03_iters/";

  logic clk = 1'b0, rst_n = 1'b0;
  always #4 clk = ~clk;

  logic                 wr_app_en = 1'b0, wr_s_en = 1'b0, start = 1'b0;
  logic [ADDR_X-1:0]    wr_app_addr = '0, rd_app_addr = '0;
  logic [APP_W-1:0]     wr_app_data = '0;
  wire  [APP_W-1:0]     rd_app_data;
  logic [ADDR_S-1:0]    wr_s_addr = '0;
  logic [Z-1:0]         wr_s_data = '0;
  logic [ITER_BITS-1:0] n_iters = '0;
  wire  [ITER_BITS-1:0] iter_count;
  wire                  busy, done;

  ldpc_core dut (.*);

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

  task automatic load_app;
    begin
      for (int c = 0; c < N_B; c++) begin
        @(negedge clk);
        wr_app_en   = 1'b1;
        wr_app_addr = c[ADDR_X-1:0];
        wr_app_data = column_of(app_init, c);
      end
      @(negedge clk); wr_app_en = 1'b0;
    end
  endtask

  task automatic load_syn;
    begin
      for (int r = 0; r < M_B; r++) begin
        @(negedge clk);
        wr_s_en   = 1'b1;
        wr_s_addr = r[ADDR_S-1:0];
        wr_s_data = {syn_words[2*r+1], syn_words[2*r]};
      end
      @(negedge clk); wr_s_en = 1'b0;
    end
  endtask

  task automatic run_iters(input int unsigned n);
    begin
      @(negedge clk) begin n_iters = n[ITER_BITS-1:0]; start = 1'b1; end
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

  // one full check: reload the starting state, run n iterations, compare
  task automatic run_and_check(input int unsigned n, output int mismatches);
    string fname;
    begin
      $display("running %0d iteration(s) ...", n);
      load_app();
      run_iters(n);
      fname = $sformatf("app_after_i%03d.hex", n - 1);
      $readmemh({DIR, fname}, app_exp);
      compare($sformatf("after %0d iteration(s)", n), mismatches);
    end
  endtask

  // progress, so a long run does not look like a hang
  logic [ITER_BITS-1:0] last_iter = '0;
  always @(posedge clk) begin
    if (iter_count != last_iter) begin
      last_iter <= iter_count;
      if (iter_count != 0) $display("    iteration %0d done at %0t", iter_count, $time);
    end
  end

  int bad, errors = 0;

  initial begin
    $readmemh({DIR, "app_init.hex"}, app_init);
    $readmemh({DIR, "syndrome.hex"}, syn_words);

    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    load_syn();

    run_and_check(1, bad);  if (bad != 0) errors++;   // no old messages yet
    run_and_check(3, bad);  if (bad != 0) errors++;   // old messages in play
    run_and_check(6, bad);  if (bad != 0) errors++;   // the frame is decoded here

    if (errors == 0) $display("STAGE 3 PASSED");
    else             $display("STAGE 3 FAILED");
    $finish;
  end

  initial begin
    #50_000_000;
    $display("ERROR: timeout");
    $finish;
  end

endmodule

`default_nettype wire
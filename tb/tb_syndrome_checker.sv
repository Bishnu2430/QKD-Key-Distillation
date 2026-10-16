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
    $readmemh("D:/QKD-Key-Distillation/tv/r700_q03/frames/000_xhat.hex",     xhat_words);
    $readmemh("D:/QKD-Key-Distillation/tv/r700_q03/frames/000_syndrome.hex", syn_words);

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

    if (errors == 0) 
        $display("STAGE 1 PASSED");
    else             
        $display("STAGE 1 FAILED");
    $finish;
  end

  initial begin
    #5_000_000;
    $display("ERROR: timeout");
    $finish;
  end

endmodule

`default_nettype wire
`timescale 1ns/1ps
`default_nettype none
`include "v3_mother_1_r700_params.svh"

module tb_ldpc_decoder;

  localparam int unsigned ADDR_X    = $clog2(N_B);
  localparam int unsigned ADDR_S    = $clog2(M_B);
  localparam int unsigned ITER_BITS = 6;
  localparam int unsigned W_APP     = 8;
  localparam int unsigned APP_W     = Z * W_APP;
  localparam int unsigned KEY_WORDS = N_BITS / 64;        // 1024
  localparam int unsigned S_WORDS   = M_BITS / 64;        // 308
  localparam int unsigned MAX_IT    = 32;

  // Raise to 20 for the full set; 4 keeps a first run to a few minutes.
  localparam int unsigned N_FRAMES  = 20;

  localparam string DIR = "D:/QKD-Key-Distillation/tv/r700_q03/";

  logic clk = 1'b0, rst_n = 1'b0;
  always #4 clk = ~clk;

  logic                 wr_app_en = 1'b0, wr_s_en = 1'b0, start = 1'b0;
  logic [ADDR_X-1:0]    wr_app_addr = '0, rd_app_addr = '0;
  logic [APP_W-1:0]     wr_app_data = '0;
  wire  [APP_W-1:0]     rd_app_data;
  logic [ADDR_S-1:0]    wr_s_addr = '0;
  logic [Z-1:0]         wr_s_data = '0;
  logic [ITER_BITS-1:0] max_iters = MAX_IT[ITER_BITS-1:0];
  wire  [ITER_BITS-1:0] iter_count;
  wire                  busy, done, ok;

  ldpc_decoder dut (.*);

  logic [63:0] y_words    [0:KEY_WORDS-1];
  logic [63:0] xhat_words [0:KEY_WORDS-1];
  logic [63:0] syn_words  [0:S_WORDS-1];

  // cycles the DUT was busy, for the throughput number (within a cycle or two)
  longint unsigned cyc = 0;
  always @(posedge clk) begin
    if (start)     cyc <= 0;
    else if (busy) cyc <= cyc + 1;
  end

  // APP word for base column c: lane j is +A if its key bit is 0, else -A
  function automatic logic [APP_W-1:0] app_word_from_y(input int c, input int amp);
    logic [APP_W-1:0] out;
    int v;
    begin
      for (int j = 0; j < Z; j++) begin
        v = c*Z + j;
        out[j*W_APP +: W_APP] = y_words[v/64][v%64] ? (-amp[W_APP-1:0])
                                                    :   amp[W_APP-1:0];
      end
      app_word_from_y = out;
    end
  endfunction

  task automatic load_frame(input int amp);
    begin
      for (int c = 0; c < N_B; c++) begin
        @(negedge clk);
        wr_app_en   = 1'b1;
        wr_app_addr = c[ADDR_X-1:0];
        wr_app_data = app_word_from_y(c, amp);
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

  // read the APP array back and compare its sign bits with the expected bits
  task automatic compare_bits(output int mismatches);
    int v;
    begin
      mismatches = 0;
      for (int c = 0; c < N_B; c++) begin
        @(negedge clk) rd_app_addr = c[ADDR_X-1:0];
        @(negedge clk);
        for (int j = 0; j < Z; j++) begin
          v = c*Z + j;
          if (rd_app_data[j*W_APP + W_APP - 1] !== xhat_words[v/64][v%64]) begin
            if (mismatches < 5)
              $display("    bit %0d: expected %0b got %0b", v,
                       xhat_words[v/64][v%64], rd_app_data[j*W_APP + W_APP - 1]);
            mismatches++;
          end
        end
      end
    end
  endtask

  int    fd, rc, errors = 0, bad;
  int    e_frame, e_ok, e_iters, e_amp, d1, d2, d3, d4;
  string header;

  initial begin
    fd = $fopen({DIR, "expected.csv"}, "r");
    if (fd == 0) begin
      $display("ERROR: cannot open expected.csv");
      $finish;
    end
    rc = $fgets(header, fd);                                  // skip the header

    repeat (5) @(negedge clk);
    rst_n = 1'b1;

    for (int f = 0; f < N_FRAMES; f++) begin
      rc = $fscanf(fd, "%d,%d,%d,%d,%d,%d,%d,%d\n",
                   e_frame, e_ok, e_iters, e_amp, d1, d2, d3, d4);
      if (rc != 8) begin
        $display("ERROR: expected.csv row %0d did not parse (%0d fields)", f, rc);
        errors++;
        break;
      end

      $readmemh($sformatf("%sframes/%03d_y.hex",        DIR, f), y_words);
      $readmemh($sformatf("%sframes/%03d_syndrome.hex", DIR, f), syn_words);
      $readmemh($sformatf("%sframes/%03d_xhat.hex",     DIR, f), xhat_words);

      load_frame(e_amp);

      @(negedge clk) start = 1'b1;
      @(negedge clk) start = 1'b0;
      wait (done);
      @(negedge clk);

      $display("frame %0d: ok=%0b iters=%0d (expected ok=%0b iters=%0d), %0d cycles",
               f, ok, iter_count, e_ok[0], e_iters, cyc);

      if (ok !== e_ok[0]) begin
        $display("  MISMATCH: ok");
        errors++;
      end
      if (iter_count != e_iters[ITER_BITS-1:0]) begin
        $display("  MISMATCH: iteration count");
        errors++;
      end

      compare_bits(bad);
      if (bad != 0) begin
        $display("  MISMATCH: %0d decoded bits", bad);
        errors++;
      end
    end

    $fclose(fd);
    if (errors == 0) $display("STAGE 4 PASSED");
    else             $display("STAGE 4 FAILED (%0d problems)", errors);
    $finish;
  end

  initial begin
    #200_000_000;
    $display("ERROR: timeout");
    $finish;
  end

endmodule

`default_nettype wire
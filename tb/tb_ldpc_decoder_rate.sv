`timescale 1ns/1ps
`default_nettype none
`include "v3_mother_1_r700_params.svh"

module tb_ldpc_decoder_rate;

  localparam int unsigned ADDR_X    = $clog2(N_B);
  localparam int unsigned ADDR_S    = $clog2(M_B);
  localparam int unsigned ITER_BITS = 6;
  localparam int unsigned W_APP     = 8;
  localparam int unsigned APP_W     = Z * W_APP;
  localparam int unsigned KEY_WORDS = N_BITS / 64;        // 1024, an upper bound
  localparam int unsigned S_WORDS   = M_BITS / 64;        // 308
  localparam int unsigned MAX_IT    = 32;

  // ---- pick the vector set here -----------------------------------------
  // tv/r700_q03_m16s32/    QBER 3%, 16 punctured + 32 shortened, rate 0.703,
  //                        20 frames, 6-7 iterations each.  N_FRAMES up to 20.
  // tv/r700_q05_m16s125/   QBER 5%, 16 punctured + 125 shortened, rate 0.628,
  //                        4 frames, 13-17 iterations.        N_FRAMES up to 4.
  // Mind the q03 / q05 in the name: the two sets differ in QBER as well as in
  // how many columns are shortened.
  localparam string       DIR      = "D:/QKD-Key-Distillation/tv/r700_q05_m16s125/";
  localparam int unsigned N_FRAMES = 4;

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
  logic signed [W_APP-1:0] ch_amp = '0;
  logic [ITER_BITS-1:0] max_iters = MAX_IT[ITER_BITS-1:0];
  wire  [ITER_BITS-1:0] iter_count;
  wire                  busy, done, ok;

  ldpc_decoder_rate dut (.*);

  logic [63:0] y_words    [0:KEY_WORDS-1];
  logic [63:0] xhat_words [0:KEY_WORDS-1];
  logic [63:0] syn_words  [0:S_WORDS-1];
  logic [1:0]  mask_cls   [0:N_B-1];

  int n_key_cols;

  longint unsigned cyc = 0;
  always @(posedge clk) begin
    if (start)     cyc <= 0;
    else if (busy) cyc <= cyc + 1;
  end

  task automatic load_mask;
    begin
      n_key_cols = 0;
      for (int c = 0; c < N_B; c++) begin
        @(negedge clk);
        wr_m_en   = 1'b1;
        wr_m_addr = c[ADDR_X-1:0];
        wr_m_data = mask_cls[c];
        if (mask_cls[c] == 2'd0) n_key_cols++;
      end
      @(negedge clk); wr_m_en = 1'b0;
      $display("mask: %0d key columns, %0d key bits", n_key_cols, n_key_cols * Z);
    end
  endtask

  // one Z-bit word per key column, taken from the key bit stream in order
  task automatic load_key;
    begin
      for (int k = 0; k < n_key_cols; k++) begin
        @(negedge clk);
        wr_k_en   = 1'b1;
        wr_k_addr = k[ADDR_X-1:0];
        wr_k_data = {y_words[2*k+1], y_words[2*k]};
      end
      @(negedge clk); wr_k_en = 1'b0;
    end
  endtask

  task automatic load_syndrome;
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

  task automatic pulse(ref logic sig);
    begin
      @(negedge clk) sig = 1'b1;
      @(negedge clk) sig = 1'b0;
      wait (done);
      @(negedge clk);
    end
  endtask

  // compare the decoded key bits: key column k holds key bits k*Z .. k*Z+Z-1
  task automatic compare_key_bits(output int mismatches);
    int k, b;
    begin
      mismatches = 0;
      k = 0;
      for (int c = 0; c < N_B; c++) begin
        if (mask_cls[c] == 2'd0) begin
          @(negedge clk) rd_app_addr = c[ADDR_X-1:0];
          @(negedge clk);
          @(negedge clk);          // NEW: the block RAM output register adds a cycle
          for (int j = 0; j < Z; j++) begin
            b = k*Z + j;
            if (rd_app_data[j*W_APP + W_APP - 1] !== xhat_words[b/64][b%64]) begin
              if (mismatches < 5)
                $display("    key bit %0d (column %0d lane %0d): expected %0b got %0b",
                         b, c, j, xhat_words[b/64][b%64],
                         rd_app_data[j*W_APP + W_APP - 1]);
              mismatches++;
            end
          end
          k++;
        end
      end
    end
  endtask

  int    fd, rc, errors = 0, bad;
  int    e_frame, e_ok, e_iters, e_amp, d1, d2, d3, d4;
  string header;

  initial begin
    $display("vectors: %s", DIR);

    // Stop at once if the vectors are not where DIR says. Carrying on with an
    // empty mask and no file descriptor only produces confusing errors later.
    $readmemh({DIR, "mask.mem"}, mask_cls);
    if ($isunknown(mask_cls[0]))
      $fatal(1, "mask.mem did not load. DIR must be exactly one of %s or %s",
             "tv/r700_q03_m16s32/", "tv/r700_q05_m16s125/");

    fd = $fopen({DIR, "expected.csv"}, "r");
    if (fd == 0)
      $fatal(1, "cannot open expected.csv. DIR must be exactly one of %s or %s",
             "tv/r700_q03_m16s32/", "tv/r700_q05_m16s125/");
    rc = $fgets(header, fd);

    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    load_mask();

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

      load_key();
      load_syndrome();

      ch_amp = e_amp[W_APP-1:0];
      pulse(load_start);          // expand key + mask into the APP memory
      pulse(start);               // decode

      $display("frame %0d: ok=%0b iters=%0d (expected ok=%0b iters=%0d), %0d cycles",
               f, ok, iter_count, e_ok[0], e_iters, cyc);

      if (ok !== e_ok[0])                       begin $display("  MISMATCH: ok");    errors++; end
      if (iter_count != e_iters[ITER_BITS-1:0]) begin $display("  MISMATCH: iters"); errors++; end

      compare_key_bits(bad);
      if (bad != 0) begin
        $display("  MISMATCH: %0d key bits", bad);
        errors++;
      end
    end

    $fclose(fd);
    if (errors == 0) $display("STAGE 5 PASSED");
    else             $display("STAGE 5 FAILED (%0d problems)", errors);
    $finish;
  end

  initial begin
    #500_000_000;
    $display("ERROR: timeout");
    $finish;
  end

endmodule

`default_nettype wire
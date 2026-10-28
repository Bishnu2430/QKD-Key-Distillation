`timescale 1ns/1ps
`default_nettype none

// Stage 14: check the verification tag against the L2 model, over the real
// decoded keys of an existing vector set.
//
// Each frame is run twice:
//   once with the correct key      - the tag must equal the model's, and
//                                    tag_ok must assert against tag_ref
//   once with key bit 0 flipped    - the tag must equal the model's tag for
//                                    the corrupted key, and tag_ok must drop
//
// The second run is the one that matters. A tag unit that reproduces a number
// proves arithmetic; a tag unit that *changes* when the key changes proves it
// is doing the job of spec section 4.
module tb_toeplitz_tag;

  localparam int unsigned W = 64;
  localparam int unsigned T = 64;

  localparam string DIR = "D:/QKD-Key-Distillation/tv/r700_q05_m16s125/";
  localparam int unsigned N_FRAMES   = 4;
  localparam int unsigned MAX_WORDS  = 1100;

  logic clk = 1'b0, rst_n = 1'b0;
  always #4 clk = ~clk;

  logic           start = 1'b0;
  logic [T-1:0]   tag_ref = '0;
  logic [W-1:0]   in_data = '0;
  logic           in_valid = 1'b0, in_last = 1'b0;
  wire            in_ready;
  wire [T-1:0]    tag;
  wire            tag_valid, tag_ok, busy;

  toeplitz_tag #(.W(W), .T(T)) dut (
      .clk(clk), .rst_n(rst_n),
      .start(start), .tag_ref(tag_ref),
      .in_data(in_data), .in_valid(in_valid), .in_last(in_last),
      .in_ready(in_ready),
      .tag(tag), .tag_valid(tag_valid), .tag_ok(tag_ok), .busy(busy)
  );

  logic [63:0] seed_words [0:MAX_WORDS-1];
  logic [63:0] key_words  [0:MAX_WORDS-1];

  int    fd, rc, errors = 0;
  int    e_frame, e_nkey, e_seedbits;
  logic [63:0] e_tag, e_tag_bad;
  string header;
  int    n_key_words, n_seed_words;

  // Set the request at a negedge, check ready immediately and at every negedge
  // after, drop it one negedge past the one where ready was seen. Same rule as
  // the stage-12 AXI driver, and for the same reason: this slave drops ready
  // for three cycles while it primes the seed window.
  // A random gap before each word, because a free-running seed read passes a
  // back-to-back test and fails the moment the stream pauses: the seed fetch
  // runs a word ahead of the window and every tag after the first stall is
  // wrong. This is test T-IF-01's reason for randomising the handshake.
  int stall_seed = 32'h5EED_1234;

  task automatic send(input logic [63:0] d, input logic last);
    int gap;
    begin
      gap = $urandom(stall_seed) % 4;
      stall_seed = $urandom;
      repeat (gap) @(negedge clk);
      @(negedge clk);
      in_data = d; in_valid = 1'b1; in_last = last;
      while (!in_ready) @(negedge clk);
      @(negedge clk);
      in_valid = 1'b0; in_last = 1'b0;
    end
  endtask

  // Run one frame end to end and return what the DUT produced.
  task automatic run_frame(input int nkw, input int nsw, input logic flip,
                           output logic [63:0] got, output logic got_ok);
    begin
      @(negedge clk);
      start = 1'b1;
      @(negedge clk);
      start = 1'b0;

      for (int w = 0; w < nsw; w++) send(seed_words[w], w == nsw - 1);
      for (int w = 0; w < nkw; w++) begin
        logic [63:0] d;
        d = key_words[w];
        if (flip && w == 0) d[0] = ~d[0];
        send(d, w == nkw - 1);
      end

      while (!tag_valid) @(negedge clk);
      got    = tag;
      got_ok = tag_ok;
    end
  endtask

  logic [63:0] got;
  logic        got_ok;

  initial begin
    $display("vectors: %s", DIR);

    // $display + $finish rather than $fatal: xsim silently skips a $fatal
    // whose format carries a %s of a string parameter, and then runs on with
    // an invalid descriptor. This guard has to work, so it uses neither.
    fd = $fopen({DIR, "tags.csv"}, "r");
    if (fd == 0) begin
      $display("ERROR: cannot open %0stags.csv", DIR);
      $display("       run: uv run python scripts/export_tag_vectors.py --tv <dir>");
      $finish;
    end
    rc = $fgets(header, fd);

    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    for (int f = 0; f < N_FRAMES; f++) begin
      rc = $fscanf(fd, "%d,%d,%d,%h,%h\n", e_frame, e_nkey, e_seedbits,
                   e_tag, e_tag_bad);
      if (rc != 5) $fatal(1, "tags.csv: short read on frame %0d (rc=%0d)", f, rc);

      n_key_words  = e_nkey / 64;
      n_seed_words = (e_seedbits + 63) / 64;

      $readmemh($sformatf("%sframes/%03d_seed.hex", DIR, f), seed_words);
      $readmemh($sformatf("%sframes/%03d_xhat.hex", DIR, f), key_words);
      if ($isunknown(seed_words[0])) begin
        $display("ERROR: cannot read %0sframes/%03d_seed.hex", DIR, f);
        $finish;
      end

      // --- the correct key -------------------------------------------------
      tag_ref = e_tag;
      run_frame(n_key_words, n_seed_words, 1'b0, got, got_ok);

      $display("frame %0d: tag=%016x  (expected %016x)  ok=%0b", f, got, e_tag, got_ok);
      if (got !== e_tag) begin
        $display("  MISMATCH: tag");
        errors++;
      end
      if (got_ok !== 1'b1) begin
        $display("  MISMATCH: tag_ok should assert on the correct key");
        errors++;
      end

      // --- one bit of the key corrupted ------------------------------------
      run_frame(n_key_words, n_seed_words, 1'b1, got, got_ok);

      $display("          bit0 flipped -> %016x  (expected %016x)  ok=%0b",
               got, e_tag_bad, got_ok);
      if (got !== e_tag_bad) begin
        $display("  MISMATCH: tag of the corrupted key");
        errors++;
      end
      if (got_ok !== 1'b0) begin
        $display("  MISMATCH: tag_ok must drop when the key is wrong");
        errors++;
      end
    end

    $fclose(fd);
    if (errors == 0) $display("STAGE 14 PASSED");
    else             $display("STAGE 14 FAILED (%0d problems)", errors);
    $finish;
  end

  initial begin
    #20_000_000;
    $display("ERROR: timeout");
    $finish;
  end

endmodule

`default_nettype wire

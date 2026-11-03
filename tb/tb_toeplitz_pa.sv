`timescale 1ns/1ps
`default_nettype none

// Stage 15 testbench: privacy amplification against the L2 model.
//
// The oracle is scripts/export_pa_vectors.py, which computes the whole L-bit
// output in one numpy expression. The RTL computes it in L/B passes with a
// sliding seed window, so agreement is a real cross-check and not a
// restatement of the same loop.
//
// Two things are deliberately adversarial:
//
//   * out_ready is randomised. The emit phase is the only one that can stall,
//     and a chunk's four words must survive an arbitrary pause between any two
//     of them. A design that shifted acc on an unaccepted cycle would drop
//     words here and pass a tidier test.
//
//   * the input stream has random gaps. The seed and block phases are the only
//     ones with a handshake, and a free-running BRAM read would arrive a word
//     ahead of the window - the stage-14 bug this project has already paid for.
module tb_toeplitz_pa;

  localparam int unsigned W      = 64;
  localparam int unsigned B      = 256;
  localparam string       DIR    = "D:/QKD-Key-Distillation/tv/pa/n1024_l512/";
  localparam int unsigned N_BITS = 1024;
  localparam int unsigned L_BITS = 512;

  localparam int unsigned N_WORDS    = N_BITS / W;
  localparam int unsigned L_WORDS    = L_BITS / W;
  localparam int unsigned N_CHUNKS   = L_BITS / B;
  localparam int unsigned SEED_BITS  = N_BITS + L_BITS - 1;
  localparam int unsigned SEED_WORDS = (SEED_BITS + W - 1) / W;

  logic clk = 1'b0, rst_n = 1'b0;
  always #4 clk = ~clk;                 // 125 MHz

  logic           start = 1'b0;
  logic [15:0]    n_chunks;
  logic [W-1:0]   in_data = '0;
  logic           in_valid = 1'b0, in_last = 1'b0;
  wire            in_ready;
  wire  [W-1:0]   out_data;
  wire            out_valid, out_last;
  logic           out_ready = 1'b0;
  wire            busy, done;

  toeplitz_pa #(.W(W), .B(B), .BLK_DEPTH(2048), .SEED_DEPTH(3072)) dut (
      .clk(clk), .rst_n(rst_n),
      .start(start), .n_chunks(n_chunks),
      .in_data(in_data), .in_valid(in_valid), .in_last(in_last),
      .in_ready(in_ready),
      .out_data(out_data), .out_valid(out_valid), .out_last(out_last),
      .out_ready(out_ready),
      .busy(busy), .done(done)
  );

  logic [W-1:0] seed_words [SEED_WORDS];
  logic [W-1:0] blk_words  [N_WORDS];
  logic [W-1:0] exp_words  [L_WORDS];
  logic [W-1:0] got_words  [L_WORDS];

  int unsigned  got_n   = 0;
  int unsigned  errors  = 0;
  int unsigned  last_at = 0;
  int unsigned  cyc     = 0;
  int unsigned  cyc_hash = 0;
  logic         hashing = 1'b0;

  // Two counters, because they answer different questions. cyc is the whole
  // operation; cyc_hash starts when the block packet ends and is the N*L/(W*B)
  // term REQ-PERF-08 is about. The ingest between them is inflated here by the
  // driver's deliberate random gaps, so quoting only cyc would understate the
  // design and quoting only cyc_hash would ignore real work.
  int unsigned  packets = 0;   // in_last events: 1 = seed done, 2 = block done
  always @(posedge clk) begin
    if (busy)    cyc      <= cyc + 1;
    if (hashing) cyc_hash <= cyc_hash + 1;
    if (in_valid && in_ready && in_last) begin
      packets <= packets + 1;
      if (packets == 1) hashing <= 1'b1;
    end
    if (done) hashing <= 1'b0;
  end

  // xorshift32 rather than $random: unsigned, so the modulo cannot come out
  // negative, and identical in Verilator and xsim from the same seed.
  int unsigned rnd_state = 32'h1234_5678;
  function automatic int unsigned rnd();
    rnd_state ^= rnd_state << 13;
    rnd_state ^= rnd_state >> 17;
    rnd_state ^= rnd_state << 5;
    return rnd_state;
  endfunction

  // ---------------------------------------------------------------- the sink
  // out_ready is low 30% of cycles, so every emit word has to tolerate a pause
  // before it is accepted.
  always @(posedge clk) begin
    if (!rst_n) begin
      out_ready <= 1'b0;
    end else begin
      out_ready <= (rnd() % 100) < 70;
      if (out_valid && out_ready) begin
        if (got_n < L_WORDS) got_words[got_n] <= out_data;
        got_n <= got_n + 1;
        if (out_last) last_at <= got_n + 1;
      end
    end
  end

  // -------------------------------------------------------------- the driver
  // The handshake is checked at the negedge, in the middle of the cycle whose
  // posedge will do the accepting. in_ready is combinational from the state,
  // and the state cannot move without accepting a word, so the value read at
  // the negedge is the value present at that posedge. Polling it *after* the
  // edge instead deadlocks on the last word of a packet, because by then the
  // DUT has already left the receiving state - which is how the first version
  // of this testbench hung.
  task automatic send(input logic [W-1:0] d, input logic lastf);
    begin
      repeat (rnd() % 3) @(negedge clk);   // 0-2 idle cycles before the word
      @(negedge clk);
      in_data  = d;
      in_last  = lastf;
      in_valid = 1'b1;
      while (!in_ready) @(negedge clk);
      @(posedge clk);                      // accepted here
      @(negedge clk);
      in_valid = 1'b0;
      in_last  = 1'b0;
    end
  endtask

  int unsigned i, bad;

  initial begin
    $display("vectors: %s", DIR);
    $display("N=%0d L=%0d -> %0d block words, %0d seed words, %0d chunks",
             N_BITS, L_BITS, N_WORDS, SEED_WORDS, N_CHUNKS);

    // The project's file guards are $display + $finish, never $fatal: xsim
    // silently skips a $fatal whose format string carries a string parameter,
    // so a guard written that way never fires. Stage 14 learned this the hard
    // way.
    for (i = 0; i < SEED_WORDS; i++) seed_words[i] = {W{1'bx}};
    $readmemh({DIR, "seed.hex"}, seed_words);
    if (seed_words[0] === {W{1'bx}}) begin
      $display("ERROR: could not read %sseed.hex", DIR); $finish;
    end
    for (i = 0; i < N_WORDS; i++) blk_words[i] = {W{1'bx}};
    $readmemh({DIR, "blk.hex"}, blk_words);
    if (blk_words[0] === {W{1'bx}}) begin
      $display("ERROR: could not read %sblk.hex", DIR); $finish;
    end
    for (i = 0; i < L_WORDS; i++) exp_words[i] = {W{1'bx}};
    $readmemh({DIR, "out.hex"}, exp_words);
    if (exp_words[0] === {W{1'bx}}) begin
      $display("ERROR: could not read %sout.hex", DIR); $finish;
    end

    n_chunks = 16'(N_CHUNKS);
    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    start <= 1'b1; @(posedge clk); start <= 1'b0;
    @(posedge clk);

    for (i = 0; i < SEED_WORDS; i++) send(seed_words[i], i == SEED_WORDS - 1);
    for (i = 0; i < N_WORDS;    i++) send(blk_words[i],  i == N_WORDS    - 1);

    wait (done);
    @(posedge clk);

    // ------------------------------------------------------------- the check
    if (got_n != L_WORDS) begin
      $display("  MISMATCH: %0d output words, expected %0d", got_n, L_WORDS);
      errors++;
    end
    if (last_at != L_WORDS) begin
      $display("  MISMATCH: out_last fired at word %0d, expected %0d",
               last_at, L_WORDS);
      errors++;
    end
    bad = 0;
    for (i = 0; i < L_WORDS; i++)
      if (got_words[i] !== exp_words[i]) begin
        if (bad < 4)
          $display("  MISMATCH word %0d: got %016x expected %016x",
                   i, got_words[i], exp_words[i]);
        bad++;
      end
    if (bad != 0) begin
      $display("  MISMATCH: %0d of %0d output words", bad, L_WORDS);
      errors++;
    end

    $display("cycles: %0d total, %0d hashing (predicted ~%0d = %0d chunks x (%0d + 10))",
             cyc, cyc_hash, N_CHUNKS * (N_WORDS + 10), N_CHUNKS, N_WORDS);
    $display("throughput at 125 MHz: %.2f Mbit/s hashing, %.2f Mbit/s including ingest",
             real'(N_BITS) / (real'(cyc_hash) / 125.0),
             real'(N_BITS) / (real'(cyc) / 125.0));

    if (errors == 0) $display("STAGE 15 PASSED");
    else             $display("STAGE 15 FAILED (%0d problems)", errors);
    $finish;
  end

  initial begin
    #(64'd200_000_000);
    $display("ERROR: timeout");
    $finish;
  end

endmodule

`default_nettype wire

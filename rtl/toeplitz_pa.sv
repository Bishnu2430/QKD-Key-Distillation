`default_nettype none

// Stage 15: privacy amplification (docs/05-algorithm-spec.md section 5).
//
// A verified block of N bits is compressed to L <= N secret bits with the same
// Toeplitz family the stage-14 tag uses, over a public seed v of N + L - 1 bits:
//
//     k_i = XOR_j  v[i + j] AND x[j],   i = 0..L-1,  j = 0..N-1
//
// ---------------------------------------------------------------------------
// Why this cannot be stage 14 with a wider output
//
// The tag module computes all T = 64 output bits in one pass, because a single
// 2W-bit shift register covers every output bit's window when T <= W + 1. Here
// L is tens of thousands of bits, so that register would have to be L + W - 1
// bits wide and the AND-XOR array L x W wide - about 1.7 million LUTs at
// L = 65,536. Both are impossible.
//
// So this is the output-chunk method of the learning guide section 17.1 with a
// chunk NARROWER than the output: B = 256 bits are accumulated at a time, and
// the block is re-streamed once per chunk, L/B passes in all.
//
//     cycles  ~  N*L / (W*B)        (section 17.2)
//
// ---------------------------------------------------------------------------
// Why B = 256, and not 128 or 1024
//
// B is the one free parameter and it trades LUTs against time one for one.
// Stage 14 measured 2.5 AND-XOR terms per LUT on this device, and the array is
// W*B terms wide:
//
//     B      AND-XOR/cycle   LUTs (est.)   cycles at N=2^17, L=N/2   Mbit/s
//     128         8,192         3,300         1,048,576               15.6
//     256        16,384         6,550           524,288               31.1
//    1024        65,536        26,200           131,072              124.6
//
// REQ-PERF-08 asks for >= 25 Mbit/s at N = 2^17, so B = 128 fails it and
// B = 256 is the smallest chunk that passes. B = 1024 would be four times
// faster, but 26,200 LUTs on top of the 28,241 the stage-13 system already
// uses is 103% of the device and 1.5x REQ-IMP-03's 70% ceiling. B = 256 lands
// at about 65%.
//
// B must be a multiple of W. Output chunk c starts at seed bit c*B, so a
// word-aligned B makes the seed read pointer start at word c*B/W and the
// window slide by whole words. A B that was not a multiple of W would need a
// bit-level barrel shifter on a 319-bit register, every cycle, for nothing.
//
// ---------------------------------------------------------------------------
// The window
//
// At block word s of chunk c the array needs seed bits
//
//     c*B + s*W  ..  c*B + s*W + B + W - 2
//
// which is B + W - 1 = 319 bits, held in a 5-word (320-bit) shift register.
// For output bit b the window is vwin[b +: W], so the widest index touched is
// B-1 + W-1 = 318 of 319. One word shifts in per block word, as in stage 14 -
// the register is simply longer here, and the base address is per chunk.
//
// ---------------------------------------------------------------------------
// The interface: two packets in, one out, TLAST-delimited
//
//   packet 1   seed    ceil((N + L - 1)/W) words
//   packet 2   block   N/W words
//   out        key     L/W words, four at a time as each chunk completes
//
// N is never told to the module: TLAST ends the block packet and the word
// count is kept, because the block has to be re-streamed from BRAM L/B times
// and the module is the thing that does the re-streaming. L cannot be inferred
// from any stream, so n_chunks = L/B is an input, latched at start. Same
// convention as ldpc_axi and toeplitz_tag, so an AXI wrapper is mechanical.
//
// L is therefore a multiple of B = 256. The PS rounds the finite-key length
// down to a multiple of 256, which discards at most 255 bits of a 65,536-bit
// key - 0.4% - and is safe in the direction that matters: the first L' rows of
// a Toeplitz matrix are themselves a Toeplitz matrix, so a prefix of the output
// is a valid 2-universal hash of the same block.
module toeplitz_pa #(
    parameter int unsigned W          = 64,    // stream width
    parameter int unsigned B          = 256,   // output chunk, see above
    parameter int unsigned BLK_DEPTH  = 2048,  // N up to BLK_DEPTH*W = 131,072
    parameter int unsigned SEED_DEPTH = 3072   // N + L - 1 up to 196,608
) (
    input  wire              clk,
    input  wire              rst_n,

    input  wire              start,      // pulse: begin a block
    input  wire [15:0]       n_chunks,   // L / B, latched at start

    input  wire [W-1:0]      in_data,
    input  wire              in_valid,
    input  wire              in_last,
    output logic             in_ready,

    output logic [W-1:0]     out_data,
    output logic             out_valid,
    output logic             out_last,
    input  wire              out_ready,

    output logic             busy,
    output logic             done
);

  // A chunk that is not a whole number of words would need a barrel shifter on
  // the seed window; a chunk narrower than the word would make no sense.
  initial begin
    if (B % W != 0)
      $fatal(1, "toeplitz_pa: B=%0d must be a multiple of W=%0d", B, W);
  end

  localparam int unsigned VWIN_W     = B + W - 1;             // 319
  localparam int unsigned VWIN_WORDS = (VWIN_W + W - 1) / W;  // 5
  localparam int unsigned VREG_W     = VWIN_WORDS * W;        // 320
  localparam int unsigned EMIT_WORDS = B / W;                 // 4, also the
  localparam int unsigned CHUNK_STEP = B / W;                 // seed word step

  localparam int unsigned BAW = $clog2(BLK_DEPTH);
  localparam int unsigned SAW = $clog2(SEED_DEPTH);
  localparam int unsigned PRIME_LAST = VWIN_WORDS;            // 5, see S_PRIME

  typedef enum logic [2:0] {
    S_IDLE, S_SEED, S_BLOCK, S_PRIME, S_PASS, S_EMIT, S_DONE
  } state_t;

  state_t                  st;
  (* ram_style = "block" *) logic [W-1:0] seed_mem [SEED_DEPTH];
  (* ram_style = "block" *) logic [W-1:0] blk_mem  [BLK_DEPTH];

  logic [SAW-1:0]          swr, vrd, chunk_base;
  logic [BAW-1:0]          bwr, brd;
  // n_words reaches BLK_DEPTH, which is one past what BAW bits can hold.
  logic [BAW:0]            n_words, s_cnt;
  logic [W-1:0]            seed_q, blk_q;
  logic [VREG_W-1:0]       vwin;
  logic [B-1:0]            acc;
  logic [2:0]              prime_cnt;
  logic [15:0]             chunk_cnt, chunk_total;
  logic [2:0]              emit_cnt;

  // Both memories are written in one phase and read in another, so each infers
  // a simple dual-port block RAM with one-cycle read latency - which is what
  // the priming sequence below assumes.
  //
  // Stage 14 needed these enables gated, because there the window advanced
  // with a stream that could stall, and a free-running read arrived a word
  // ahead of the window. Here the pass reads the block out of BRAM and cannot
  // stall, so the gating is NOT load-bearing: a mutation to seed_rd_en = 1'b1
  // passes every vector. It is kept because S_PASS is the only phase that may
  // ever gain a stall, and because an enable that states when the read matters
  // is worth more than one cycle of saved toggling.
  logic seed_rd_en, blk_rd_en;
  assign seed_rd_en = (st == S_PRIME) || (st == S_PASS);
  assign blk_rd_en  = (st == S_PRIME && prime_cnt == 3'(PRIME_LAST)) || (st == S_PASS);

  always_ff @(posedge clk) begin
    if (st == S_SEED  && in_valid) seed_mem[swr] <= in_data;
    if (st == S_BLOCK && in_valid) blk_mem[bwr]  <= in_data;
    if (seed_rd_en)                seed_q <= seed_mem[vrd];
    if (blk_rd_en)                 blk_q  <= blk_mem[brd];
  end

  // The whole arithmetic of the stage, in four lines. B = 256 of these, each a
  // 64-term AND-XOR: about 22 LUT6 of first level and a three-deep XOR tree.
  logic [B-1:0] contrib, acc_next;
  always_comb
    for (int b = 0; b < B; b++)
      contrib[b] = ^(vwin[b +: W] & blk_q);
  assign acc_next = acc ^ contrib;

  // The pass runs from BRAM, so it never stalls; only the emit phase can.
  assign in_ready = (st == S_SEED) || (st == S_BLOCK);

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      st          <= S_IDLE;
      acc         <= '0;
      vwin        <= '0;
      swr         <= '0;
      bwr         <= '0;
      vrd         <= '0;
      brd         <= '0;
      chunk_base  <= '0;
      n_words     <= '0;
      s_cnt       <= '0;
      prime_cnt   <= '0;
      chunk_cnt   <= '0;
      chunk_total <= '0;
      emit_cnt    <= '0;
      out_data    <= '0;
      out_valid   <= 1'b0;
      out_last    <= 1'b0;
      busy        <= 1'b0;
      done        <= 1'b0;
    end else begin
      case (st)

        S_IDLE: begin
          if (start) begin
            st          <= S_SEED;
            busy        <= 1'b1;
            done        <= 1'b0;
            chunk_total <= n_chunks;
            swr         <= '0;
            bwr         <= '0;
            chunk_cnt   <= '0;
            chunk_base  <= '0;
          end
        end

        S_SEED: if (in_valid) begin
          swr <= swr + 1'b1;
          if (in_last) st <= S_BLOCK;
        end

        // N arrives rather than being configured: the word count is kept
        // because the block is re-streamed from here, L/B times.
        S_BLOCK: if (in_valid) begin
          bwr <= bwr + 1'b1;
          if (in_last) begin
            n_words   <= bwr + 1'b1;
            st        <= S_PRIME;
            vrd       <= chunk_base;
            brd       <= '0;
            acc       <= '0;
            prime_cnt <= '0;
          end
        end

        // Six cycles, because the read is a cycle behind the address:
        //   count 0       address chunk_base issued, seed_q stale - no shift
        //   counts 1..5   seed_q = w[base+0..4], shift each one in
        // and on entry to S_PASS the next read (w[base+5]) is in flight, which
        // is the word the first pass cycle shifts in. The last prime cycle also
        // issues the read of block word 0, so blk_q is ready at pass cycle 0.
        S_PRIME: begin
          if (vrd < SAW'(SEED_DEPTH - 1)) vrd <= vrd + 1'b1;
          if (prime_cnt != 3'd0) vwin <= {seed_q, vwin[VREG_W-1:W]};
          if (prime_cnt == 3'(PRIME_LAST)) begin
            brd   <= BAW'(1);
            s_cnt <= '0;
            st    <= S_PASS;
          end
          prime_cnt <= prime_cnt + 1'b1;
        end

        // At block word s of chunk c:
        //   vwin   = seed words base+s .. base+s+4, base = c*B/W
        //   blk_q  = block word s
        //   seed_q = seed word base+s+5, the one word s+1 shifts in
        S_PASS: begin
          acc  <= acc_next;
          vwin <= {seed_q, vwin[VREG_W-1:W]};
          if (vrd < SAW'(SEED_DEPTH - 1)) vrd <= vrd + 1'b1;
          if (brd < BAW'(BLK_DEPTH  - 1)) brd <= brd + 1'b1;
          if (s_cnt == n_words - 1'b1) begin
            st        <= S_EMIT;
            emit_cnt  <= '0;
            out_valid <= 1'b1;
            out_data  <= acc_next[W-1:0];
            out_last  <= (chunk_cnt == chunk_total - 1'b1) &&
                         (EMIT_WORDS == 1);
          end else begin
            s_cnt <= s_cnt + 1'b1;
          end
        end

        // B/W words out, low word first - LSB-first packing, spec section 2,
        // so output word c*B/W + k holds key bits c*B + k*W upwards. This is
        // the only phase that can stall, and acc only shifts on an accepted
        // word, so a slow consumer costs cycles and nothing else.
        S_EMIT: if (out_ready) begin
          if (emit_cnt == 3'(EMIT_WORDS - 1)) begin
            out_valid <= 1'b0;
            out_last  <= 1'b0;
            if (chunk_cnt == chunk_total - 1'b1) begin
              st <= S_DONE;
            end else begin
              chunk_cnt  <= chunk_cnt + 1'b1;
              chunk_base <= chunk_base + SAW'(CHUNK_STEP);
              vrd        <= chunk_base + SAW'(CHUNK_STEP);
              brd        <= '0;
              acc        <= '0;
              vwin       <= '0;
              prime_cnt  <= '0;
              st         <= S_PRIME;
            end
          end else begin
            acc      <= acc >> W;
            out_data <= acc[2*W-1:W];
            emit_cnt <= emit_cnt + 1'b1;
            out_last <= (chunk_cnt == chunk_total - 1'b1) &&
                        (emit_cnt == 3'(EMIT_WORDS - 2));
          end
        end

        S_DONE: begin
          done <= 1'b1;
          busy <= 1'b0;
          st   <= S_IDLE;
        end

        default: st <= S_IDLE;
      endcase
    end
  end

endmodule

`default_nettype wire

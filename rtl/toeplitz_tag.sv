`default_nettype none

// Stage 14: error verification (docs/05-algorithm-spec.md section 4).
//
// After a frame decodes, Alice draws a public seed v of n_key + t - 1 bits and
// both sides compute a t = 64 bit Toeplitz tag over their copy of the key:
//
//     tag_i = XOR_j  v[i + j] AND x[j],   i = 0..t-1,  j = 0..n_key-1
//
// Toeplitz hashing is 2-universal, so two different keys collide with
// probability at most 2^-64. If the tags differ the frame is discarded.
//
// ---------------------------------------------------------------------------
// The architecture, and the one thing that makes this version simple
//
// This is the output-chunk method of the learning guide section 17.1 with the
// chunk equal to the whole output: B = t = 64. Because the tag is exactly as
// wide as the data word, ONE pass over the key suffices and the input is never
// re-streamed. Stage 15 cannot do this - privacy amplification wants an output
// of thousands of bits, so it needs several chunks and a pass per chunk.
//
// Per key word we need a 2W-bit window of the seed. For output bit i the
// window is vwin[i +: W], so the widest index touched is T-1 + W-1 = 126 of
// 127. That is where the T <= W + 1 assertion below comes from: it is what
// lets a single 128-bit shift register serve all 64 output bits at once.
//
// Per cycle that is 64 outputs x 64 AND-XOR terms. A LUT6 computes three
// AND-XOR pairs at once, so each output bit is 22 LUTs of first level plus a
// short XOR tree - about three LUT levels, which closes comfortably.
//
// ---------------------------------------------------------------------------
// The interface: one stream, two packets, TLAST-delimited
//
//   packet 1   seed   ceil((n_key + T - 1) / W) words
//   packet 2   key    n_key / W words
//
// Same convention as ldpc_axi, so wrapping this for AXI later is mechanical.
// n_key is never told to the module - TLAST says when the key ends, which
// matters because n_key depends on the rate mask. n_key is always a multiple
// of Z = 128 and therefore of W = 64, so no partial word can arrive.
module toeplitz_tag #(
    parameter int unsigned W          = 64,    // stream width
    parameter int unsigned T          = 64,    // tag bits, spec section 4
    parameter int unsigned SEED_DEPTH = 1032   // >= ceil((N_BITS + T - 1)/W) + 3
) (
    input  wire              clk,
    input  wire              rst_n,

    input  wire              start,      // pulse: begin a frame
    input  wire [T-1:0]      tag_ref,    // Alice's tag, for the comparison

    input  wire [W-1:0]      in_data,
    input  wire              in_valid,
    input  wire              in_last,
    output logic             in_ready,

    output logic [T-1:0]     tag,
    output logic             tag_valid,
    output logic             tag_ok,     // tag == tag_ref
    output logic             busy
);

  // A single shift register can only cover every output bit's window while the
  // tag is no wider than the data word. Stage 15 relaxes this with chunking.
  initial begin
    if (T > W + 1)
      $fatal(1, "toeplitz_tag: T=%0d exceeds W+1=%0d; needs the chunked form", T, W + 1);
  end

  localparam int unsigned AW = $clog2(SEED_DEPTH);

  typedef enum logic [2:0] {
    S_IDLE, S_SEED, S_PRIME, S_KEY, S_DONE
  } state_t;

  state_t                st;
  (* ram_style = "block" *) logic [W-1:0] seed_mem [SEED_DEPTH];
  logic [AW-1:0]         wr_ptr, vrd;
  logic [W-1:0]          seed_q;
  logic [2*W-1:0]        vwin;
  logic [T-1:0]          acc;
  logic [1:0]            prime_cnt;

  // Write while receiving the seed, read while walking the key. The two phases
  // never overlap, so this infers a simple dual-port block RAM with a one-cycle
  // read latency - which is exactly what the priming sequence below assumes.
  //
  // The read enable is NOT free-running, and that is the whole correctness
  // argument for stalls. vrd only advances on an accepted word, so a
  // free-running read would re-issue the *next* address during an idle cycle
  // and seed_q would arrive a word ahead of the window. Gating the enable the
  // same way vrd is gated makes seed_q hold its value for as long as the
  // stream is stalled.
  logic seed_rd_en;
  assign seed_rd_en = (st == S_PRIME) || (st == S_KEY && in_valid);

  always_ff @(posedge clk) begin
    if (st == S_SEED && in_valid) seed_mem[wr_ptr] <= in_data;
    if (seed_rd_en)               seed_q <= seed_mem[vrd];
  end

  // The whole arithmetic of the stage, in four lines.
  logic [T-1:0] contrib;
  always_comb
    for (int i = 0; i < T; i++)
      contrib[i] = ^(vwin[i +: W] & in_data);

  assign in_ready = (st == S_SEED) || (st == S_KEY);

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      st        <= S_IDLE;
      acc       <= '0;
      vwin      <= '0;
      wr_ptr    <= '0;
      vrd       <= '0;
      prime_cnt <= '0;
      tag       <= '0;
      tag_valid <= 1'b0;
      tag_ok    <= 1'b0;
      busy      <= 1'b0;
    end else begin
      case (st)

        S_IDLE: begin
          if (start) begin
            st        <= S_SEED;
            busy      <= 1'b1;
            tag_valid <= 1'b0;
            wr_ptr    <= '0;
            vrd       <= '0;
            acc       <= '0;
            prime_cnt <= '0;
          end
        end

        S_SEED: if (in_valid) begin
          wr_ptr <= wr_ptr + 1'b1;
          if (in_last) begin
            st        <= S_PRIME;
            vrd       <= '0;
            prime_cnt <= 2'd0;
          end
        end

        // Three cycles, because the read is a cycle behind the address:
        //   count 0  address 0 issued, seed_q still stale - do not shift
        //   count 1  seed_q = w0, shift it in
        //   count 2  seed_q = w1, shift it in -> vwin = {w1, w0}
        // and on entry to S_KEY the next read (w2) is already in flight.
        S_PRIME: begin
          vrd <= vrd + 1'b1;
          if (prime_cnt != 2'd0) vwin <= {seed_q, vwin[2*W-1:W]};
          prime_cnt <= prime_cnt + 1'b1;
          if (prime_cnt == 2'd2) st <= S_KEY;
        end

        // At key word s: vwin = {w[s+1], w[s]} and seed_q = w[s+2].
        // Everything is gated on in_valid, so a stall holds the window and
        // re-reads the same address rather than losing a seed word.
        S_KEY: if (in_valid) begin
          acc  <= acc ^ contrib;
          vwin <= {seed_q, vwin[2*W-1:W]};
          if (vrd < AW'(SEED_DEPTH - 1)) vrd <= vrd + 1'b1;
          if (in_last) st <= S_DONE;
        end

        S_DONE: begin
          tag       <= acc;
          tag_ok    <= (acc == tag_ref);
          tag_valid <= 1'b1;
          busy      <= 1'b0;
          st        <= S_IDLE;
        end

        default: st <= S_IDLE;
      endcase
    end
  end

endmodule

`default_nettype wire

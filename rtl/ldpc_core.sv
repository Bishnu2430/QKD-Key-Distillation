`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Stage 3: the whole decoder loop - every layer, every iteration, with the
// check messages of the previous iteration read back from memory.
//
// New compared with stage 2 (which assumed R_old = 0):
//   * cn_mem - one compressed record per (layer, lane): min1, min2, the index
//     of the minimum, and one sign bit per edge position. Read at the start of
//     a layer, written at the end. It is a lossless encoding of every message
//     that layer sent, in a quarter of the bits.
//   * T = sat(L - R_old) in both passes, reconstructed from that record.
//   * a layer counter and an iteration counter around the stage-2 schedule.
//
// Everything else - the shared lane rotator, the minimum finder, the
// saturating adds, the one-read-one-write memory discipline - is stage 2
// unchanged, including the two-state split that lets one rotator serve both
// the read and the write-back.
module ldpc_core (
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
    input  wire [ITER_BITS-1:0]     n_iters,       // NEW: how many iterations to run
    output logic                    busy,
    output logic                    done,
    output logic [ITER_BITS-1:0]    iter_count     // NEW: iterations completed
);

  // ------------------------------------------------------------ parameters
  localparam int unsigned ADDR_X    = $clog2(N_B);          // 9
  localparam int unsigned ADDR_S    = $clog2(M_B);          // 8
  localparam int unsigned ADDR_E    = $clog2(N_EDGES);      // 11
  localparam int unsigned W_APP     = 8;                    // spec 2.1
  localparam int unsigned W_MSG     = 6;
  localparam int          MAX_APP   = 127;  // signed: sat_add compares against it
  localparam int unsigned MAX_MSG   = 31;   // unsigned: only compared with |T|
  localparam int unsigned APP_W     = Z * W_APP;            // 1024 bits per column
  localparam int unsigned IDX_BITS  = $clog2(MAX_ROW_DEG + 1);
  localparam int unsigned ITER_BITS = 6;                    // NEW: up to 63 iterations

  // NEW: check-node record layout, per lane. min1 and min2 are stored in
  // MAG_BITS = 6 bits, which holds 0..32 - the sentinel value MAX_MSG+1
  // included, so nothing is lost even on a degree-1 row that never exists.
  localparam int unsigned MAG_BITS = W_MSG;                   // 6
  localparam int unsigned IDX_LO   = 2 * MAG_BITS;            // 12
  localparam int unsigned SGN_LO   = IDX_LO + IDX_BITS;       // 16
  localparam int unsigned CN_BITS  = SGN_LO + MAX_ROW_DEG;    // 30 bits per check
  localparam int unsigned CN_W     = Z * CN_BITS;             // 3840 bits per layer

  // --------------------------------------------------------------- state
  typedef enum logic [3:0] {
    S_IDLE, S_CLEAR, S_L_START, S_SETUP,
    S_A_ROM, S_A_MEM, S_A_ACC,
    S_B_SETUP, S_B_ROM, S_B_MEM, S_B_ROT, S_B_WR,
    S_L_END, S_DONE
  } state_t;

  state_t                 state;
  logic [ADDR_E:0]        e_start, e_end, e_idx;
  logic [IDX_BITS-1:0]    pos;
  logic [EDGE_BITS-1:0]   rom_q;
  logic [SHIFT_BITS-1:0]  shift_q;
  logic [COL_BITS-1:0]    col_q;
  logic [ADDR_S-1:0]      layer_q, clr_ptr;            // NEW
  logic [ITER_BITS-1:0]   iter_q, iters_q;             // NEW

  logic [W_MSG:0]         min1 [Z];      // one bit wider than W_MSG for the sentinel
  logic [W_MSG:0]         min2 [Z];
  logic [IDX_BITS-1:0]    idx  [Z];
  logic                   sgn  [Z];      // running sign product, 1 = negative
  logic [MAX_ROW_DEG-1:0] sgn_bits [Z];  // NEW: this layer's sign, one bit per edge
  logic [Z-1:0]           syn_q;

  logic [CN_W-1:0]        old_rec;       // NEW: the record read back for this layer
  logic [Z-1:0]           old_par;       // NEW: parity of each lane's stored signs
  logic [APP_W-1:0]       wb_q;          // write-back word, held for the rotator

  assign iter_count = iter_q;

  // --------------------------------------------------------------- memories
  logic [APP_W-1:0]      app_mem  [N_B];
  logic [Z-1:0]          syn_mem  [M_B];
  logic [EDGE_BITS-1:0]  edge_rom [N_EDGES];
  logic [15:0]           layer_ptr_rom [M_B+1];

  // NEW. ram_style is not optional: 154 entries is shallow enough that Vivado
  // may decide this is distributed RAM, and 591,360 bits of LUT RAM would eat
  // the device. Forcing block RAM also keeps it off the LUT budget.
  (* ram_style = "block" *)
  logic [CN_W-1:0]       cn_mem   [M_B];

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
  // ONE read port, ONE write port, one always_ff. This is what makes it a BRAM.
  logic [ADDR_X-1:0] app_raddr;
  logic [APP_W-1:0]  app_q;
  logic              app_we;
  logic [ADDR_X-1:0] app_waddr;
  logic [APP_W-1:0]  app_wdata;

  assign rd_app_data = app_q;

  // --------------------------------------------- the one and only rotator
  logic [APP_W-1:0]      rot_in, rot_out;
  logic [SHIFT_BITS-1:0] rot_amt;

  always_comb begin
    if (state == S_B_WR) begin
      rot_in  = wb_q;
      rot_amt = (Z - shift_q) & (Z - 1);   // inverse: back to column order
    end else begin
      rot_in  = app_q;
      rot_amt = shift_q;                   // forward: into check order
    end
    rot_out = rot_lanes(rot_in, rot_amt);
  end

  // --------------------------------- NEW: T = sat(L - R_old), for every lane
  // R_old is rebuilt from the record this layer wrote last iteration. In
  // iteration 1 the record is all zeros, so this reduces to T = L and the
  // module behaves exactly like stage 2.
  logic signed [W_APP-1:0]  t_lane [Z];

  logic signed [W_APP-1:0]  o_l;
  logic [MAX_ROW_DEG-1:0]   o_vec;
  logic [W_APP-1:0]         o_mag;
  logic [W_MSG:0]           o_nrm;
  logic signed [W_APP+1:0]  o_val;
  logic                     o_neg;

  always_comb begin
    for (int i = 0; i < Z; i++) begin
      o_l   = rot_out[i*W_APP +: W_APP];
      o_vec = old_rec[i*CN_BITS + SGN_LO +: MAX_ROW_DEG];
      o_mag = (pos == old_rec[i*CN_BITS + IDX_LO +: IDX_BITS])
              ? {2'b00, old_rec[i*CN_BITS + MAG_BITS +: MAG_BITS]}   // min2
              : {2'b00, old_rec[i*CN_BITS            +: MAG_BITS]};  // min1
      o_nrm = (o_mag >> 1) + (o_mag >> 2);              // alpha = 0.75, truncating
      o_neg = syn_q[i] ^ old_par[i] ^ o_vec[pos];       // sign of the old message
      o_val = o_neg ? -$signed({2'b00, o_nrm}) : $signed({2'b00, o_nrm});
      t_lane[i] = sat_add(o_l, -o_val);                 // T = sat(L - R_old)
    end
  end

  // ------------------------------------- the new message, added back in pass B
  logic [APP_W-1:0]        new_word;
  logic [W_APP-1:0]        n_mag;
  logic [W_MSG:0]          n_nrm;
  logic signed [W_APP+1:0] n_val;
  logic                    n_neg;

  always_comb begin
    for (int i = 0; i < Z; i++) begin
      n_mag = (pos == idx[i]) ? {1'b0, min2[i]} : {1'b0, min1[i]};
      n_nrm = (n_mag >> 1) + (n_mag >> 2);
      n_neg = sgn[i] ^ syn_q[i] ^ t_lane[i][W_APP-1];
      n_val = n_neg ? -$signed({2'b00, n_nrm}) : $signed({2'b00, n_nrm});
      new_word[i*W_APP +: W_APP] = sat_add(t_lane[i], n_val);
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
      app_wdata = rot_out;                 // the same rotator, inverse direction
    end
  end

  always_ff @(posedge clk) begin
    if (app_we) app_mem[app_waddr] <= app_wdata;
    app_q <= app_mem[app_raddr];
  end

  // ------------------------------------------- NEW: check-record memory ports
  // Same discipline as app_mem: one muxed write port, one read port, one
  // always_ff. The read address is simply the current layer; the write is
  // either the clearing pass or the record this layer just produced.
  logic [ADDR_S-1:0] cn_raddr, cn_waddr;
  logic              cn_we;
  logic [CN_W-1:0]   cn_wdata, cn_q, rec_w;

  always_comb begin
    for (int i = 0; i < Z; i++)
      rec_w[i*CN_BITS +: CN_BITS] = {sgn_bits[i], idx[i],
                                     min2[i][MAG_BITS-1:0], min1[i][MAG_BITS-1:0]};
  end

  always_comb begin
    cn_raddr = layer_q;
    cn_we    = (state == S_CLEAR) || (state == S_L_END);
    cn_waddr = (state == S_CLEAR) ? clr_ptr : layer_q;
    cn_wdata = (state == S_CLEAR) ? '0      : rec_w;
  end

  always_ff @(posedge clk) begin
    if (cn_we) cn_mem[cn_waddr] <= cn_wdata;
    cn_q <= cn_mem[cn_raddr];
  end

  // --------------------------------------------------------------- control
  logic signed [W_APP-1:0] a_t;
  logic [W_APP-1:0]        a_m;
  logic [W_MSG:0]          a_a;

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
            busy    <= 1'b1;
            iters_q <= (n_iters == '0) ? 1'b1 : n_iters;   // 0 would never finish
            iter_q  <= '0;
            clr_ptr <= '0;
            state   <= S_CLEAR;
          end
        end

        // NEW: iteration 1 has no old messages, so every record starts at zero.
        // One layer per cycle, M_B cycles, once per decode.
        S_CLEAR: begin
          if (clr_ptr == M_B - 1) begin
            layer_q <= '0;
            state   <= S_L_START;
          end else begin
            clr_ptr <= clr_ptr + 1'b1;
          end
        end

        // NEW: cn_raddr is layer_q now, so the record arrives in cn_q next cycle
        S_L_START: state <= S_SETUP;

        S_SETUP: begin
          old_rec <= cn_q;                                      // NEW
          for (int i = 0; i < Z; i++)                           // NEW
            old_par[i] <= ^cn_q[i*CN_BITS + SGN_LO +: MAX_ROW_DEG];
          e_start <= layer_ptr_rom[layer_q];
          e_end   <= layer_ptr_rom[layer_q + 1];
          e_idx   <= layer_ptr_rom[layer_q];
          pos     <= '0;
          syn_q   <= syn_mem[layer_q];
          for (int i = 0; i < Z; i++) begin
            min1[i]     <= MAX_MSG + 1;      // sentinel: larger than any |T|
            min2[i]     <= MAX_MSG + 1;
            idx[i]      <= '0;
            sgn[i]      <= 1'b0;
            sgn_bits[i] <= '0;               // NEW
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

        S_A_ACC: begin                       // t_lane is valid this cycle
          for (int i = 0; i < Z; i++) begin
            a_t = t_lane[i];                                   // was: rotated app_q
            a_m = a_t[W_APP-1] ? (-a_t) : a_t;                 // |T|
            a_a = (a_m > MAX_MSG) ? MAX_MSG[W_MSG:0] : a_m[W_MSG:0];
            sgn[i]           <= sgn[i] ^ a_t[W_APP-1];         // sign product
            sgn_bits[i][pos] <= a_t[W_APP-1];                  // NEW: keep each sign
            if (a_a < min1[i]) begin                           // strict: first wins
              min2[i] <= min1[i];
              min1[i] <= a_a;
              idx[i]  <= pos;
            end else if (a_a < min2[i]) begin
              min2[i] <= a_a;
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
          if (e_idx == e_end) state <= S_L_END;      // was: S_DONE
          else begin
            rom_q <= edge_rom[e_idx];
            state <= S_B_MEM;
          end
        end

        S_B_MEM: begin
          col_q   <= rom_q[COL_BITS-1:0];
          shift_q <= rom_q[EDGE_BITS-1:COL_BITS];
          state   <= S_B_ROT;
        end

        S_B_ROT: begin                       // app_q holds the column: compute and hold
          wb_q  <= new_word;
          state <= S_B_WR;
        end

        S_B_WR: begin                        // the memory writes rot_out this cycle
          e_idx <= e_idx + 1'b1;
          pos   <= pos + 1'b1;
          state <= S_B_ROM;
        end

        // NEW: the cn_mem block writes rec_w this cycle; then advance
        S_L_END: begin
          if (layer_q == M_B - 1) begin
            layer_q <= '0;
            iter_q  <= iter_q + 1'b1;
            state   <= ((iter_q + 1'b1) == iters_q) ? S_DONE : S_L_START;
          end else begin
            layer_q <= layer_q + 1'b1;
            state   <= S_L_START;
          end
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
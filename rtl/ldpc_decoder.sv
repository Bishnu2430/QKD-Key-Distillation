`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Stage 4: the decoder with early termination.
//
// New compared with stage 3:
//   * a third pass over the edges at the end of every iteration, which XORs
//     the hard decisions into a per-lane parity and compares it with the
//     stored syndrome. It reuses the rotator, the APP port and both ROMs, so
//     it costs almost no logic - only time.
//   * ok and iter_count, defined as the model defines them: iter_count is the
//     1-based iteration after which the syndrome matched, or max_iters.
//   * no multiplexer on the check-record write data: the per-lane registers
//     are zeroed at start, so the clearing pass writes a record that is
//     already zero.
//
// The check has to be its own pass. Layer r's parity is only meaningful once
// every variable it touches has its final value for the iteration, and later
// layers are still going to change some of them.
module ldpc_decoder (
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

    // control and status
    input  wire                     start,
    input  wire [ITER_BITS-1:0]     max_iters,
    output logic                    busy,
    output logic                    done,
    output logic                    ok,            // NEW: syndrome satisfied
    output logic [ITER_BITS-1:0]    iter_count
);

  // ------------------------------------------------------------ parameters
  localparam int unsigned ADDR_X    = $clog2(N_B);          // 9
  localparam int unsigned ADDR_S    = $clog2(M_B);          // 8
  localparam int unsigned ADDR_E    = $clog2(N_EDGES);      // 11
  localparam int unsigned W_APP     = 8;                    // spec 2.1
  localparam int unsigned W_MSG     = 6;
  localparam int          MAX_APP   = 127;
  localparam int unsigned MAX_MSG   = 31;
  localparam int unsigned APP_W     = Z * W_APP;            // 1024
  localparam int unsigned IDX_BITS  = $clog2(MAX_ROW_DEG + 1);
  localparam int unsigned ITER_BITS = 6;

  localparam int unsigned MAG_BITS = W_MSG;                   // 6
  localparam int unsigned IDX_LO   = 2 * MAG_BITS;            // 12
  localparam int unsigned SGN_LO   = IDX_LO + IDX_BITS;       // 16
  localparam int unsigned CN_BITS  = SGN_LO + MAX_ROW_DEG;    // 30
  localparam int unsigned CN_W     = Z * CN_BITS;             // 3840

  // --------------------------------------------------------------- state
  // Twenty states now that the check sweep has its own, so the state register
  // is five bits wide rather than stage 3's four.
  typedef enum logic [4:0] {
    S_IDLE, S_CLEAR, S_L_START, S_SETUP,
    S_A_ROM, S_A_MEM, S_A_ACC,
    S_B_SETUP, S_B_ROM, S_B_MEM, S_B_ROT, S_B_WR,
    S_L_END,
    S_C_SETUP, S_C_ROM, S_C_MEM, S_C_ACC, S_C_CMP, S_C_END,
    S_DONE
  } state_t;

  state_t                 state;
  logic [ADDR_E:0]        e_start, e_end, e_idx;
  logic [IDX_BITS-1:0]    pos;
  logic [EDGE_BITS-1:0]   rom_q;
  logic [SHIFT_BITS-1:0]  shift_q;
  logic [COL_BITS-1:0]    col_q;
  logic [ADDR_S-1:0]      layer_q, clr_ptr;
  logic [ITER_BITS-1:0]   iter_q, iters_q;

  logic [W_MSG:0]         min1 [Z];
  logic [W_MSG:0]         min2 [Z];
  logic [IDX_BITS-1:0]    idx  [Z];
  logic                   sgn  [Z];
  logic [MAX_ROW_DEG-1:0] sgn_bits [Z];
  logic [Z-1:0]           syn_q;

  logic [CN_W-1:0]        old_rec;
  logic [Z-1:0]           old_par;
  logic [APP_W-1:0]       wb_q;

  logic [Z-1:0]           par;        // NEW: parity of the hard decisions, per lane
  logic                   chk_bad;    // NEW: sticky across the whole check sweep

  assign iter_count = iter_q;

  // --------------------------------------------------------------- memories
  logic [APP_W-1:0]      app_mem  [N_B];
  logic [Z-1:0]          syn_mem  [M_B];
  logic [EDGE_BITS-1:0]  edge_rom [N_EDGES];
  logic [15:0]           layer_ptr_rom [M_B+1];

  (* ram_style = "block" *)
  logic [CN_W-1:0]       cn_mem   [M_B];

  initial begin
    $readmemh("v3_mother_1_r700_edges.mem",     edge_rom);
    $readmemh("v3_mother_1_r700_layer_ptr.mem", layer_ptr_rom);
  end

  always_ff @(posedge clk) begin
    if (wr_s_en) syn_mem[wr_s_addr] <= wr_s_data;
  end

  // ------------------------------------------------------------- functions
  function automatic logic [APP_W-1:0] rot_lanes(input logic [APP_W-1:0] w,
                                                 input logic [SHIFT_BITS-1:0] k);
    logic [2*APP_W-1:0] dbl;
    begin
      dbl       = {w, w};
      rot_lanes = dbl[k * W_APP +: APP_W];
    end
  endfunction

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
      rot_amt = (Z - shift_q) & (Z - 1);
    end else begin
      rot_in  = app_q;
      rot_amt = shift_q;
    end
    rot_out = rot_lanes(rot_in, rot_amt);
  end

  // ------------------------------------------- T = sat(L - R_old), per lane
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
              ? {2'b00, old_rec[i*CN_BITS + MAG_BITS +: MAG_BITS]}
              : {2'b00, old_rec[i*CN_BITS            +: MAG_BITS]};
      o_nrm = (o_mag >> 1) + (o_mag >> 2);
      o_neg = syn_q[i] ^ old_par[i] ^ o_vec[pos];
      o_val = o_neg ? -$signed({2'b00, o_nrm}) : $signed({2'b00, o_nrm});
      t_lane[i] = sat_add(o_l, -o_val);
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
    // NEW: the check sweep reads columns too
    app_raddr = ((state == S_A_MEM) || (state == S_B_MEM) || (state == S_C_MEM))
                ? rom_q[COL_BITS-1:0] : rd_app_addr;

    if (wr_app_en) begin
      app_we    = 1'b1;
      app_waddr = wr_app_addr;
      app_wdata = wr_app_data;
    end else begin
      app_we    = (state == S_B_WR);
      app_waddr = col_q;
      app_wdata = rot_out;
    end
  end

  always_ff @(posedge clk) begin
    if (app_we) app_mem[app_waddr] <= app_wdata;
    app_q <= app_mem[app_raddr];
  end

  // ------------------------------------------------ check-record memory ports
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
    cn_wdata = rec_w;          // NEW: no multiplexer - the registers are zero
  end                          // during the clearing pass, so the record is too

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
      ok    <= 1'b0;
    end else begin
      case (state)
        S_IDLE: begin
          done <= 1'b0;
          if (start) begin
            busy    <= 1'b1;
            ok      <= 1'b0;
            iters_q <= (max_iters == '0) ? 1'b1 : max_iters;
            iter_q  <= '0;
            clr_ptr <= '0;
            // NEW: zero the record registers so the clearing pass writes zeros
            for (int i = 0; i < Z; i++) begin
              min1[i]     <= '0;
              min2[i]     <= '0;
              idx[i]      <= '0;
              sgn_bits[i] <= '0;
            end
            state <= S_CLEAR;
          end
        end

        S_CLEAR: begin
          if (clr_ptr == M_B - 1) begin
            layer_q <= '0;
            state   <= S_L_START;
          end else begin
            clr_ptr <= clr_ptr + 1'b1;
          end
        end

        S_L_START: state <= S_SETUP;

        S_SETUP: begin
          old_rec <= cn_q;
          for (int i = 0; i < Z; i++)
            old_par[i] <= ^cn_q[i*CN_BITS + SGN_LO +: MAX_ROW_DEG];
          e_start <= layer_ptr_rom[layer_q];
          e_end   <= layer_ptr_rom[layer_q + 1];
          e_idx   <= layer_ptr_rom[layer_q];
          pos     <= '0;
          syn_q   <= syn_mem[layer_q];
          for (int i = 0; i < Z; i++) begin
            min1[i]     <= MAX_MSG + 1;
            min2[i]     <= MAX_MSG + 1;
            idx[i]      <= '0;
            sgn[i]      <= 1'b0;
            sgn_bits[i] <= '0;
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

        S_A_MEM: begin
          col_q   <= rom_q[COL_BITS-1:0];
          shift_q <= rom_q[EDGE_BITS-1:COL_BITS];
          state   <= S_A_ACC;
        end

        S_A_ACC: begin
          for (int i = 0; i < Z; i++) begin
            a_t = t_lane[i];
            a_m = a_t[W_APP-1] ? (-a_t) : a_t;
            a_a = (a_m > MAX_MSG) ? MAX_MSG[W_MSG:0] : a_m[W_MSG:0];
            sgn[i]           <= sgn[i] ^ a_t[W_APP-1];
            sgn_bits[i][pos] <= a_t[W_APP-1];
            if (a_a < min1[i]) begin
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
          if (e_idx == e_end) state <= S_L_END;
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

        S_B_ROT: begin
          wb_q  <= new_word;
          state <= S_B_WR;
        end

        S_B_WR: begin
          e_idx <= e_idx + 1'b1;
          pos   <= pos + 1'b1;
          state <= S_B_ROM;
        end

        S_L_END: begin
          if (layer_q == M_B - 1) begin
            layer_q <= '0;
            iter_q  <= iter_q + 1'b1;
            chk_bad <= 1'b0;              // NEW: the iteration is complete; check it
            state   <= S_C_SETUP;
          end else begin
            layer_q <= layer_q + 1'b1;
            state   <= S_L_START;
          end
        end

        // -------------------------------------------- NEW: the check sweep
        S_C_SETUP: begin
          e_idx <= layer_ptr_rom[layer_q];
          e_end <= layer_ptr_rom[layer_q + 1];
          syn_q <= syn_mem[layer_q];
          par   <= '0;
          state <= S_C_ROM;
        end

        S_C_ROM: begin
          if (e_idx == e_end) state <= S_C_CMP;
          else begin
            rom_q <= edge_rom[e_idx];
            state <= S_C_MEM;
          end
        end

        S_C_MEM: begin
          shift_q <= rom_q[EDGE_BITS-1:COL_BITS];
          state   <= S_C_ACC;
        end

        S_C_ACC: begin                    // the hard decision is the sign bit
          for (int i = 0; i < Z; i++)
            par[i] <= par[i] ^ rot_out[i*W_APP + W_APP - 1];
          e_idx <= e_idx + 1'b1;
          state <= S_C_ROM;
        end

        S_C_CMP: begin
          if (par != syn_q) chk_bad <= 1'b1;
          if (layer_q == M_B - 1) state <= S_C_END;
          else begin
            layer_q <= layer_q + 1'b1;
            state   <= S_C_SETUP;
          end
        end

        S_C_END: begin
          if (!chk_bad) begin             // every layer agreed: the frame is decoded
            ok    <= 1'b1;
            state <= S_DONE;
          end else if (iter_q == iters_q) begin
            ok    <= 1'b0;
            state <= S_DONE;
          end else begin
            layer_q <= '0;
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
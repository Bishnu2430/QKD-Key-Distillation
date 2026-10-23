`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Stage 7: the same decoder, one edge per clock.
//
// Stages 1-6 walked the edge list with a small state machine that spent five
// to seven cycles on every edge: fetch the edge, present the address, wait for
// the block RAM, rotate, compute, rotate back, write. Here those steps become
// pipeline stages, so a new edge is issued every cycle and the per-edge cost
// is one clock plus a fixed drain at the end of each pass.
//
//   c0  present the edge-ROM address
//   c1  rom_q valid     -> present the APP read address
//   c2  block RAM internal register
//   c3  block RAM output register -> forward rotate, and IN PARALLEL the
//                          reconstruction of R_old from the stored record
//   c4  rot_q and rold_q valid -> T = sat(L - R_old), and the new message's
//                          magnitude; mode C takes its parity bit here
//   c5  t_q valid       -> mode A  accumulate min1/min2/idx/sign
//                          mode B  L = sat(T + R_new) -> wb_q
//   c6  (mode B) inverse rotate wb_q
//   c7  (mode B) write the APP memory
//
// Stage 7 did everything from c3's rotate output to the minimum finder in one
// cycle, and every one of its six worst paths ran through it: 17 logic levels
// starting at pos4, which fans out to a 4-bit comparison and a 14-to-1
// multiplexer in each of 128 lanes. Splitting that stage in three moves the
// pos-dependent work a cycle earlier, where it runs beside the rotator instead
// of after it, and leaves c4 and c5 with roughly a third of the depth each.
//
// Two changes of principle compared with stage 6:
//
//   * TWO rotators, not one. Stage 2 shared a single rotator between the read
//     and the write-back, which was right for a design that visited each edge
//     once every seven cycles. In a pipeline the forward rotate of edge k+2 and
//     the inverse rotate of edge k happen in the same cycle, so sharing is no
//     longer possible. The second rotator costs about 3,500 LUTs - and it also
//     takes the state register off the datapath, because neither rotator needs
//     a state-dependent input multiplexer any more.
//
//   * The APP memory is read and written in the same cycle. That is safe: it
//     is inferred as a simple dual-port block RAM (one write port, one read
//     port), and within a layer every edge touches a different base column, so
//     a read and a write in the same cycle are never to the same address.
//     Across layers, each pass drains completely before the next one starts.
module ldpc_decoder_deep (
    input  wire                     clk,
    input  wire                     rst_n,

    // APP memory load / read-back port (the testbench reads the result here)
    input  wire                     wr_app_en,
    input  wire [ADDR_X-1:0]        wr_app_addr,
    input  wire [APP_W-1:0]         wr_app_data,
    input  wire [ADDR_X-1:0]        rd_app_addr,
    output wire [APP_W-1:0]         rd_app_data,

    // syndrome load port
    input  wire                     wr_s_en,
    input  wire [ADDR_S-1:0]        wr_s_addr,
    input  wire [Z-1:0]             wr_s_data,

    // mask load port - two bits per base column
    input  wire                     wr_m_en,
    input  wire [ADDR_X-1:0]        wr_m_addr,
    input  wire [1:0]               wr_m_data,

    // key load port - one Z-bit word per key column
    input  wire                     wr_k_en,
    input  wire [ADDR_X-1:0]        wr_k_addr,
    input  wire [Z-1:0]             wr_k_data,

    // control and status
    input  wire                     load_start,
    input  wire signed [W_APP-1:0]  ch_amp,
    input  wire                     start,
    input  wire [ITER_BITS-1:0]     max_iters,
    output logic                    busy,
    output logic                    done,
    output logic                    ok,
    output logic [ITER_BITS-1:0]    iter_count
);

  // ------------------------------------------------------------ parameters
  localparam int unsigned ADDR_X    = $clog2(N_B);          // 9
  localparam int unsigned ADDR_S    = $clog2(M_B);          // 8
  localparam int unsigned ADDR_E    = $clog2(N_EDGES);      // 11
  localparam int unsigned W_APP     = 8;
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

  localparam logic [1:0] CLS_KEY   = 2'd0;
  localparam logic [1:0] CLS_PUNCT = 2'd1;
  localparam logic [1:0] CLS_SHORT = 2'd2;

  // which pass the edges now in flight belong to
  localparam logic [1:0] MD_A = 2'd0;   // accumulate the minima
  localparam logic [1:0] MD_B = 2'd1;   // write back
  localparam logic [1:0] MD_C = 2'd2;   // check the syndrome

  // --------------------------------------------------------------- state
  typedef enum logic [4:0] {
    S_IDLE,
    S_LD_ADDR, S_LD_WR,
    S_CLEAR, S_L_START, S_SETUP,
    S_A_ISSUE, S_A_DRAIN,
    S_B_SETUP, S_B_ISSUE, S_B_DRAIN,
    S_L_END,
    S_C_SETUP, S_C_ISSUE, S_C_DRAIN, S_C_CMP, S_C_END,
    S_DONE
  } state_t;

  state_t                 state;
  logic [1:0]             mode;
  logic [ADDR_E:0]        e_start, e_end, e_idx;
  logic [IDX_BITS-1:0]    pos_iss;
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
  logic [Z-1:0]           par;
  logic                   chk_bad;

  logic [ADDR_X-1:0]      ld_col, kcol;
  logic [1:0]             cls_q;
  logic signed [W_APP-1:0] amp_q;

  assign iter_count = iter_q;

  // ------------------------------------------------- the pipeline's control
  // One valid bit per stage, with the edge's column, shift and position
  // travelling alongside it. Nothing ever stalls, so this is a plain shift
  // register: an edge issued at c0 arrives at the arithmetic at c4.
  logic                   v1, v2, v3, v4, v5, v6, v7;
  logic [SHIFT_BITS-1:0]  sh2, sh3, sh4, sh5, sh6;
  logic [COL_BITS-1:0]    col2, col3, col4, col5, col6, col7;
  logic [IDX_BITS-1:0]    pos1, pos2, pos3, pos4, pos5;

  // what c3 and c4 hand on: the old message, which neighbour owns the minimum,
  // the variable-to-check value, and the new message's magnitude
  logic signed [W_APP+1:0] rold_q [Z];
  logic                    sel2_q [Z];
  logic signed [W_APP-1:0] t_q    [Z];
  logic [W_MSG:0]          nrm_q  [Z];

  logic                   issue;          // an edge enters the pipeline now
  logic                   pipe_busy;      // anything still in flight

  assign issue = ((state == S_A_ISSUE) || (state == S_B_ISSUE) ||
                  (state == S_C_ISSUE)) && (e_idx != e_end);
  assign pipe_busy = v1 | v2 | v3 | v4 | v5 | v6 | v7;

  // --------------------------------------------------------------- memories
  logic [APP_W-1:0]      app_mem  [N_B];
  logic [Z-1:0]          syn_mem  [M_B];
  logic [EDGE_BITS-1:0]  edge_rom [N_EDGES];
  logic [15:0]           layer_ptr_rom [M_B+1];

  (* ram_style = "block" *)
  logic [CN_W-1:0]       cn_mem   [M_B];

  logic [1:0]            mask_mem [N_B];
  logic [Z-1:0]          key_mem  [N_B];
  logic [Z-1:0]          key_q;

  initial begin
    $readmemh("v3_mother_1_r700_edges.mem",     edge_rom);
    $readmemh("v3_mother_1_r700_layer_ptr.mem", layer_ptr_rom);
  end

  always_ff @(posedge clk) begin
    if (wr_s_en) syn_mem[wr_s_addr] <= wr_s_data;
    if (wr_m_en) mask_mem[wr_m_addr] <= wr_m_data;
  end

  always_ff @(posedge clk) begin
    if (wr_k_en) key_mem[wr_k_addr] <= wr_k_data;
    key_q <= key_mem[kcol];
  end

  // the edge ROM, read every cycle at the issue address
  logic [EDGE_BITS-1:0] rom_q;

  always_ff @(posedge clk) rom_q <= edge_rom[e_idx[ADDR_E-1:0]];

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
  logic [APP_W-1:0]  app_q1, app_q;
  logic              app_we;
  logic [ADDR_X-1:0] app_waddr;
  logic [APP_W-1:0]  app_wdata;

  assign rd_app_data = app_q;

  // ------------------------------------------------------- the two rotators
  // Forward: the column just read, into check order. Inverse: the updated
  // word, back into column order. Both run every cycle on their own operands,
  // so neither needs a multiplexer and the state register drives neither.
  logic [APP_W-1:0] rot_q;        // c3 -> c4
  logic [APP_W-1:0] wb_q;         // c4 -> c5
  logic [APP_W-1:0] wbr_q;        // c5 -> c6

  always_ff @(posedge clk) rot_q <= rot_lanes(app_q, sh3);

  // ------------------------------- temporaries for the staged arithmetic
  // Declared once at module level and used only inside the clocked block
  // below, exactly as in the earlier stages.
  logic [MAX_ROW_DEG-1:0]   o_vec;
  logic [W_APP-1:0]         o_mag;
  logic [W_MSG:0]           o_nrm;
  logic                     o_neg;
  logic [W_APP-1:0]         n_mag;
  logic signed [W_APP+1:0]  n_val;
  logic                     n_neg;

  // ----------------------------------- the starting APP word for a column
  logic [APP_W-1:0] ld_word;

  always_comb begin
    for (int j = 0; j < Z; j++) begin
      case (cls_q)
        CLS_PUNCT: ld_word[j*W_APP +: W_APP] = '0;
        CLS_SHORT: ld_word[j*W_APP +: W_APP] = MAX_APP[W_APP-1:0];
        default:   ld_word[j*W_APP +: W_APP] = key_q[j] ? -amp_q : amp_q;
      endcase
    end
  end

  always_comb begin
    // the pipeline owns the read port while an edge is at c1
    app_raddr = v1 ? rom_q[COL_BITS-1:0] : rd_app_addr;

    // three writers: the host, the loader, and the pipeline's c6
    if (wr_app_en) begin
      app_we    = 1'b1;
      app_waddr = wr_app_addr;
      app_wdata = wr_app_data;
    end else if (state == S_LD_WR) begin
      app_we    = 1'b1;
      app_waddr = ld_col;
      app_wdata = ld_word;
    end else begin
      app_we    = v7;
      app_waddr = {{(ADDR_X-COL_BITS){1'b0}}, col7};
      app_wdata = wbr_q;
    end
  end

  always_ff @(posedge clk) begin
    if (app_we) app_mem[app_waddr] <= app_wdata;
    app_q1 <= app_mem[app_raddr];
    app_q  <= app_q1;
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
    cn_wdata = rec_w;
  end

  always_ff @(posedge clk) begin
    if (cn_we) cn_mem[cn_waddr] <= cn_wdata;
    cn_q <= cn_mem[cn_raddr];
  end

  // --------------------------------------------------------- the pipeline
  logic signed [W_APP-1:0] a_t;
  logic [W_APP-1:0]        a_m;
  logic [W_MSG:0]          a_a;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      v1 <= 1'b0; v2 <= 1'b0; v3 <= 1'b0; v4 <= 1'b0;
      v5 <= 1'b0; v6 <= 1'b0; v7 <= 1'b0;
    end else begin
      // c0 -> c1: the edge ROM read is in flight
      v1   <= issue;
      pos1 <= pos_iss;

      // c1 -> c2: the APP read address is presented this cycle
      v2   <= v1;
      sh2  <= rom_q[EDGE_BITS-1:COL_BITS];
      col2 <= rom_q[COL_BITS-1:0];
      pos2 <= pos1;

      // c2 -> c3: the block RAM's internal register
      v3   <= v2;
      sh3  <= sh2;
      col3 <= col2;
      pos3 <= pos2;

      // c3 -> c4: the block RAM's output register, and the forward rotate
      v4   <= v3;
      sh4  <= sh3;
      col4 <= col3;
      pos4 <= pos3;

      // c4 -> c5: the arithmetic stage
      v5   <= v4;
      sh5  <= sh4;
      col5 <= col4;
      pos5 <= pos4;

      // c5 -> c6: pass B only, the updated word waits for the inverse rotate
      v6   <= v5 & (mode == MD_B);
      sh6  <= sh5;
      col6 <= col5;

      // c6 -> c7: the inverse rotate
      v7   <= v6;
      col7 <= col6;
    end
  end

  // --------------------------------------------------------------- control
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state <= S_IDLE;
      busy  <= 1'b0;
      done  <= 1'b0;
      ok    <= 1'b0;
    end else begin
      // ---- the pipeline's work, one stage per cycle. These assignments share
      // an always_ff with the control below because both write min1, min2,
      // idx, sgn, sgn_bits and par: two always_ff blocks writing one variable
      // is multiple drivers. A pass always drains before the state that clears
      // them, so the two never fire in the same cycle.

      // c3: R_old for the edge whose column has just arrived, reconstructed
      // beside the rotate rather than after it. sel2_q answers "does this
      // neighbour own the layer's minimum", which pass B needs at c5.
      for (int i = 0; i < Z; i++) begin
        o_vec     = old_rec[i*CN_BITS + SGN_LO +: MAX_ROW_DEG];
        o_mag     = (pos3 == old_rec[i*CN_BITS + IDX_LO +: IDX_BITS])
                    ? {2'b00, old_rec[i*CN_BITS + MAG_BITS +: MAG_BITS]}
                    : {2'b00, old_rec[i*CN_BITS            +: MAG_BITS]};
        o_nrm     = (o_mag >> 1) + (o_mag >> 2);
        o_neg     = syn_q[i] ^ old_par[i] ^ o_vec[pos3];
        rold_q[i] <= o_neg ? -$signed({2'b00, o_nrm}) : $signed({2'b00, o_nrm});
        sel2_q[i] <= (pos3 == idx[i]);
      end

      // c4: the subtract, and the magnitude pass B will add back
      for (int i = 0; i < Z; i++) begin
        t_q[i]   <= sat_add(rot_q[i*W_APP +: W_APP], -rold_q[i]);
        n_mag     = sel2_q[i] ? {1'b0, min2[i]} : {1'b0, min1[i]};
        nrm_q[i] <= (n_mag >> 1) + (n_mag >> 2);
      end

      // c4: the check sweep needs the sign of L, which rot_q already holds
      if (v4 && (mode == MD_C))
        for (int i = 0; i < Z; i++)
          par[i] <= par[i] ^ rot_q[i*W_APP + W_APP - 1];

      // c5: the minimum finder, or the write-back word
      if (v5) begin
        case (mode)
          MD_A: begin
            for (int i = 0; i < Z; i++) begin
              a_t = t_q[i];
              a_m = a_t[W_APP-1] ? (-a_t) : a_t;
              a_a = (a_m > MAX_MSG) ? MAX_MSG[W_MSG:0] : a_m[W_MSG:0];
              sgn[i]            <= sgn[i] ^ a_t[W_APP-1];
              sgn_bits[i][pos5] <= a_t[W_APP-1];
              if (a_a < min1[i]) begin
                min2[i] <= min1[i];
                min1[i] <= a_a;
                idx[i]  <= pos5;
              end else if (a_a < min2[i]) begin
                min2[i] <= a_a;
              end
            end
          end

          MD_B: begin
            for (int i = 0; i < Z; i++) begin
              n_neg = sgn[i] ^ syn_q[i] ^ t_q[i][W_APP-1];
              n_val = n_neg ? -$signed({2'b00, nrm_q[i]}) : $signed({2'b00, nrm_q[i]});
              wb_q[i*W_APP +: W_APP] <= sat_add(t_q[i], n_val);
            end
          end

          default: ;
        endcase
      end

      // c6: the inverse rotate, back into column order
      if (v6) wbr_q <= rot_lanes(wb_q, (Z - sh6) & (Z - 1));

      case (state)
        S_IDLE: begin
          done <= 1'b0;
          if (load_start) begin
            busy   <= 1'b1;
            amp_q  <= ch_amp;
            ld_col <= '0;
            kcol   <= '0;
            state  <= S_LD_ADDR;
          end else if (start) begin
            busy    <= 1'b1;
            ok      <= 1'b0;
            iters_q <= (max_iters == '0) ? 1'b1 : max_iters;
            iter_q  <= '0;
            clr_ptr <= '0;
            for (int i = 0; i < Z; i++) begin
              min1[i]     <= '0;
              min2[i]     <= '0;
              idx[i]      <= '0;
              sgn_bits[i] <= '0;
            end
            state <= S_CLEAR;
          end
        end

        S_LD_ADDR: begin
          cls_q <= mask_mem[ld_col];
          state <= S_LD_WR;
        end

        S_LD_WR: begin
          if (cls_q == CLS_KEY) kcol <= kcol + 1'b1;
          if (ld_col == N_B - 1) state <= S_DONE;
          else begin
            ld_col <= ld_col + 1'b1;
            state  <= S_LD_ADDR;
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
          pos_iss <= '0;
          syn_q   <= syn_mem[layer_q];
          mode    <= MD_A;
          for (int i = 0; i < Z; i++) begin
            min1[i]     <= MAX_MSG + 1;
            min2[i]     <= MAX_MSG + 1;
            idx[i]      <= '0;
            sgn[i]      <= 1'b0;
            sgn_bits[i] <= '0;
          end
          state <= S_A_ISSUE;
        end

        // ------------------------------------------- pass A, one edge a cycle
        S_A_ISSUE: begin
          if (e_idx == e_end) state <= S_A_DRAIN;
          else begin
            e_idx   <= e_idx + 1'b1;
            pos_iss <= pos_iss + 1'b1;
          end
        end

        S_A_DRAIN: if (!pipe_busy) state <= S_B_SETUP;

        // ------------------------------------------- pass B, one edge a cycle
        S_B_SETUP: begin
          e_idx   <= e_start;
          pos_iss <= '0;
          mode    <= MD_B;
          state   <= S_B_ISSUE;
        end

        S_B_ISSUE: begin
          if (e_idx == e_end) state <= S_B_DRAIN;
          else begin
            e_idx   <= e_idx + 1'b1;
            pos_iss <= pos_iss + 1'b1;
          end
        end

        S_B_DRAIN: if (!pipe_busy) state <= S_L_END;

        S_L_END: begin
          if (layer_q == M_B - 1) begin
            layer_q <= '0;
            iter_q  <= iter_q + 1'b1;
            chk_bad <= 1'b0;
            state   <= S_C_SETUP;
          end else begin
            layer_q <= layer_q + 1'b1;
            state   <= S_L_START;
          end
        end

        // ------------------------------- the check sweep, one edge a cycle
        S_C_SETUP: begin
          e_idx   <= layer_ptr_rom[layer_q];
          e_end   <= layer_ptr_rom[layer_q + 1];
          syn_q   <= syn_mem[layer_q];
          pos_iss <= '0;
          par     <= '0;
          mode    <= MD_C;
          state   <= S_C_ISSUE;
        end

        S_C_ISSUE: begin
          if (e_idx == e_end) state <= S_C_DRAIN;
          else begin
            e_idx   <= e_idx + 1'b1;
            pos_iss <= pos_iss + 1'b1;
          end
        end

        S_C_DRAIN: if (!pipe_busy) state <= S_C_CMP;

        S_C_CMP: begin
          if (par != syn_q) chk_bad <= 1'b1;
          if (layer_q == M_B - 1) state <= S_C_END;
          else begin
            layer_q <= layer_q + 1'b1;
            state   <= S_C_SETUP;
          end
        end

        S_C_END: begin
          if (!chk_bad) begin
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

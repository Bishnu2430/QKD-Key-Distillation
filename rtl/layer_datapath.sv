`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Stage 2: process one layer, first-iteration semantics (old messages are zero).
// Two passes over the layer's edges:
//   pass A - find min1/min2/index and the sign product for each of the Z lanes
//   pass B - write back L = sat(T + R_new)
// Three cycles per edge in each pass; stage 3 pipelines this.
//
// MEMORY STRUCTURE MATTERS AS MUCH AS THE ARITHMETIC. app_mem is 512 x 1024
// bits and must become block RAM, which means exactly ONE write port and ONE
// read port, both registered, both inside one always_ff. The read address is
// muxed between the datapath and the test port; the write is muxed between the
// load path and the datapath. Spread those accesses over two always_ff blocks
// and Vivado reports "Unable to infer a block/distributed RAM ... 524288 bits
// is too large".
module layer_datapath (
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
    input  wire [ADDR_S-1:0]        layer_sel,
    output logic                    busy,
    output logic                    done
);

  // ------------------------------------------------------------ parameters
  localparam int unsigned ADDR_X   = $clog2(N_B);          // 9
  localparam int unsigned ADDR_S   = $clog2(M_B);          // 8
  localparam int unsigned ADDR_E   = $clog2(N_EDGES);      // 11
  localparam int unsigned W_APP    = 8;                    // spec 2.1
  localparam int unsigned W_MSG    = 6;
  localparam int          MAX_APP  = 127;   // signed: sat_add compares against it
  localparam int unsigned MAX_MSG  = 31;    // unsigned: only compared with |T|
  localparam int unsigned APP_W    = Z * W_APP;            // 1024 bits per column
  localparam int unsigned IDX_BITS = $clog2(MAX_ROW_DEG + 1);

  // --------------------------------------------------------------- state
  typedef enum logic [3:0] {
    S_IDLE, S_SETUP, S_A_ROM, S_A_MEM, S_A_ACC,
    S_B_SETUP, S_B_ROM, S_B_MEM, S_B_ROT, S_B_WR, S_DONE
  } state_t;

  state_t                state;
  logic [ADDR_E:0]       e_start, e_end, e_idx;
  logic [IDX_BITS-1:0]   pos;
  logic [EDGE_BITS-1:0]  rom_q;
  logic [SHIFT_BITS-1:0] shift_q;
  logic [COL_BITS-1:0]   col_q;

  logic [W_MSG:0]        min1 [Z];      // one bit wider than W_MSG for the sentinel
  logic [W_MSG:0]        min2 [Z];
  logic [IDX_BITS-1:0]   idx  [Z];
  logic                  sgn  [Z];      // running sign product, 1 = negative
  logic [Z-1:0]          syn_q;

  // --------------------------------------------------------------- memories
  logic [APP_W-1:0]      app_mem  [N_B];
  logic [Z-1:0]          syn_mem  [M_B];
  logic [EDGE_BITS-1:0]  edge_rom [N_EDGES];
  logic [15:0]           layer_ptr_rom [M_B+1];

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
  // ONE read port, ONE write port. This is what makes it a BRAM.
  logic [ADDR_X-1:0] app_raddr;
  logic [APP_W-1:0]  app_q;        // registered read data, used by both users
  logic              app_we;
  logic [ADDR_X-1:0] app_waddr;
  logic [APP_W-1:0]  app_wdata;

  assign rd_app_data = app_q;

  // combinational write-back word, built from the registered read data
  logic [APP_W-1:0]        t_word, new_word;
  logic [APP_W-1:0]        wb_q;    // new_word, held while the rotator turns around
  logic signed [W_APP-1:0] tl;
  logic [W_APP-1:0]        magv;
  logic [W_MSG:0]          nrm;
  logic signed [W_APP+1:0] rval;
  logic                    rneg;

  // temporaries used only inside the control block (pass A accumulation)
  logic signed [W_APP-1:0] ta;
  logic [W_APP-1:0]        ma;
  logic [W_MSG:0]          aa;

  // the one and only lane rotator
  // Two users, never in the same cycle - which is the whole reason S_B_WR was
  // split in two. In S_B_WR it rotates the held word back to column order; in
  // every other state it rotates the freshly read column into check order.
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

  assign t_word = rot_out;                 // valid in S_A_ACC and in S_B_ROT

  always_comb begin
    for (int i = 0; i < Z; i++) begin
      tl   = t_word[i*W_APP +: W_APP];
      magv = (pos == idx[i]) ? {1'b0, min2[i]} : {1'b0, min1[i]};
      nrm  = (magv >> 1) + (magv >> 2);                 // alpha = 0.75, truncating
      rneg = sgn[i] ^ syn_q[i] ^ tl[W_APP-1];           // final sign of R
      rval = rneg ? -$signed({2'b00, nrm}) : $signed({2'b00, nrm});
      new_word[i*W_APP +: W_APP] = sat_add(tl, rval);
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

  // --------------------------------------------------------------- control
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
            busy  <= 1'b1;
            state <= S_SETUP;
          end
        end

        S_SETUP: begin
          e_start <= layer_ptr_rom[layer_sel];
          e_end   <= layer_ptr_rom[layer_sel + 1];
          e_idx   <= layer_ptr_rom[layer_sel];
          pos     <= '0;
          syn_q   <= syn_mem[layer_sel];
          for (int i = 0; i < Z; i++) begin
            min1[i] <= MAX_MSG + 1;          // sentinel: larger than any |T|
            min2[i] <= MAX_MSG + 1;
            idx[i]  <= '0;
            sgn[i]  <= 1'b0;
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

        S_A_ACC: begin                       // app_q holds the column
          for (int i = 0; i < Z; i++) begin
            ta = t_word[i*W_APP +: W_APP];
            ma = ta[W_APP-1] ? (-ta) : ta;                  // |T|
            aa = (ma > MAX_MSG) ? MAX_MSG[W_MSG:0] : ma[W_MSG:0];
            sgn[i] <= sgn[i] ^ ta[W_APP-1];                 // sign product
            if (aa < min1[i]) begin                         // strict: first wins
              min2[i] <= min1[i];
              min1[i] <= aa;
              idx[i]  <= pos;
            end else if (aa < min2[i]) begin
              min2[i] <= aa;
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
          if (e_idx == e_end) state <= S_DONE;
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

        S_B_ROT: begin       // app_q holds the column: do the arithmetic and hold it
          wb_q  <= new_word;
          state <= S_B_WR;
        end

        S_B_WR: begin        // rot_out is now wb_q in column order; the memory writes it
          e_idx <= e_idx + 1'b1;
          pos   <= pos + 1'b1;
          state <= S_B_ROM;
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
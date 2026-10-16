`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Stage 1: walk every layer, XOR the connected bits, compare with the syndrome.
// Deliberately simple: three cycles per edge, no pipelining. Stage 2 speeds it up.
module syndrome_checker (
    input  wire                     clk,
    input  wire                     rst_n,

    // load port: the testbench fills the two memories through this
    input  wire                     wr_x_en,
    input  wire [ADDR_X-1:0]        wr_x_addr,   // base column index
    input  wire [Z-1:0]             wr_x_data,   // 128 bits of x_hat
    input  wire                     wr_s_en,
    input  wire [ADDR_S-1:0]        wr_s_addr,   // layer index
    input  wire [Z-1:0]             wr_s_data,   // 128 syndrome bits

    // control
    input  wire                     start,
    output logic                    busy,
    output logic                    done,
    output logic                    match,       // 1 = every layer agreed
    output logic [15:0]             bad_layers   // how many disagreed
);

  localparam int unsigned ADDR_X = $clog2(N_B);        // 9
  localparam int unsigned ADDR_S = $clog2(M_B);        // 8
  localparam int unsigned ADDR_E = $clog2(N_EDGES);    // 11

  // ---------------------------------------------------------------- memories
  logic [Z-1:0]          xhat_mem [N_B];   // 512 x 128 = 65,536 bits
  logic [Z-1:0]          syn_mem  [M_B];   // 154 x 128 = 19,712 bits
  logic [EDGE_BITS-1:0]  edge_rom [N_EDGES];
  logic [15:0]           layer_ptr_rom [M_B+1];

  initial begin
    $readmemh("v3_mother_1_r700_edges.mem",     edge_rom);
    $readmemh("v3_mother_1_r700_layer_ptr.mem", layer_ptr_rom);
  end

  always_ff @(posedge clk) begin
    if (wr_x_en) xhat_mem[wr_x_addr] <= wr_x_data;
    if (wr_s_en) syn_mem [wr_s_addr] <= wr_s_data;
  end

  // ------------------------------------------------------- rotate left by k
  // lane i of a check must read bit (i + shift) mod Z of the column word.
  function automatic logic [Z-1:0] rotl(input logic [Z-1:0] w,
                                        input logic [SHIFT_BITS-1:0] k);
    logic [2*Z-1:0] dbl;
    begin
      dbl  = {w, w};
      rotl = dbl[k +: Z];
    end
  endfunction

  // ------------------------------------------------------------------- FSM
  typedef enum logic [2:0] {
    S_IDLE, S_LAYER, S_EDGE_ROM, S_EDGE_MEM, S_EDGE_ACC, S_CMP, S_DONE
  } state_t;

  state_t                 state;
  logic [ADDR_S:0]        layer;      // one extra bit: counts up to M_B
  logic [ADDR_E:0]        e_idx, e_end;
  logic [Z-1:0]           acc;
  logic [EDGE_BITS-1:0]   rom_q;
  logic [SHIFT_BITS-1:0]  shift_q;
  logic [Z-1:0]           word_q;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state      <= S_IDLE;
      busy       <= 1'b0;
      done       <= 1'b0;
      match      <= 1'b1;
      bad_layers <= '0;
      layer      <= '0;
    end else begin
      case (state)
        S_IDLE: begin
          done <= 1'b0;
          if (start) begin
            busy       <= 1'b1;
            match      <= 1'b1;
            bad_layers <= '0;
            layer      <= '0;
            state      <= S_LAYER;
          end
        end

        S_LAYER: begin                       // set up one layer
          e_idx <= layer_ptr_rom[layer];
          e_end <= layer_ptr_rom[layer + 1];
          acc   <= '0;
          state <= S_EDGE_ROM;
        end

        S_EDGE_ROM: begin                    // fetch one edge record
          if (e_idx == e_end) begin
            state <= S_CMP;
          end else begin
            rom_q <= edge_rom[e_idx];
            state <= S_EDGE_MEM;
          end
        end

        S_EDGE_MEM: begin                    // read that column, latch the shift
          word_q  <= xhat_mem[rom_q[COL_BITS-1:0]];
          shift_q <= rom_q[EDGE_BITS-1:COL_BITS];
          state   <= S_EDGE_ACC;
        end

        S_EDGE_ACC: begin                    // rotate into place and accumulate
          acc   <= acc ^ rotl(word_q, shift_q);
          e_idx <= e_idx + 1'b1;
          state <= S_EDGE_ROM;
        end

        S_CMP: begin                         // compare this layer
          if (acc != syn_mem[layer[ADDR_S-1:0]]) begin
            match      <= 1'b0;
            bad_layers <= bad_layers + 1'b1;
          end
          if (layer == M_B - 1) begin
            state <= S_DONE;
          end else begin
            layer <= layer + 1'b1;
            state <= S_LAYER;
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
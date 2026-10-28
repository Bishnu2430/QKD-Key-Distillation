`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Stage 12: the decoder as an AXI peripheral.
//
// The decoder core has wide, private load ports - 1,024-bit APP words, 128-bit
// key and syndrome words - which suited a testbench and suits nothing else.
// This wrapper gives it the two interfaces a Zynq system speaks:
//
//   AXI4-Lite slave   the register map of docs/08-interfaces-regmap.md
//   AXI4-Stream       one 64-bit input stream carrying three packets per
//                     frame (mask, syndrome, key), and one 64-bit output
//                     stream carrying the corrected key
//
// Three packets on one channel rather than three channels, because a DMA
// engine moves packets and a block design is simpler with one stream each
// way. Each packet ends with TLAST, so the wrapper never has to be told how
// long the key is - which matters, because that depends on the mask.
//
// Per frame software: writes IMAX and CH_LLR_A, writes CTRL.start, sends the
// three packets, waits for STATUS.done, then reads STATUS.ok and LAST_ITERS
// while the corrected key arrives on the output stream.
module ldpc_axi #(
    parameter int unsigned AXI_ADDR_W = 12
) (
    input  wire                     aclk,
    input  wire                     aresetn,

    // ---- AXI4-Lite slave: control and status
    input  wire [AXI_ADDR_W-1:0]    s_axi_awaddr,
    input  wire                     s_axi_awvalid,
    output logic                    s_axi_awready,
    input  wire [31:0]              s_axi_wdata,
    input  wire [3:0]               s_axi_wstrb,
    input  wire                     s_axi_wvalid,
    output logic                    s_axi_wready,
    output logic [1:0]              s_axi_bresp,
    output logic                    s_axi_bvalid,
    input  wire                     s_axi_bready,
    input  wire [AXI_ADDR_W-1:0]    s_axi_araddr,
    input  wire                     s_axi_arvalid,
    output logic                    s_axi_arready,
    output logic [31:0]             s_axi_rdata,
    output logic [1:0]              s_axi_rresp,
    output logic                    s_axi_rvalid,
    input  wire                     s_axi_rready,

    // ---- AXI4-Stream slave: mask, then syndrome, then key
    input  wire [63:0]              s_axis_tdata,
    input  wire                     s_axis_tvalid,
    output logic                    s_axis_tready,
    input  wire                     s_axis_tlast,

    // ---- AXI4-Stream master: the corrected key
    output logic [63:0]             m_axis_tdata,
    output logic                    m_axis_tvalid,
    input  wire                     m_axis_tready,
    output logic                    m_axis_tlast,

    output logic                    irq
);

  localparam int unsigned ADDR_X    = $clog2(N_B);
  localparam int unsigned ADDR_S    = $clog2(M_B);
  localparam int unsigned W_APP     = 8;
  localparam int unsigned APP_W     = Z * W_APP;
  localparam int unsigned ITER_BITS = 6;

  localparam logic [31:0] ID_MAGIC = 32'h514B4431;   // "QKD1"

  // register offsets, docs/08-interfaces-regmap.md
  localparam logic [7:0] A_ID     = 8'h00, A_CTRL  = 8'h04, A_STATUS = 8'h08,
                         A_IMAX   = 8'h0C, A_MASKID= 8'h10, A_AMP    = 8'h14,
                         A_ITERS  = 8'h18, A_OK    = 8'h1C, A_FAIL   = 8'h20,
                         A_CYCLES = 8'h24;

  // --------------------------------------------------------- declarations
  typedef enum logic [3:0] {
    W_IDLE, W_RX_MASK, W_MASK_WR, W_RX_SYN, W_RX_KEY,
    W_LOAD, W_LOAD_W, W_DEC, W_DEC_W,
    W_TX_SCAN, W_TX_WAIT, W_TX_LO, W_TX_HI, W_DONE
  } wstate_t;

  wstate_t                 ws;

  logic [ITER_BITS-1:0]    reg_imax, reg_last_iters;
  logic signed [W_APP-1:0] reg_amp;
  logic [31:0]             reg_mask_id, reg_frames_ok, reg_frames_fail, reg_cycles;
  logic                    reg_irq_en, reg_done, reg_ok;
  logic                    start_pulse, soft_reset;

  logic [63:0]             beat, lo_word;
  logic [5:0]              sub;
  logic [ADDR_X-1:0]       col, kcol;
  logic [ADDR_S-1:0]       lay;
  logic                    half;
  logic [N_B-1:0]          is_key;
  logic [ADDR_X:0]         key_cols;
  logic [31:0]             cycle_cnt;
  logic                    busy_any;

  logic              wr_s_en, wr_m_en, wr_k_en;
  logic [ADDR_S-1:0] wr_s_addr;
  logic [Z-1:0]      wr_s_data, wr_k_data;
  logic [ADDR_X-1:0] wr_m_addr, wr_k_addr;
  logic [1:0]        wr_m_data;
  logic [APP_W-1:0]  rd_app_data;
  logic              load_start, dec_start, dec_busy, dec_done, dec_ok;
  logic [ITER_BITS-1:0] dec_iters;

  logic [63:0] sign_lo, sign_hi;

  assign busy_any = (ws != W_IDLE);
  assign irq      = reg_irq_en && reg_done;

  // ---------------------------------------------------- the decoder itself
  ldpc_decoder_chunk u_dec (
      .clk          (aclk),
      .rst_n        (aresetn & ~soft_reset),
      .wr_app_en    (1'b0),
      .wr_app_addr  ('0),
      .wr_app_data  ('0),
      .rd_app_addr  (col),              // the transmit scan drives this
      .rd_app_data  (rd_app_data),
      .wr_s_en      (wr_s_en),
      .wr_s_addr    (wr_s_addr),
      .wr_s_data    (wr_s_data),
      .wr_m_en      (wr_m_en),
      .wr_m_addr    (wr_m_addr),
      .wr_m_data    (wr_m_data),
      .wr_k_en      (wr_k_en),
      .wr_k_addr    (wr_k_addr),
      .wr_k_data    (wr_k_data),
      .load_start   (load_start),
      .ch_amp       (reg_amp),
      .start        (dec_start),
      .max_iters    (reg_imax),
      .busy         (dec_busy),
      .done         (dec_done),
      .ok           (dec_ok),
      .iter_count   (dec_iters)
  );

  // the sign bits of whichever column is on rd_app_data, as two 64-bit beats
  always_comb begin
    for (int j = 0; j < 64; j++) begin
      sign_lo[j] = rd_app_data[j*W_APP + W_APP - 1];
      sign_hi[j] = rd_app_data[(j+64)*W_APP + W_APP - 1];
    end
  end

  always_comb begin
    s_axis_tready = (ws == W_RX_MASK) || (ws == W_RX_SYN) || (ws == W_RX_KEY);
    m_axis_tvalid = (ws == W_TX_LO)   || (ws == W_TX_HI);
    m_axis_tdata  = (ws == W_TX_LO)   ? sign_lo : sign_hi;
    m_axis_tlast  = (ws == W_TX_HI)   && (kcol == key_cols - 1);
  end

  // ------------------------------------------------------------ AXI4-Lite
  logic aw_hs, ar_hs;
  assign aw_hs = s_axi_awvalid && s_axi_awready && s_axi_wvalid && s_axi_wready;
  assign ar_hs = s_axi_arvalid && s_axi_arready;

  always_ff @(posedge aclk) begin
    if (!aresetn) begin
      s_axi_awready <= 1'b0;
      s_axi_wready  <= 1'b0;
      s_axi_bvalid  <= 1'b0;
      s_axi_bresp   <= 2'b00;
      s_axi_arready <= 1'b0;
      s_axi_rvalid  <= 1'b0;
      s_axi_rresp   <= 2'b00;
      s_axi_rdata   <= '0;
      reg_imax      <= 6'd24;           // the default E3 confirmed
      reg_amp       <= 8'sd14;
      reg_mask_id   <= '0;
      reg_irq_en    <= 1'b0;
      start_pulse   <= 1'b0;
      soft_reset    <= 1'b0;
    end else begin
      start_pulse <= 1'b0;
      soft_reset  <= 1'b0;

      // write: address and data accepted together, one transaction at a time
      if (s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid &&
          !s_axi_awready && !s_axi_wready) begin
        s_axi_awready <= 1'b1;
        s_axi_wready  <= 1'b1;
      end else begin
        s_axi_awready <= 1'b0;
        s_axi_wready  <= 1'b0;
      end

      if (aw_hs) begin
        s_axi_bvalid <= 1'b1;
        s_axi_bresp  <= 2'b00;
        case (s_axi_awaddr)
          A_CTRL: begin
            start_pulse <= s_axi_wdata[0];
            soft_reset  <= s_axi_wdata[1];
            reg_irq_en  <= s_axi_wdata[2];
          end
          A_IMAX:   reg_imax    <= s_axi_wdata[ITER_BITS-1:0];
          A_MASKID: reg_mask_id <= s_axi_wdata;
          A_AMP:    reg_amp     <= s_axi_wdata[W_APP-1:0];
          default: ;
        endcase
      end else if (s_axi_bvalid && s_axi_bready) begin
        s_axi_bvalid <= 1'b0;
      end

      // read
      if (s_axi_arvalid && !s_axi_rvalid && !s_axi_arready) s_axi_arready <= 1'b1;
      else                                                  s_axi_arready <= 1'b0;

      if (ar_hs) begin
        s_axi_rvalid <= 1'b1;
        s_axi_rresp  <= 2'b00;
        case (s_axi_araddr)
          A_ID:     s_axi_rdata <= ID_MAGIC;
          A_CTRL:   s_axi_rdata <= {29'd0, reg_irq_en, 2'b00};
          A_STATUS: s_axi_rdata <= {29'd0, reg_ok, reg_done, busy_any};
          A_IMAX:   s_axi_rdata <= {26'd0, reg_imax};
          A_MASKID: s_axi_rdata <= reg_mask_id;
          A_AMP:    s_axi_rdata <= {{24{reg_amp[W_APP-1]}}, reg_amp};
          A_ITERS:  s_axi_rdata <= {26'd0, reg_last_iters};
          A_OK:     s_axi_rdata <= reg_frames_ok;
          A_FAIL:   s_axi_rdata <= reg_frames_fail;
          A_CYCLES: s_axi_rdata <= reg_cycles;
          default:  s_axi_rdata <= 32'hDEADBEEF;
        endcase
      end else if (s_axi_rvalid && s_axi_rready) begin
        s_axi_rvalid <= 1'b0;
      end
    end
  end

  // --------------------------------------------------------- the sequencer
  always_ff @(posedge aclk) begin
    if (!aresetn || soft_reset) begin
      ws              <= W_IDLE;
      wr_s_en         <= 1'b0;
      wr_m_en         <= 1'b0;
      wr_k_en         <= 1'b0;
      load_start      <= 1'b0;
      dec_start       <= 1'b0;
      reg_done        <= 1'b0;
      reg_ok          <= 1'b0;
      reg_frames_ok   <= '0;
      reg_frames_fail <= '0;
      reg_last_iters  <= '0;
      reg_cycles      <= '0;
      cycle_cnt       <= '0;
    end else begin
      wr_s_en    <= 1'b0;
      wr_m_en    <= 1'b0;
      wr_k_en    <= 1'b0;
      load_start <= 1'b0;
      dec_start  <= 1'b0;

      if (ws != W_IDLE) cycle_cnt <= cycle_cnt + 1'b1;

      case (ws)
        W_IDLE: if (start_pulse) begin
          reg_done  <= 1'b0;
          col       <= '0;
          lay       <= '0;
          kcol      <= '0;
          half      <= 1'b0;
          is_key    <= '0;
          key_cols  <= '0;
          cycle_cnt <= '0;
          ws        <= W_RX_MASK;
        end

        // ---- packet 1: the mask, 32 columns per beat
        W_RX_MASK: if (s_axis_tvalid) begin
          beat <= s_axis_tdata;
          sub  <= '0;
          ws   <= W_MASK_WR;
        end

        W_MASK_WR: begin
          wr_m_en   <= 1'b1;
          wr_m_addr <= col;
          wr_m_data <= beat[sub*2 +: 2];
          if (beat[sub*2 +: 2] == 2'd0) begin
            is_key[col] <= 1'b1;
            key_cols    <= key_cols + 1'b1;
          end
          col <= col + 1'b1;
          if (sub == 6'd31) ws  <= (col == N_B - 1) ? W_RX_SYN : W_RX_MASK;
          else              sub <= sub + 6'd1;
        end

        // ---- packet 2: the syndrome, two beats per layer
        W_RX_SYN: if (s_axis_tvalid) begin
          if (!half) begin
            lo_word <= s_axis_tdata;
            half    <= 1'b1;
          end else begin
            wr_s_en   <= 1'b1;
            wr_s_addr <= lay;
            wr_s_data <= {s_axis_tdata, lo_word};
            lay       <= lay + 1'b1;
            half      <= 1'b0;
          end
          if (s_axis_tlast) begin
            half <= 1'b0;
            ws   <= W_RX_KEY;
          end
        end

        // ---- packet 3: Bob's key, two beats per key column
        W_RX_KEY: if (s_axis_tvalid) begin
          if (!half) begin
            lo_word <= s_axis_tdata;
            half    <= 1'b1;
          end else begin
            wr_k_en   <= 1'b1;
            wr_k_addr <= kcol;
            wr_k_data <= {s_axis_tdata, lo_word};
            kcol      <= kcol + 1'b1;
            half      <= 1'b0;
          end
          if (s_axis_tlast) begin
            half <= 1'b0;
            ws   <= W_LOAD;
          end
        end

        // ---- expand into the APP memory, then decode
        W_LOAD:   begin load_start <= 1'b1; ws <= W_LOAD_W; end
        W_LOAD_W: if (dec_done) ws <= W_DEC;
        W_DEC:    begin dec_start  <= 1'b1; ws <= W_DEC_W; end

        W_DEC_W: if (dec_done) begin
          reg_ok         <= dec_ok;
          reg_last_iters <= dec_iters;
          if (dec_ok) reg_frames_ok   <= reg_frames_ok   + 1'b1;
          else        reg_frames_fail <= reg_frames_fail + 1'b1;
          col  <= '0;
          kcol <= '0;
          ws   <= W_TX_SCAN;
        end

        // ---- stream the corrected key out, key columns only
        W_TX_SCAN: begin
          if (!is_key[col]) col <= col + 1'b1;   // skip punctured and shortened
          else              ws  <= W_TX_WAIT;    // rd_app_addr is col from here
        end

        W_TX_WAIT: ws <= W_TX_LO;                // the second cycle of read latency

        W_TX_LO: if (m_axis_tready) ws <= W_TX_HI;

        W_TX_HI: if (m_axis_tready) begin
          kcol <= kcol + 1'b1;
          col  <= col + 1'b1;
          ws   <= (kcol == key_cols - 1) ? W_DONE : W_TX_SCAN;
        end

        W_DONE: begin
          reg_done   <= 1'b1;
          reg_cycles <= cycle_cnt;
          ws         <= W_IDLE;
        end

        default: ws <= W_IDLE;
      endcase
    end
  end

endmodule

`default_nettype wire
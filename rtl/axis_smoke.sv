`default_nettype none

module axis_smoke #(
    parameter int unsigned W     = 64,
    parameter int unsigned DEPTH = 1024
) (
    input  wire          clk,
    input  wire          rst_n,

    input  wire [W-1:0]  s_axis_tdata,
    input  wire          s_axis_tvalid,
    output logic         s_axis_tready,
    input  wire          s_axis_tlast,

    output logic [W-1:0] m_axis_tdata,
    output logic         m_axis_tvalid,
    input  wire          m_axis_tready,
    output logic         m_axis_tlast,

    output logic [W-1:0] checksum
);

  localparam int unsigned AW = $clog2(DEPTH);

  logic [W:0]    mem [DEPTH];      // {tlast, tdata}
  logic [AW-1:0] wr_ptr, rd_ptr;
  logic [AW:0]   count;

  logic          out_valid;
  logic [W:0]    out_data;

  wire do_wr = s_axis_tvalid & s_axis_tready;
  wire do_rd = (count != '0) & (~out_valid | m_axis_tready);

  // input side
  always_comb s_axis_tready = (count != DEPTH[AW:0]);

  always_ff @(posedge clk) begin
    if (do_wr) begin
      mem[wr_ptr] <= {s_axis_tlast, s_axis_tdata};
      wr_ptr      <= wr_ptr + 1'b1;
      checksum    <= checksum ^ s_axis_tdata;
    end
    if (!rst_n) begin
      wr_ptr   <= '0;
      checksum <= '0;
    end
  end

  // output side
  always_ff @(posedge clk) begin
    if (do_rd) begin
      out_data <= mem[rd_ptr];
      rd_ptr   <= rd_ptr + 1'b1;
    end
    if (!rst_n) rd_ptr <= '0;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      count     <= '0;
      out_valid <= 1'b0;
    end else begin
      count <= count + (do_wr ? 1'b1 : 1'b0) - (do_rd ? 1'b1 : 1'b0);
      if (do_rd)              out_valid <= 1'b1;
      else if (m_axis_tready) out_valid <= 1'b0;
    end
  end

  assign m_axis_tvalid = out_valid;
  assign m_axis_tdata  = out_data[W-1:0];
  assign m_axis_tlast  = out_data[W];

endmodule

`default_nettype wire
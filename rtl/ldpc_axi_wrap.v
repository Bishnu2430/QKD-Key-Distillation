`timescale 1ns/1ps
`default_nettype none

// Stage 13: a Verilog shell over the SystemVerilog wrapper.
//
// Vivado's IP Integrator "Add Module" cannot reference a SystemVerilog module
// at the TOP of the referenced hierarchy (UG994, Referencing a Module ->
// Limitations). It parses ldpc_axi.sv happily, lists it in the dialog, and
// leaves OK greyed out. SystemVerilog lower down is fine, so the fix is this:
// a pure Verilog-2001 module that does nothing but instantiate ldpc_axi and
// pass every port straight through.
//
// There is no logic here. If you find yourself adding any, it belongs in
// ldpc_axi.sv instead - this file exists only to satisfy a tool restriction.
//
// The port names are the ones Vivado infers AXI interfaces from, so they must
// stay exactly as they are: aclk, aresetn, s_axi_*, s_axis_t*, m_axis_t*.
module ldpc_axi_wrap #(
    parameter AXI_ADDR_W = 12
) (
    input  wire                  aclk,
    input  wire                  aresetn,

    // ---- AXI4-Lite slave: control and status
    input  wire [AXI_ADDR_W-1:0] s_axi_awaddr,
    input  wire                  s_axi_awvalid,
    output wire                  s_axi_awready,
    input  wire [31:0]           s_axi_wdata,
    input  wire [3:0]            s_axi_wstrb,
    input  wire                  s_axi_wvalid,
    output wire                  s_axi_wready,
    output wire [1:0]            s_axi_bresp,
    output wire                  s_axi_bvalid,
    input  wire                  s_axi_bready,
    input  wire [AXI_ADDR_W-1:0] s_axi_araddr,
    input  wire                  s_axi_arvalid,
    output wire                  s_axi_arready,
    output wire [31:0]           s_axi_rdata,
    output wire [1:0]            s_axi_rresp,
    output wire                  s_axi_rvalid,
    input  wire                  s_axi_rready,

    // ---- AXI4-Stream slave: mask, then syndrome, then key
    input  wire [63:0]           s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready,
    input  wire                  s_axis_tlast,

    // ---- AXI4-Stream master: the corrected key
    output wire [63:0]           m_axis_tdata,
    output wire                  m_axis_tvalid,
    input  wire                  m_axis_tready,
    output wire                  m_axis_tlast,

    output wire                  irq
);

  ldpc_axi #(
      .AXI_ADDR_W (AXI_ADDR_W)
  ) u_axi (
      .aclk          (aclk),
      .aresetn       (aresetn),

      .s_axi_awaddr  (s_axi_awaddr),
      .s_axi_awvalid (s_axi_awvalid),
      .s_axi_awready (s_axi_awready),
      .s_axi_wdata   (s_axi_wdata),
      .s_axi_wstrb   (s_axi_wstrb),
      .s_axi_wvalid  (s_axi_wvalid),
      .s_axi_wready  (s_axi_wready),
      .s_axi_bresp   (s_axi_bresp),
      .s_axi_bvalid  (s_axi_bvalid),
      .s_axi_bready  (s_axi_bready),
      .s_axi_araddr  (s_axi_araddr),
      .s_axi_arvalid (s_axi_arvalid),
      .s_axi_arready (s_axi_arready),
      .s_axi_rdata   (s_axi_rdata),
      .s_axi_rresp   (s_axi_rresp),
      .s_axi_rvalid  (s_axi_rvalid),
      .s_axi_rready  (s_axi_rready),

      .s_axis_tdata  (s_axis_tdata),
      .s_axis_tvalid (s_axis_tvalid),
      .s_axis_tready (s_axis_tready),
      .s_axis_tlast  (s_axis_tlast),

      .m_axis_tdata  (m_axis_tdata),
      .m_axis_tvalid (m_axis_tvalid),
      .m_axis_tready (m_axis_tready),
      .m_axis_tlast  (m_axis_tlast),

      .irq           (irq)
  );

endmodule

`default_nettype wire
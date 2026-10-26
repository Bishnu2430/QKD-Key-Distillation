`timescale 1ns/1ps
`default_nettype none
`include "v3_mother_1_r700_params.svh"

// Stage 12: drive the wrapper the way a Zynq system would - registers over
// AXI4-Lite, three packets in over AXI4-Stream, the corrected key out - and
// check the result against the same vectors every earlier stage used.
module tb_ldpc_axi;

  localparam int unsigned ADDR_X    = $clog2(N_B);
  localparam int unsigned W_APP     = 8;
  localparam int unsigned KEY_WORDS = N_BITS / 64;
  localparam int unsigned S_WORDS   = M_BITS / 64;

  localparam string DIR = "D:/QKD-Key-Distillation/tv/r700_q05_m16s125/";
  localparam int unsigned N_FRAMES = 2;

  localparam logic [7:0] A_ID    = 8'h00, A_CTRL  = 8'h04, A_STATUS = 8'h08,
                         A_IMAX  = 8'h0C, A_AMP   = 8'h14, A_ITERS  = 8'h18,
                         A_OK    = 8'h1C, A_FAIL  = 8'h20, A_CYCLES = 8'h24;

  logic clk = 1'b0, rst_n = 1'b0;
  always #4 clk = ~clk;

  logic [7:0]  awaddr = '0, araddr = '0;
  logic        awvalid = 1'b0, wvalid = 1'b0, bready = 1'b1;
  logic        arvalid = 1'b0, rready = 1'b1;
  logic [31:0] wdata = '0;
  logic [3:0]  wstrb = 4'hF;
  wire         awready, wready, bvalid, arready, rvalid;
  wire [1:0]   bresp, rresp;
  wire [31:0]  rdata;

  logic [63:0] s_tdata = '0;
  logic        s_tvalid = 1'b0, s_tlast = 1'b0;
  wire         s_tready;

  wire [63:0]  m_tdata;
  wire         m_tvalid, m_tlast;
  logic        m_tready = 1'b1;
  wire         irq;

  ldpc_axi #(.AXI_ADDR_W(8)) dut (
      .aclk(clk), .aresetn(rst_n),
      .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
      .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid),
      .s_axi_wready(wready), .s_axi_bresp(bresp), .s_axi_bvalid(bvalid),
      .s_axi_bready(bready),
      .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
      .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid),
      .s_axi_rready(rready),
      .s_axis_tdata(s_tdata), .s_axis_tvalid(s_tvalid), .s_axis_tready(s_tready),
      .s_axis_tlast(s_tlast),
      .m_axis_tdata(m_tdata), .m_axis_tvalid(m_tvalid), .m_axis_tready(m_tready),
      .m_axis_tlast(m_tlast),
      .irq(irq)
  );

  logic [63:0] y_words    [0:KEY_WORDS-1];
  logic [63:0] xhat_words [0:KEY_WORDS-1];
  logic [63:0] syn_words  [0:S_WORDS-1];
  logic [1:0]  mask_cls   [0:N_B-1];
  logic [63:0] rx         [0:KEY_WORDS-1];

  int rx_count, rx_last_seen;

  // ---------------------------------------------------------- AXI4-Lite
  // Two rules, and a driver needs both:
  //   sample ready at the NEGEDGE, where everything has settled - reading a
  //     combinational DUT output at the clock edge is a race, and simulators
  //     are entitled to resolve it differently;
  //   drop valid one negedge LATER, so that valid is still high across the
  //     posedge that actually completes the transfer;
  //   and CHECK BEFORE ADVANCING - "while (!ready) @(negedge clk)", not
  //     "do @(negedge clk) while (!ready)". The slave can accept the beat and
  //     drop ready within the same cycle, as this wrapper does on every mask
  //     beat; a driver that advances first never sees the acceptance, holds
  //     valid, and the beat is taken twice.
  // Sampling at the posedge passes in Verilator and loses stream beats in
  // xsim; dropping valid at the sampling negedge kills the handshake in both.
  task automatic axil_write(input logic [7:0] a, input logic [31:0] d);
    begin
      @(negedge clk);
      awaddr = a; wdata = d; awvalid = 1'b1; wvalid = 1'b1;
      while (!(awready && wready)) @(negedge clk);
      @(negedge clk);
      awvalid = 1'b0; wvalid = 1'b0;
      while (!bvalid) @(negedge clk);
    end
  endtask

  task automatic axil_read(input logic [7:0] a, output logic [31:0] d);
    begin
      @(negedge clk);
      araddr = a; arvalid = 1'b1;
      while (!arready) @(negedge clk);
      @(negedge clk);
      arvalid = 1'b0;
      while (!rvalid) @(negedge clk);
      d = rdata;
    end
  endtask

  // ------------------------------------------------------ AXI4-Stream in
  task automatic send_beat(input logic [63:0] d, input logic last);
    begin
      @(negedge clk);
      s_tdata = d; s_tvalid = 1'b1; s_tlast = last;
      while (!s_tready) @(negedge clk);
      @(negedge clk);
      s_tvalid = 1'b0; s_tlast = 1'b0;
    end
  endtask

  // the mask, 32 columns to a beat, two bits each
  task automatic send_mask;
    logic [63:0] b;
    begin
      for (int w = 0; w < N_B/32; w++) begin
        for (int i = 0; i < 32; i++) b[i*2 +: 2] = mask_cls[w*32 + i];
        send_beat(b, w == N_B/32 - 1);
      end
    end
  endtask

  // ----------------------------------------------------- AXI4-Stream out
  // Back-pressure every fourth cycle, so the transmit path is exercised with
  // a receiver that is not always ready.
  int ready_phase = 0;
  always @(negedge clk) begin
    ready_phase <= (ready_phase + 1) % 4;
    m_tready    <= (ready_phase != 2);
  end

  always @(posedge clk) begin
    if (m_tvalid && m_tready) begin
      rx[rx_count] <= m_tdata;
      rx_count     <= rx_count + 1;
      if (m_tlast) rx_last_seen <= 1;
    end
  end

  int    fd, rc, errors = 0, mismatches;
  int    e_frame, e_ok, e_iters, e_amp, d1, d2, d3, d4;
  int    n_key_words;
  string header;
  logic [31:0] v;
  logic        got_ok;

  initial begin
    $display("vectors: %s", DIR);
    $readmemh({DIR, "mask.mem"}, mask_cls);
    if ($isunknown(mask_cls[0])) $fatal(1, "no mask.mem under %s", DIR);

    fd = $fopen({DIR, "expected.csv"}, "r");
    if (fd == 0) $fatal(1, "no expected.csv under %s", DIR);
    rc = $fgets(header, fd);

    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);
    axil_read(A_ID, v);
    if (v !== 32'h514B4431) begin
      $display("ERROR: ID reads %08x, expected 514B4431", v);
      errors++;
    end else $display("ID: %08x", v);

    for (int f = 0; f < N_FRAMES; f++) begin
      rc = $fscanf(fd, "%d,%d,%d,%d,%d,%d,%d,%d\n",
                   e_frame, e_ok, e_iters, e_amp, d1, d2, d3, d4);
      $readmemh($sformatf("%sframes/%03d_y.hex",        DIR, f), y_words);
      $readmemh($sformatf("%sframes/%03d_syndrome.hex", DIR, f), syn_words);
      $readmemh($sformatf("%sframes/%03d_xhat.hex",     DIR, f), xhat_words);
      n_key_words = d3 / 64;                       // n_key_bits from the CSV

      rx_count = 0; rx_last_seen = 0;

      axil_write(A_IMAX, 32'd32);
      axil_write(A_AMP,  e_amp);
      axil_write(A_CTRL, 32'h1);                   // start

      send_mask();
      for (int w = 0; w < S_WORDS; w++)     send_beat(syn_words[w], w == S_WORDS-1);
      for (int w = 0; w < n_key_words; w++) send_beat(y_words[w],   w == n_key_words-1);

      wait (rx_last_seen);
      do axil_read(A_STATUS, v); while (!v[1]);    // wait for done
      got_ok = v[2];
      axil_read(A_ITERS, v);

      $display("frame %0d: ok=%0b iters=%0d  (expected ok=%0b iters=%0d)  %0d beats",
               f, got_ok, v, e_ok[0], e_iters, rx_count);

      if (got_ok !== e_ok[0]) begin $display("  MISMATCH: ok"); errors++; end
      if (v !== e_iters) begin
        $display("  MISMATCH: iterations, read %0d expected %0d", v, e_iters);
        errors++;
      end

      if (rx_count != n_key_words) begin
        $display("  MISMATCH: %0d beats received, expected %0d", rx_count, n_key_words);
        errors++;
      end

      mismatches = 0;
      for (int w = 0; w < n_key_words; w++)
        if (rx[w] !== xhat_words[w]) begin
          if (mismatches < 3)
            $display("    beat %0d: expected %016x got %016x", w, xhat_words[w], rx[w]);
          mismatches++;
        end
      if (mismatches != 0) begin
        $display("  MISMATCH: %0d of %0d key words", mismatches, n_key_words);
        errors++;
      end
    end

    axil_read(A_OK,     v); $display("FRAMES_OK   = %0d", v);
    axil_read(A_FAIL,   v); $display("FRAMES_FAIL = %0d", v);
    axil_read(A_CYCLES, v); $display("CYCLES      = %0d", v);

    $fclose(fd);
    if (errors == 0) $display("STAGE 12 PASSED");
    else             $display("STAGE 12 FAILED (%0d problems)", errors);
    $finish;
  end

  initial begin
    #500_000_000;
    $display("ERROR: timeout");
    $finish;
  end

endmodule

`default_nettype wire
`timescale 1ns/1ps
`default_nettype none

module tb_axis_smoke;

  localparam int W = 64, DEPTH = 1024, N = 64;

  logic clk = 1'b0, rst_n = 1'b0;
  always #4 clk = ~clk;                      // 8 ns period = 125 MHz

  logic [W-1:0] s_tdata = '0;
  logic         s_tvalid = 1'b0, s_tlast = 1'b0, m_tready = 1'b0;
  wire          s_tready, m_tvalid, m_tlast;
  wire  [W-1:0] m_tdata, checksum;

  axis_smoke #(.W(W), .DEPTH(DEPTH)) dut (
      .clk(clk), .rst_n(rst_n),
      .s_axis_tdata(s_tdata), .s_axis_tvalid(s_tvalid),
      .s_axis_tready(s_tready), .s_axis_tlast(s_tlast),
      .m_axis_tdata(m_tdata), .m_axis_tvalid(m_tvalid),
      .m_axis_tready(m_tready), .m_axis_tlast(m_tlast),
      .checksum(checksum));

  logic [W-1:0] sent [$];
  logic [W-1:0] expect_xor = '0;
  int got = 0, errors = 0;

  // driver
  initial begin
    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    for (int i = 0; i < N; i++) begin
      logic [W-1:0] d = {$urandom, $urandom};
      forever begin
        @(negedge clk);
        s_tdata  = d;
        s_tlast  = (i == N-1);
        s_tvalid = 1'b1;
        if (s_tready) break;            // the coming rising edge accepts it
      end
      @(posedge clk);
      sent.push_back(d);
      expect_xor ^= d;
    end
    @(negedge clk);
    s_tvalid = 1'b0;
    s_tlast  = 1'b0;
  end

  // receiver with random back-pressure
  initial begin
    forever begin
      @(negedge clk);
      m_tready = ($urandom_range(0, 3) != 0);     // ready about 75% of cycles
      if (m_tvalid && m_tready) begin
        automatic logic [W-1:0] d    = m_tdata;   // stable now
        automatic logic         last = m_tlast;
        @(posedge clk);                            // transfer happens here
        if (sent.size() == 0) begin
          $display("ERROR: extra word %h", d); errors++;
        end else begin
          automatic logic [W-1:0] exp = sent.pop_front();
          if (d !== exp) begin
            $display("ERROR at word %0d: expected %h, got %h", got, exp, d);
            errors++;
          end
        end
        got++;
        if (last && got != N) begin
          $display("ERROR: tlast on word %0d of %0d", got, N); errors++;
        end
      end
    end
  end

  // end of test
  initial begin
    wait (got == N);
    repeat (3) @(posedge clk);
    if (checksum !== expect_xor) begin
      $display("ERROR: checksum %h, expected %h", checksum, expect_xor);
      errors++;
    end
    $display("%0d words received, %0d errors", got, errors);
    $display(errors == 0 ? "TEST PASSED" : "TEST FAILED");
    $finish;
  end

  initial begin
    #200000;
    $display("ERROR: timeout, got %0d of %0d words", got, N);
    $finish;
  end

endmodule

`default_nettype wire
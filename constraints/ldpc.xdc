# Target: 125 MHz on the decoder's only clock (REQ-PERF-02).
# This module is synthesised out of context, so there are no pins and no I/O
# buffers; the input and output delays below are a placeholder budget for the
# logic that will eventually sit either side of it in the block design.
#
# Two port-name sets, one file: the decoder cores call the clock "clk" and the
# reset "rst_n", while the AXI wrapper must call them "aclk" and "aresetn" for
# Vivado to infer its interfaces. get_ports takes a list of patterns, so each
# line matches whichever top is set, and -quiet stops the pattern that does
# not match from warning. The clock OBJECT is named "clk" either way, so the
# two delay lines below never change.
create_clock -period 8.000 -name clk [get_ports -quiet {clk aclk}]

set_input_delay  -clock clk 2.000 \
    [filter [all_inputs] {NAME != "clk" && NAME != "aclk"}]
set_output_delay -clock clk 2.000 [all_outputs]

# Reset is applied and released by software, nowhere near a clock edge.
set_false_path -from [get_ports -quiet {rst_n aresetn}]
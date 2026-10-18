# Target: 125 MHz on the decoder's only clock (REQ-PERF-02).
# This module is synthesised out of context, so there are no pins and no I/O
# buffers; the input and output delays below are a placeholder budget for the
# logic that will eventually sit either side of it in the block design.
create_clock -period 8.000 -name clk [get_ports clk]

set_input_delay  -clock clk 2.000 [filter [all_inputs] {NAME != "clk"}]
set_output_delay -clock clk 2.000 [all_outputs]

# Reset is applied and released by software, nowhere near a clock edge.
set_false_path -from [get_ports rst_n]
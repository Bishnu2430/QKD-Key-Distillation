# 125 MHz target clock (REQ-IMP-02): 8 ns period
create_clock -period 8.000 -name clk [get_ports clk]

# Out-of-context: assume 1 ns of delay outside this block on each interface
set_input_delay  -clock clk 1.000 [filter [all_inputs] {NAME != "clk"}]
set_output_delay -clock clk 1.000 [all_outputs]

# Reset is asserted for many cycles; it does not need to meet timing
set_false_path -from [get_ports rst_n]
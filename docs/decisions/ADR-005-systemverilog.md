# ADR-005: SystemVerilog as the HDL

| Status | Accepted |
|---|---|
| Date | 2026-09-21 |
| Related | REQ-IMP-04, [13](../13-rtl-coding-guidelines.md) |

## Context
The RTL needs parameterisation, clean typing, and good support in Vivado and open-source simulators.

## Options considered
1. **SystemVerilog-2012 (synthesisable subset)**: `logic`, `always_ff/comb`, packed structs, parameters; supported by Vivado and Verilator; works with cocotb.
2. **Verilog-2001**: widest support, but more verbose and error-prone.
3. **VHDL**: strong typing; Verilator doesn't support it (GHDL would be needed).

## Decision
SystemVerilog-2012 synthesisable subset.

## Consequences
Icarus support is partial, so Verilator is the primary simulator.

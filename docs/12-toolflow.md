# 12 — Toolflow and Reproducibility

| Version | 0.1 (draft), 21 Sep 2026 |
|---|---|
| Goal | Anyone with this repo and a laptop can regenerate every number in the papers |

## 1. Environment

| Layer | Choice | Notes |
|---|---|---|
| Host OS | Windows 11 | Vivado runs natively on Windows |
| Linux tools | WSL2, Ubuntu 24.04 LTS | Python, Verilator, Icarus, cocotb |
| FPGA tools | AMD Vivado, **last 2025.x release** (see [ADR-002](decisions/ADR-002-toolchain-and-vivado-version.md)) | Install only the 7-series / Zynq-7000 device support to save disk space |
| Python | 3.11 or newer, in a venv inside WSL2 | Pin versions in `requirements.txt` |
| Simulator (primary) | Verilator 5.x | Use a version compatible with your cocotb release (check the cocotb docs); build from source if the apt version is too old |
| Simulator (secondary) | Icarus Verilog | Limited SystemVerilog support; useful for quick checks |
| Waveforms | Surfer or GTKWave | |

### 1.1 Setup checklist
- [ ] Enable WSL2 and install Ubuntu 24.04
- [ ] In WSL: `sudo apt install build-essential git python3-venv iverilog gtkwave`
- [ ] Install Verilator (apt or source), then run `verilator --version`
- [ ] `python3 -m venv .venv && source .venv/bin/activate`
- [ ] `pip install numpy numba scipy matplotlib pytest pyyaml cocotb`
- [ ] Install Vivado on Windows; record the exact version in §4
- [ ] Run the §2 "prove the flow" test

## 2. Prove the flow (Week 1)

Synthesise and implement a tiny AXI4-Stream core **out of context**. This avoids running out of package pins, because a 64-bit stream core has more ports than the package has user I/Os.

```tcl
# scripts/vivado/ooc_build.tcl  (non-project mode)
set part  xc7z020clg400-1
set top   [lindex $argv 0]
read_verilog -sv [glob rtl/*.sv]
read_xdc scripts/vivado/timing_125mhz.xdc
synth_design -top $top -part $part -mode out_of_context
opt_design
place_design
phys_opt_design
route_design
report_utilization     -file results/${top}_util.rpt
report_timing_summary  -file results/${top}_timing.rpt
report_power           -file results/${top}_power.rpt
write_checkpoint -force results/${top}_routed.dcp
```

```tcl
# scripts/vivado/timing_125mhz.xdc
create_clock -period 8.000 -name clk [get_ports clk]
```

Run it with `vivado -mode batch -source scripts/vivado/ooc_build.tcl -tclargs axis_counter`. **Pass criteria:** the reports exist, WNS ≥ 0, and you can read the LUT, FF and BRAM counts.

## 3. Power with switching activity (L6)
1. Run post-implementation timing simulation of representative frames and write a SAIF file.
2. In Vivado: `open_checkpoint` → `read_saif` → `report_power`.
3. Record the confidence level Vivado reports alongside the number (REQ-REP-02).

Exact commands go here after M5.

## 4. Version pins (fill in on install)

| Tool | Version | Date installed |
|---|---|---|
| Vivado | | |
| Verilator | | |
| Icarus Verilog | | |
| Python | | |
| cocotb | | |
| NumPy / Numba | | |

## 5. Reproducing a result
Every file in `results/` starts with a header:

```yaml
commit: <git sha>
tools: {vivado: "...", verilator: "...", python: "..."}
part: xc7z020clg400-1
clock_ns: 8.000
wns_ns: ...
rng_seed: ...
command: "<exact command line>"
```

To reproduce: `git checkout <commit>`, set up the §4 tool versions, then run `command`.

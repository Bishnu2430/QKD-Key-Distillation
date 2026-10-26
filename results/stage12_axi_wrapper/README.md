# Stage 12 — The decoder as an AXI peripheral

`ldpc_axi` wraps the chunked r700 decoder in the two interfaces a Zynq system
speaks: AXI4-Lite for its ten registers, one AXI4-Stream in carrying three
packets (mask, syndrome, key) and one out carrying the corrected key. It is the
first build in which the decoder is not the top module.

**It works, it closes timing, and it is 4,549 LUTs smaller than the decoder was
on its own.**

## Simulation

Two frames driven entirely through AXI, in xsim, against
`tv/r700_q05_m16s125/`:

```
ID: 514b4431
frame 0: ok=1 iters=13  (expected ok=1 iters=13)  742 beats
frame 1: ok=1 iters=16  (expected ok=1 iters=16)  742 beats
FRAMES_OK   = 2
FRAMES_FAIL = 0
CYCLES      = 185649
STAGE 12 PASSED
```

Every number arrived over an interface: the ID from a register read, `ok` and
`iterations` from `STATUS` and `LAST_ITERS`, and all 742 key words per frame
from the output stream with the receiver stalling one cycle in four. Identical
to the Verilator pre-check, down to the cycle count.

## Implementation

| | stage 11, r700 chunked | **stage 12, `ldpc_axi`** | Δ |
|---|---|---|---|
| WNS | +0.079 ns | **+0.013 ns** | −0.066 |
| Failing endpoints | 0 | **0 of 37,476** | — |
| Slice LUTs | 29,486 (55.4%) | **24,937 (46.9%)** | **−4,549** |
| Slice registers | — | 15,006 (14.1%) | — |
| Block RAM tiles | 44.5 (31.8%) | **44.5 (31.8%)** | 0 |
| Dynamic power | 0.791 W | 0.815 W | +0.024 |

Total on-chip power 0.935 W, static 0.120 W, junction 35.8 °C. Routing is
clean: zero nets with routing errors, zero DRC violations, WHS +0.016 ns.

### The LUT count fell, and that was not the prediction

The forecast was **+400 to +700 LUTs** for a register file, two counters and
the sign-bit extraction. The build came in **4,549 LUTs lower**, so the decoder
itself must have shed something over 5,000.

The likely cause is the module boundary disappearing. Synthesised out of
context as the top, `ldpc_decoder_chunk` has to support arbitrary values on a
1,024-bit APP load port and 128-bit key and syndrome ports — none of it can be
optimised away, because anything could drive it. Instantiated inside the
wrapper, those ports are fed by a 64-bit stream through known logic, and the
wide load muxing collapses into it.

That is an inference from the port widths, not a measurement: this flow emits
no per-instance utilization. `report_utilization -hierarchical` on
`ldpc_axi_routed.dcp` would settle it, and is worth running before the figure
is quoted anywhere that matters.

The practical reading is that **the stage-11 area figures were pessimistic for
any build where the decoder is a submodule** — which, from here on, is every
build.

### Where the margin went

WNS fell from +0.079 to +0.013 ns — 0.16% of the clock period. The two worst
paths both end at a block RAM and are almost entirely routing:

| | Worst | Second |
|---|---|---|
| Slack | +0.013 ns | +0.066 ns |
| From | `u_dec/layer_q_reg[2]_rep__2` | `u_dec/state_reg[1]` |
| To | `u_dec/cn_mem_reg_26/ADDRBWRADDR[9]` | `u_dec/app_mem_reg_7/DIBDI[19]` |
| Logic levels | **0** | 4 |
| Route share | 6.881 of 7.337 ns (**93.8%**) | 6.519 of 7.609 ns (85.7%) |

Zero logic levels on the worst path means there is nothing left to pipeline:
it is a flip-flop output reaching a block RAM address pin on the other side of
the die. Vivado had already replicated the driver (`_rep__2`) and the net still
has fanout 36.

This is **not** a congestion wall. The third-worst path is at +0.122 ns and the
tenth at +0.212 ns, so only two paths are tight. A different placer directive
would most likely clear both.

### Why this matters for stage 13

+0.013 ns will probably not survive the block design. Three things change: the
clock arrives from `FCLK_CLK0` through the PS rather than from a port, the
wrapper stops being synthesised out of context, and the DMA and interconnect
compete for the same fabric. If stage 13 fails timing, the fix is a placement
directive (`Performance_ExplorePostRoutePhysOpt`) rather than an RTL change —
there is no logic on the critical path to restructure.

## The constraints file now serves both port-name sets

Stage 12 had to rename `clk`/`rst_n` to `aclk`/`aresetn` so Vivado would infer
the AXI interfaces. That silently invalidated `constraints/ldpc.xdc`: the first
build of this module produced four CRITICAL WARNINGs and **no clock at all**,
which still completes and still writes a timing report.

`get_ports` takes a list of patterns, so one file now matches whichever top is
set, with `-quiet` suppressing the pattern that misses:

```tcl
create_clock -period 8.000 -name clk [get_ports -quiet {clk aclk}]
```

The clock *object* keeps the name `clk` either way, so every constraint and
every timing report filed before this one still refers to the same thing.

## Requirements

| | Target | Status |
|---|---|---|
| REQ-IMP-02 timing | WNS ≥ 0 at 125 MHz | ✅ +0.013 ns, no failing endpoints |
| REQ-IMP-03 resources | ≤70% LUT, ≤80% BRAM | ✅ 46.9% / 31.8% |
| REQ-PERF-06 power | ≤1.0 W dynamic | ✅ 0.815 W (vectorless) |

Power is vectorless and has varied ±20% with placement across this project;
only the stage-9 build has a SAIF measurement. The final system build should be
re-measured before any power number is quoted.

## Files

| File | Contents |
|---|---|
| `axi_simulate.log` | The xsim run, two frames through AXI |
| `axi_timing_summary_routed.rpt` | WNS +0.013 ns, 0 of 37,476 endpoints failing |
| `axi_utilization_placed.rpt` | 46.9% LUT, 31.8% block RAM |
| `axi_power_routed.rpt` | 0.935 W total, 0.815 W dynamic |
| `axi_route_status.rpt` | Fully routed, zero nets with routing errors |

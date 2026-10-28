# Stage 13 — The block design

The decoder in a real Zynq system: ZYNQ7 PS, an AXI DMA moving both streams
through `S_AXI_HP0`, an interconnect and a SmartConnect, and `ldpc_axi` in the
middle behind a Verilog shell. Built to a bitstream on `xc7z020clg400-1`.

**It closes at 125 MHz with more margin than the standalone module had, and
the entire AXI plumbing costs 23 mW.**

## System, post-route

| | Value |
|---|---|
| Clock | `clk_fpga_0`, **125.000 MHz** exactly |
| WNS | **+0.072 ns**, 0 failing of 49,364 endpoints |
| WHS | +0.033 ns |
| Slice LUTs | 28,241 (53.08%) |
| Slice registers | 18,996 (17.85%) |
| Block RAM tiles | 53.5 (38.21%) |
| Total on-chip power | 2.541 W |
| Junction temperature | 54.3 °C (max ambient 55.7 °C) |

Fully routed, zero nets with routing errors, zero DRC violations.

## Where it all goes

| Block | LUTs | FFs | BRAM tiles | Dynamic power |
|---|---|---|---|---|
| `ldpc_axi_wrap_0` — decoder and wrapper | **25,489** | 15,217 | **44.5** | **0.824 W** |
| `axi_dma_0` | 1,567 | 2,336 | 9 | 0.012 W |
| `axi_smc` — SmartConnect | 603 | 723 | 0 | 0.008 W |
| `axi_mem_intercon` | 567 | 687 | 0 | 0.003 W |
| `processing_system7_0` | hard silicon | — | — | **1.524 W** |

### The accelerator costs what stage 12 said it did

| | stage 12, out of context | stage 13, inside the system |
|---|---|---|
| LUTs | 24,937 | 25,489 (+2.2%) |
| Block RAM tiles | 44.5 | 44.5 (unchanged) |
| Dynamic power | 0.815 W | 0.824 W (+1.1%) |

Everything measured about the module in isolation survived integration within
a couple of percent. That is not guaranteed — a module can behave quite
differently once it competes for placement — and it means the stage-6 to
stage-12 measurements remain quotable rather than needing to be redone.

It also **settles the open question from stage 12**, where the LUT count fell
4,549 against stage 11 and the explanation was inferred from port widths
rather than measured. `report_utilization -hierarchical` now shows the decoder
at 25,489 LUTs as a submodule against 29,486 as the stage-11 top. The drop is
real, it persists, and the cause was the module boundary: as an out-of-context
top the decoder had to support arbitrary values on a 1,024-bit APP load port,
and inside a wrapper fed by a 64-bit stream that load muxing collapses.

### The AXI plumbing is nearly free

DMA, SmartConnect and interconnect together: **2,737 LUTs (5.1% of the
device), 9 block RAM tiles, and 23 mW.** For that you get both streams moving
through `S_AXI_HP0` at 64 bits with no CPU copying.

The nine block RAM tiles are all inside the DMA's `I_PRMRY_DATAMOVER` — its
stream FIFOs — and were forecast at 2 to 4. That was the one resource
prediction that missed badly, and it is worth remembering if a future stage
adds a second DMA.

### Power, read correctly

| | W | What it is |
|---|---|---|
| Decoder | **0.824** | the accelerator — compare against REQ-PERF-06 |
| All programmable logic | **0.847** | decoder + DMA + both interconnects |
| `processing_system7_0` | 1.524 | ARM cores, DDR controller, peripherals |
| Static | 0.170 | leakage |
| **Total on-chip** | **2.541** | |

**The PS is 64% of dynamic power and none of it is the accelerator's.** It is
hard silicon that draws this whether or not a decoder exists in the fabric.
Quoting 2.541 W as "the cost of LDPC reconciliation" would overstate it by
roughly three times; quoting 0.824 W under a heading that says "system power"
would understate it. Both figures are here so the thesis can use whichever the
sentence actually means.

Still vectorless. Only the stage-9 build carries a SAIF measurement, and
vectorless estimates have moved ±20% with placement across this project.

## Timing, and a prediction that went the wrong way

The stage-13 document expected the margin to shrink — a BUFG clock from the
PS, no out-of-context synthesis, and the DMA competing for fabric. It grew
instead, +0.013 → **+0.072 ns**.

More telling than the number is that the **critical path moved entirely**:

| | stage 12 | stage 13 |
|---|---|---|
| From | `layer_q_reg[2]_rep__2` | `u_dec/t_q_reg[32][0]` |
| To | `cn_mem_reg_26/ADDRBWRADDR[9]` | `u_dec/idx_reg[32][0]/CE` |
| Logic levels | 0 | 6 |
| Route share | 93.8% | 71.8% |

Stage 12's bottleneck — a flip-flop reaching a block RAM address pin with
nothing in between — is gone. The new one is inside the check-node
minimum-finder and has six levels of logic, so unlike the old one it could be
restructured if margin were ever needed.

The honest reading is that **±0.07 ns is placement noise on a route-dominated
design**, not a trend. Across stage 11 (+0.079), stage 12 (+0.013) and stage 13
(+0.072) the same RTL has landed anywhere in that band depending on where the
placer put the memories. Any future claim about a change improving timing by
less than about 0.1 ns needs more than one build behind it.

## Headroom for what remains

| | Used | Free |
|---|---|---|
| Slice LUTs | 28,241 (53.1%) | **24,959** |
| Block RAM tiles | 53.5 (38.2%) | **86.5** |

Comfortable for stage 14 (error verification with a Toeplitz tag) and stage 15
(privacy amplification). Resource pressure is not the binding constraint on
the rest of this project.

## Requirements

| | Target | Status |
|---|---|---|
| REQ-IMP-02 timing | WNS ≥ 0 at 125 MHz | ✅ +0.072 ns, 0 failing |
| REQ-IMP-03 resources | ≤70% LUT, ≤80% BRAM | ✅ 53.1% / 38.2% |
| REQ-PERF-06 power | ≤1.0 W dynamic | ✅ 0.824 W decoder, 0.847 W all PL |

## What this does not show

Nothing ran. There is no board, so the block design is **built, not executed**.

The functional evidence is stage 12's: two frames driven through the identical
AXI interfaces in xsim, matching the reference on `ok`, iteration count and all
742 key words per frame. Stage 13 adds integration and cost — that the
interfaces infer, the address map closes, and the system fits and meets timing.

`ldpc_axi_wrap_0/S_AXI` sits at **`0x4000_0000`** with a 4 KB range, recorded
in [docs/08-interfaces-regmap.md](../../docs/08-interfaces-regmap.md).

## Files

| File | Contents |
|---|---|
| `system_timing_summary_routed.rpt` | WNS +0.072 ns, 0 of 49,364 failing |
| `system_utilization_placed.rpt` | 53.08% LUT, 38.21% block RAM |
| `system_utilization_hier.rpt` | The per-block split above |
| `system_power_routed.rpt` | 2.541 W total, 1.523 W of it PS7 |
| `system_power_hier.rpt` | Per-block power, decoder at 0.824 W |
| `system_route_status.rpt` | Fully routed, no routing errors |

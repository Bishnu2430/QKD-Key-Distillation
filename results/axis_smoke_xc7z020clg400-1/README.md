# Week-1 Toolflow Proof — Performance and Evaluation Report

| Field | Value |
|---|---|
| Design | `axis_smoke` — AXI4-Stream FIFO, W = 64, DEPTH = 1024, with running XOR checksum |
| Purpose | Prove the no-board methodology end to end, **not** an accelerator result |
| Part | `xc7z020clg400-1` (Zynq-7020, clg400, speed grade −1) |
| Tool | Vivado ML Standard v2025.2 (SW Build 6299465) |
| Flow | GUI, project mode, **out-of-context** synthesis; run `impl_1` |
| Date | 11 Oct 2026 |
| Machine-readable summary | [result.yaml](result.yaml) |

**Verdict: PASS.** Timing met with large margin, block RAM inferred correctly, out-of-context confirmed, no latches, behavioural simulation passed.

---

## 1. Timing

### 1.1 Summary (post-route)

| Metric | Value | Pass condition | Status |
|---|---|---|---|
| WNS (worst setup slack) | **+2.565 ns** | ≥ 0 | met |
| TNS (total negative slack) | 0.000 ns | 0 | met |
| WHS (worst hold slack) | **+0.151 ns** | ≥ 0 | met |
| THS | 0.000 ns | 0 | met |
| WPWS (pulse width) | +3.500 ns | ≥ 0 | met |
| Failing endpoints | 0 of 428 | 0 | met |

Clock constraint: `clk`, period 8.000 ns (125.000 MHz), waveform {0.000 4.000}.

**Estimated Fmax** = 1 / (8.000 − 2.565) ns = **184.0 MHz**, which is 47% above the 125 MHz target. The design would meet timing at any clock up to roughly that figure; this is an estimate from static analysis, not a measured frequency.

### 1.2 Worst setup path

| Property | Value |
|---|---|
| Source | `mem_reg_0/CLKBWRCLK` (RAMB36E1, site RAMB36_X3Y12) |
| Destination | `m_axis_tdata[0]` (output port) |
| Requirement | 8.000 ns |
| Data path delay | **3.427 ns** — logic 2.454 ns (71.6%), routing 0.973 ns (28.4%) |
| Logic levels | 0 |
| Clock path skew | −0.973 ns |
| Clock uncertainty | 0.035 ns (system jitter 0.071 ns) |
| Output delay constraint | 1.000 ns |
| Arrival / required | 4.400 ns / 6.965 ns |

**Reading:** the critical path is the block RAM's clock-to-output delay (2.454 ns) followed by routing to the output port. There is no combinational logic in it at all — zero logic levels. For the real decoder this is the pattern to expect: memory access dominates, and the way to go faster is pipelining around the memory rather than simplifying logic.

### 1.3 Worst hold path

| Property | Value |
|---|---|
| Source | `wr_ptr_reg[7]/C` (FDRE) |
| Destination | `mem_reg_1/ADDRARDADDR[12]` (RAMB36E1) |
| Data path delay | 0.302 ns — logic 0.128 ns (42.4%), routing 0.174 ns (57.6%) |
| Slack | +0.151 ns |

Hold margin is thin in absolute terms, which is normal for a short address path, and the tool closed it without help.

---

## 2. Resource utilisation

| Resource | Used | Available | Utilisation |
|---|---|---|---|
| Slice LUTs | 97 | 53,200 | 0.18% |
| — LUT as logic | 97 | 53,200 | 0.18% |
| — LUT as memory | 0 | 17,400 | 0.00% |
| Slice registers (all flip-flops) | 96 | 106,400 | 0.09% |
| — Registers as latch | **0** | — | must stay 0 |
| CARRY4 | 3 | 13,300 | 0.02% |
| F7 / F8 muxes | 0 | — | — |
| **Block RAM tile** | **2** (both RAMB36E1) | 140 | 1.43% |
| RAMB18 | 0 | 280 | 0.00% |
| DSP48E1 | 0 | 220 | 0.00% |
| Bonded IOB | **0** | 125 | confirms out-of-context |
| BUFGCTRL | 0 | 32 | OOC: no global buffer inserted |

**Checks that matter:**
- **BRAM = 2** is exactly right. The memory is 1,024 × 65 bits ≈ 66.6 Kb, and a RAMB36 holds 36 Kb, so two tiles. The array became true block RAM, not LUT RAM (LUT as memory = 0) and not registers.
- **Latches = 0**, so no accidental combinational loops or incomplete `always_comb` branches.
- **IOB = 0** confirms out-of-context synthesis was active; otherwise ~200 ports would have demanded pins the clg400 package does not have.
- The 3 CARRY4 cells are the pointer and occupancy counters.

---

## 3. Power

Estimated at the typical process corner, **vectorless** (no switching-activity file). Vivado reports confidence **Medium**.

### 3.1 On-chip breakdown

| Component | Power (W) | Share of total | Share of dynamic |
|---|---|---|---|
| Clocks | 0.001 | 0.9% | 12.5% |
| Slice logic (LUT, FF, CARRY4) | < 0.001 | < 0.9% | < 12.5% |
| Signals | < 0.001 | < 0.9% | < 12.5% |
| **Block RAM** | **0.006** | 5.4% | **75%** |
| **Dynamic total** | **0.008** | 7.2% | 100% |
| **Device static (leakage)** | **0.103** | **92.8%** | — |
| **Total on-chip** | **0.111** | 100% | — |

**Reading:** at this size, leakage dominates completely — the logic is 0.2% of the device. The useful observation for the project is that **block RAM is 75% of the dynamic power**. The accelerator will use 30–45 BRAMs rather than 2, so memory will dominate its dynamic power, and reducing memory traffic (compressed check-node storage, fewer passes over the APP array) is also a power optimisation, not just an area one.

### 3.2 Supply

| Rail | Voltage | Total current | Dynamic | Static |
|---|---|---|---|---|
| Vccint | 1.000 V | 0.016 A | 0.008 A | 0.007 A |

### 3.3 Thermal

| Property | Value |
|---|---|
| Ambient temperature | 25.0 °C |
| **Junction temperature** | **26.3 °C** |
| Maximum allowed ambient | 83.7 °C |
| **Thermal margin** | **58.7 °C** |
| Effective θJA | 11.5 °C/W |
| Airflow | 250 LFM, no heat sink |
| Board model | medium 10"×10", 8–11 layers |

A 1.3 °C rise over ambient. Thermally this design is invisible; the figure matters only as a baseline to compare the full accelerator against.

---

## 4. Derived performance metrics

| Metric | Value | How it was derived |
|---|---|---|
| Throughput at the 125 MHz constraint | **8.0 Gbit/s** | 64 bits × 125 MHz (one word per cycle, no stalls) |
| Throughput at estimated Fmax | 11.8 Gbit/s | 64 bits × 184.0 MHz |
| Dynamic energy per bit | **1.0 pJ/bit** | 0.008 W ÷ 8.0 Gbit/s |
| Total energy per bit (incl. leakage) | 13.9 pJ/bit | 0.111 W ÷ 8.0 Gbit/s |
| Minimum latency | 2 cycles = **16 ns** at 125 MHz | Write cycle, then registered memory read |
| Buffer capacity | 1,024 words = 65,536 bits | DEPTH × W, i.e. one full LDPC frame |

The last row is a useful coincidence: the test FIFO holds exactly one 65,536-bit frame, so these numbers are a rough floor for what frame buffering alone will cost in the real design (2 BRAM, 1 pJ/bit dynamic).

---

## 5. Functional verification

| Check | Result |
|---|---|
| Behavioural simulation (`tb_axis_smoke`, random back-pressure, 64 words) | **TEST PASSED** |
| Word order and content preserved | Yes |
| `tlast` position preserved | Yes |
| Final checksum matches the testbench XOR | Yes |
| Post-implementation timing simulation | Not run (planned for M5) |
| SAIF-based power | Not run (planned for M5) |

---

## 6. What this does and does not establish

**Established:**
1. The SystemVerilog subset in [13-rtl-coding-guidelines](../../docs/13-rtl-coding-guidelines.md) elaborates and synthesises cleanly.
2. Memory written as in the coding guidelines infers block RAM, with no latches.
3. Out-of-context synthesis works, so port-heavy blocks can be implemented on this package.
4. The AXI4-Stream handshake is implemented correctly under random back-pressure.
5. The complete evidence chain works: constraint → implementation → timing, area and power reports → repository record.

**Not established:** anything about the accelerator's performance. This design has 0 logic levels on its critical path and 2 BRAMs; the LDPC decoder will have deep arithmetic and 30–45 BRAMs. Treat these numbers only as a floor and as proof that the method works.

---

## 7. Files

| File | Source |
|---|---|
| `axis_smoke_timing_summary_routed.rpt` | Copied from `vivado/axis_smoke/axis_smoke.runs/impl_1/` |
| `axis_smoke_utilization_placed.rpt` | Same |
| `axis_smoke_power_routed.rpt` | Same |
| `result.yaml` | Machine-readable summary (REQ-REP-01) |

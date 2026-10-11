# 15 — Vivado GUI Guide (you drive, start to finish)

| Version | 0.2, 11 Oct 2026 |
|---|---|
| Tool | Vivado ML Standard **2025.2**, installed at `D:\AMDDesignTools\2025.2\Vivado` |
| Target part | `xc7z020clg400-1` (Zynq-7020, clg400 package, speed grade −1) |
| Covers | Week-1 flow test, end to end: project → RTL → constraints → synthesis → implementation → reports → simulation → SAIF power |

> **Working rule.** Everything inside Vivado is done **by you, in the GUI**. Claude does not create Vivado projects, RTL, constraints or Tcl scripts, does not run the tool, and does not touch your Vivado project folder. Claude writes documentation and the Python-side models, explains messages you paste in, and records your results. Reference code in this guide is **material for you to type and adapt**, not files Claude places in the repo.

Menu paths are for 2025.2. Other versions move things slightly; the wording nearby is usually the same.

---

## 0. Before you open Vivado

### 0.1 Folder layout

| Folder | Holds | In git? |
|---|---|---|
| `D:\QKD-Key-Distillation\rtl\` | Your SystemVerilog design files | **Yes** |
| `D:\QKD-Key-Distillation\constraints\` | XDC constraint files | **Yes** |
| `D:\QKD-Key-Distillation\tb\` | Testbenches | **Yes** |
| `D:\QKD-Key-Distillation\results\` | Reports you copy out of Vivado, plus a `result.yaml` per run | **Yes** |
| `D:\QKD-Key-Distillation\vivado\` | The Vivado project itself (`.xpr`, `.runs`, `.cache`, `.sim`) | **No** |

The project folder is a build artefact: it is large, it churns on every run, and it can always be recreated from the sources. The sources and the reports are what matter.

### 0.2 Add the ignore rule
Open `.gitignore` (any text editor) and add a line:

```
vivado/
```

### 0.3 Create the folders
In File Explorer, create `vivado` and `constraints` under `D:\QKD-Key-Distillation` if they don't exist. (`rtl`, `tb` and `results` already exist.)

### 0.4 Housekeeping on your earlier trial
You created a project called `axis_flow` in the repo root while testing the installation. Either delete that folder, or move it into `vivado\`. It is not needed.

---

## 1. Create the project

1. **Start → Vivado 2025.2.**
2. On the welcome screen: **Create Project** → **Next**.
3. **Project Name** page:
   - *Project name:* `axis_smoke`
   - *Project location:* `D:/QKD-Key-Distillation/vivado`
   - Tick **Create project subdirectory** (you get `vivado/axis_smoke/`)
   - **Next**
4. **Project Type** page: select **RTL Project**, and tick **Do not specify sources at this time**. You will add sources deliberately in step 2, which avoids the wizard copying files into the project. → **Next**
5. **Default Part** page: click the **Parts** tab (not *Boards*), then set the filters:
   - *Category:* All · *Family:* **Zynq-7000** · *Package:* **clg400** · *Speed:* **-1**
   - Select the row **`xc7z020clg400-1`** → **Next**
6. **Summary** page: confirm it reads Family *Zynq-7000*, Package *clg400*, Speed *-1* → **Finish**.

Vivado opens the project. The part is shown in the top-right corner of the window — check it says `xc7z020clg400-1` before doing anything else.

### 1.1 Project settings
*Tools → Settings → Project Settings → General*:

| Setting | Value | Why |
|---|---|---|
| Target language | Verilog | Only affects generated netlists and templates; SystemVerilog sources work regardless |
| Simulator language | Mixed | Lets the simulator handle both Verilog and VHDL models |

Click **OK**.

---

## 2. Write the flow-test design

### 2.1 What this design is for

It is **not** part of the accelerator. Its job is to prove, in one small run, that:

| Proves | How this design proves it |
|---|---|
| SystemVerilog elaborates in Vivado | The module uses `logic`, `always_ff`, `always_comb`, parameters |
| Block RAM inference works | A 1,024 × 65-bit memory written and read synchronously must become BRAM, not LUT RAM |
| The AXI4-Stream handshake is implemented correctly | Both a slave and a master port with `tvalid`/`tready`/`tlast` |
| Logic is not optimised away | A running XOR checksum that reaches an output port |
| Timing closes at 125 MHz on this part | The critical path runs through the memory and the pointer arithmetic |
| The report flow works | Utilisation, timing and power reports all have something real to report |

### 2.2 Specification (write to this, not to my code)

**Module:** `axis_smoke`, parameters `W` (data width, default 64) and `DEPTH` (words, default 1024, a power of two).

**Ports**

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `clk` | in | 1 | Clock |
| `rst_n` | in | 1 | Synchronous reset, active low |
| `s_axis_tdata` | in | W | Input stream data |
| `s_axis_tvalid` | in | 1 | Input data is valid |
| `s_axis_tready` | out | 1 | We can accept a word this cycle |
| `s_axis_tlast` | in | 1 | Last word of the input frame |
| `m_axis_tdata` | out | W | Output stream data |
| `m_axis_tvalid` | out | 1 | Output data is valid |
| `m_axis_tready` | in | 1 | Downstream can accept a word |
| `m_axis_tlast` | out | 1 | Last word of the output frame |
| `checksum` | out | W | Running XOR of every accepted input word |

**Behaviour**

1. A word is **accepted** on any rising edge where `s_axis_tvalid && s_axis_tready`. Accepted words are written into memory at `wr_ptr`, along with their `tlast` bit, and XORed into `checksum`.
2. A word is **issued** on any rising edge where `m_axis_tvalid && m_axis_tready`.
3. Words come out in the order they went in (first in, first out), with their `tlast` bit preserved.
4. `s_axis_tready` is high whenever the FIFO is not full.
5. `m_axis_tvalid` is high whenever a word is waiting in the output register.

**Rules you must not break (AXI4-Stream)**

- `m_axis_tvalid` must **not** depend combinationally on `m_axis_tready`. Make `m_axis_tvalid` come straight from a register. (The reverse is allowed: your internal read-enable may look at `m_axis_tready`.)
- Once `m_axis_tvalid` is high, the data must stay stable until the cycle where `m_axis_tready` is also high.
- No data may be lost or duplicated when the downstream stalls.

**Internal state**

| Signal | Width | Purpose |
|---|---|---|
| `mem` | DEPTH × (W+1) | Storage: `{tlast, tdata}` |
| `wr_ptr`, `rd_ptr` | log2(DEPTH) | Write and read addresses |
| `count` | log2(DEPTH)+1 | Occupancy, 0…DEPTH, so it needs one extra bit |
| `out_valid` | 1 | Output register holds a valid word |
| `out_data` | W+1 | Output register |

**The one subtle part.** The memory read is synchronous: data appears one cycle after the address. So the design reads from memory into an output register, and `m_axis_tvalid` reflects that register. Read only when there is something to read **and** the output register is free or being emptied this cycle:

```
read_enable = (count != 0) && (!out_valid || m_axis_tready)
```

That single line is what makes the FIFO both correct under back-pressure and compliant with the handshake rules.

### 2.3 Reference implementation

Type this in (or write your own to the specification above — the exercise is more useful if you try first and compare afterwards).

```systemverilog
`default_nettype none

module axis_smoke #(
    parameter int unsigned W     = 64,
    parameter int unsigned DEPTH = 1024
) (
    input  wire          clk,
    input  wire          rst_n,

    input  wire [W-1:0]  s_axis_tdata,
    input  wire          s_axis_tvalid,
    output logic         s_axis_tready,
    input  wire          s_axis_tlast,

    output logic [W-1:0] m_axis_tdata,
    output logic         m_axis_tvalid,
    input  wire          m_axis_tready,
    output logic         m_axis_tlast,

    output logic [W-1:0] checksum
);

  localparam int unsigned AW = $clog2(DEPTH);

  logic [W:0]    mem [DEPTH];      // {tlast, tdata}
  logic [AW-1:0] wr_ptr, rd_ptr;
  logic [AW:0]   count;

  logic          out_valid;
  logic [W:0]    out_data;

  wire do_wr = s_axis_tvalid & s_axis_tready;
  wire do_rd = (count != '0) & (~out_valid | m_axis_tready);

  // ---- input side -------------------------------------------------------
  always_comb s_axis_tready = (count != DEPTH[AW:0]);

  always_ff @(posedge clk) begin
    if (do_wr) begin
      mem[wr_ptr] <= {s_axis_tlast, s_axis_tdata};
      wr_ptr      <= wr_ptr + 1'b1;
      checksum    <= checksum ^ s_axis_tdata;
    end
    if (!rst_n) begin
      wr_ptr   <= '0;
      checksum <= '0;
    end
  end

  // ---- output side ------------------------------------------------------
  always_ff @(posedge clk) begin
    if (do_rd) begin
      out_data <= mem[rd_ptr];
      rd_ptr   <= rd_ptr + 1'b1;
    end
    if (!rst_n) rd_ptr <= '0;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      count     <= '0;
      out_valid <= 1'b0;
    end else begin
      count <= count + (do_wr ? 1'b1 : 1'b0) - (do_rd ? 1'b1 : 1'b0);
      if (do_rd)              out_valid <= 1'b1;
      else if (m_axis_tready) out_valid <= 1'b0;
    end
  end

  assign m_axis_tvalid = out_valid;
  assign m_axis_tdata  = out_data[W-1:0];
  assign m_axis_tlast  = out_data[W];

endmodule

`default_nettype wire
```

### 2.4 Why it is written this way

| Line or construct | Reason |
|---|---|
| `` `default_nettype none `` at the top, `wire` at the end | Makes a typo in a signal name an error instead of an implicit 1-bit wire. One of the cheapest bug-catchers in Verilog |
| `parameter int unsigned W, DEPTH` | REQ-IMP-05: every width and size is a parameter, so sweeps don't need edits |
| `logic [W:0] mem [DEPTH]` with **no reset** | A memory array with a reset cannot be inferred as block RAM. This omission is deliberate and necessary |
| Write and read in **separate** `always_ff` blocks | Maps cleanly onto a simple dual-port BRAM (one write port, one read port) |
| `out_data <= mem[rd_ptr]` (registered read) | 7-series block RAM has a synchronous read. An asynchronous read forces LUT RAM instead |
| `s_axis_tready` from `count` only | Keeps the input handshake free of any dependence on `m_axis_tready` |
| `m_axis_tvalid = out_valid` (a register) | The AXI rule: valid must not depend combinationally on ready |
| `count` is `AW+1` bits | It must represent DEPTH (1024), which needs 11 bits, not 10 |
| Reset written as a trailing `if (!rst_n)` | Synchronous reset, and it overrides the earlier non-blocking assignments in the same block. Only control state is reset, never the memory |
| `checksum` reaches a port | Stops synthesis from trimming the datapath as unused |

### 2.5 Create the file in Vivado

1. Flow Navigator → **PROJECT MANAGER → Add Sources**.
2. Select **Add or create design sources** → **Next**.
3. Click **Create File**:
   - *File type:* **SystemVerilog**
   - *File name:* `axis_smoke.sv`
   - *File location:* click the dropdown → **Choose Location…** → browse to `D:/QKD-Key-Distillation/rtl` → **Select**
   - **OK**
4. **Finish**.
5. A **Define Module** dialog appears asking for ports. Click **Cancel** (and **Yes** if it asks to confirm) — you are writing the ports yourself.
6. In the **Sources** pane, expand *Design Sources*, double-click `axis_smoke.sv`, and type the module into the editor.
7. **Ctrl+S** to save.

**Checks after saving:**
- The **Sources** pane shows `axis_smoke` as the top module, in **bold**. If it doesn't, right-click the module → **Set as Top**.
- The file appears under *Design Sources*, not under *Non-module files*. If it does, the file type is wrong: right-click → **Set File Type → SystemVerilog**.
- No red error markers in the editor margin.

---

## 3. Write the timing constraints

### 3.1 Create the file
1. **Add Sources** → **Add or create constraints** → **Next** → **Create File**:
   - *File type:* **XDC** · *File name:* `timing_125mhz.xdc`
   - *File location:* **Choose Location…** → `D:/QKD-Key-Distillation/constraints` → **Select** → **OK**
2. **Finish**, then open the file from *Sources → Constraints* and type the four lines below.

### 3.2 What to write

```tcl
# 125 MHz target clock (REQ-IMP-02): 8 ns period
create_clock -period 8.000 -name clk [get_ports clk]

# Out-of-context: assume 1 ns of delay outside this block on each interface
set_input_delay  -clock clk 1.000 [filter [all_inputs] {NAME != "clk"}]
set_output_delay -clock clk 1.000 [all_outputs]

# Reset is asserted for many cycles; it does not need to meet timing
set_false_path -from [get_ports rst_n]
```

### 3.3 Line by line

| Line | What it does | What happens without it |
|---|---|---|
| `create_clock` | Declares the clock and its period. Everything in the timing report is measured against this | No clock, so no timing analysis at all. The report says "no clocks" and WNS is meaningless |
| `set_input_delay` | Says "upstream logic consumes 1 ns before data arrives at my input". The filter excludes the clock port, which must not carry an input delay | Input paths are unconstrained and silently ignored in the report |
| `set_output_delay` | Says "downstream logic needs 1 ns after my output" | Output paths unconstrained |
| `set_false_path -from rst_n` | Tells the tool not to time the reset net, which fans out widely and is held for many cycles | A long reset net can dominate the critical path and produce a fake timing failure |

The 1 ns figures are a convention for a block that will later sit inside a larger design; they make the report honest rather than flattering. Record whatever you use, because the WNS number is only meaningful alongside them.

> **Tip:** *Window → Language Templates → XDC* has the syntax for every constraint, so you never have to guess an option name.

---

## 4. Enable out-of-context synthesis

Your module has 2 × 64 data bits plus handshakes plus a 64-bit checksum — about 200 ports. The clg400 package has far fewer user I/O pins, so a normal run fails during placement with an I/O-count error. Out-of-context (OOC) synthesis skips I/O buffer insertion and treats the module as a block inside a larger design, which is exactly what it will be.

1. *Flow Navigator → **Settings*** (or *Tools → Settings*) → *Project Settings → **Synthesis***.
2. In the **More Options** box, type:
   ```
   -mode out_of_context
   ```
3. **OK**.

**Verify it took effect:** after synthesis, open the synthesised design and run *Reports → Report Utilization*. The **IO** row should show **0** used. If it shows a large number, OOC is not active.

> Alternative route: right-click the module in **Sources** → *Set as Out-of-Context for Synthesis*. This creates a separate OOC run. Use one method or the other, never both at once.

---

## 5. Run synthesis

1. Flow Navigator → **SYNTHESIS → Run Synthesis**.
2. *Launch Runs* dialog: *Number of jobs* = 4 (or however many cores you want to spare) → **OK**.
3. Watch the progress bar in the top-right. For this design it takes under a minute.
4. When *Synthesis Completed* appears, choose **Open Synthesized Design** → **OK**.

### 5.1 Check the messages
Open the **Messages** tab (bottom panel). Use the check-boxes to show Errors, Critical Warnings and Warnings.

| Message | Meaning | Action |
|---|---|---|
| 0 errors, 0 critical warnings | What you want | Continue |
| `[Synth 8-xxx] cannot find module` | A file isn't in the project, or its type is wrong | Check the Sources pane |
| *inferred latch for signal* | An `always_comb` path doesn't assign a signal on every branch | Fix it; a latch in this design is always a bug |
| *signal is read but never assigned* | Typo in a name (this is why `` `default_nettype none `` is there) | Fix the typo |
| *port width mismatch* | Connection widths differ | Check the instantiation |

### 5.2 Confirm block RAM inference
This is the main thing the test is checking.

- *Reports → **Report Utilization*** → **OK**. In the results panel, look at **Block RAM Tile**. For 1,024 × 65 bits you should see **2** (a RAMB36 holds 36 Kb; you need ≈ 66.6 Kb).
- If it shows 0, the memory became distributed LUT RAM or registers. The usual causes are an asynchronous read, a reset on the array, or a depth too small to be worth a BRAM.
- You can also search the synthesis log for the RAM inference report: *Reports → Report Synthesis → …*, or open `vivado/axis_smoke/axis_smoke.runs/synth_1/runme.log` and search for `RAM`. Vivado prints a table of inferred RAMs with their implementation (block vs distributed).

### 5.3 Confirm out-of-context worked
In the same utilisation report, the **IO** row should be **0 used**. If it shows roughly 200, OOC is not active — go back to §4.

### 5.4 Optional sanity check
*Flow Navigator → Open Synthesized Design → **Schematic***. You should see the memory block, the pointer counters and the XOR. If large parts are missing, something was optimised away because it never reaches an output.

---

## 6. Run implementation

1. Flow Navigator → **IMPLEMENTATION → Run Implementation** → **OK**.
2. On *Implementation Completed*, select **Open Implemented Design** → **OK**.

### 6.1 Read the timing result
*Reports → Timing → **Report Timing Summary*** → **OK**. In the report tree, click **Design Timing Summary**.

| Field | Meaning | Pass condition |
|---|---|---|
| **WNS** | Worst negative slack, setup. How much time to spare the slowest path has | **≥ 0.000 ns** |
| **TNS** | Total negative slack, the sum over all failing endpoints | 0.000 |
| **WHS** | Worst hold slack | ≥ 0.000 ns |
| **THS** | Total hold slack | 0.000 |
| Failing endpoints | Count of paths that miss | 0 |

Compute your effective maximum clock:

```
Fmax ≈ 1 / (clock_period − WNS)
```

With an 8 ns constraint and WNS = +2.5 ns, that is 1/5.5 ns ≈ 182 MHz. Quote it as "meets timing at 125 MHz; Fmax estimated at …", never as a measured frequency.

**If WNS is negative:** expand *Intra-Clock Paths → clk → Setup*, double-click the worst path, and read the *Path Properties*. Look at where the delay accumulates — logic levels, routing, or a long fan-out net. The fixes are pipelining, reducing logic between registers, or lowering the clock target. A lower clock, reported honestly, is a legitimate result.

### 6.2 Read area
*Reports → **Report Utilization***. Record: Slice LUTs, Slice Registers, Block RAM Tile, DSPs, each with its percentage. For this test design the numbers are tiny (roughly 100 LUTs, 100 FFs, 2 BRAM, 0 DSP); the point is that they are non-zero and that BRAM appeared.

### 6.3 Read power (vectorless for now)
*Reports → **Report Power*** → **OK**. Note two things:
- **Total On-Chip Power**, split into Dynamic and Device Static.
- The **confidence level**, which at this stage will be *Low*, because Vivado is guessing the switching activity.

Vectorless numbers are fine for a flow test. They are **not** acceptable for the paper — §8 shows the SAIF flow that replaces them.

### 6.4 The fast overview
*Window → **Design Runs***. Each run shows WNS, TNS, WHS, THS, Total Power and resource columns in one line. Right-click the column header to add columns (LUT, FF, BRAM). After any change, this is the quickest way to see what moved.

---

## 7. Save the evidence into the repository

Vivado writes reports automatically for each implementation run:

```
D:\QKD-Key-Distillation\vivado\axis_smoke\axis_smoke.runs\impl_1\
```

Typical files:

| File | Contents |
|---|---|
| `axis_smoke_utilization_placed.rpt` | Resource usage |
| `axis_smoke_timing_summary_routed.rpt` | Full timing summary |
| `axis_smoke_power_routed.rpt` | Power estimate |
| `axis_smoke_drc_routed.rpt` | Design rule checks |
| `axis_smoke_route_status.rpt` | Routing completion |

1. Create `D:\QKD-Key-Distillation\results\axis_smoke_xc7z020clg400-1\`.
2. **Copy** (do not move) the utilisation, timing-summary and power reports into it.
3. Create `result.yaml` next to them. Fill in your own numbers:

```yaml
# Week-1 toolflow proof (docs/15). Not an accelerator result.
commit: <git sha at the time of the run>
date: 2026-10-__
tools:
  vivado: "v2025.2 (64-bit), SW Build 6299465"
part: xc7z020clg400-1
clock_ns: 8.000          # 125 MHz target, REQ-IMP-02
design: axis_smoke (W=64, DEPTH=1024)
mode: out_of_context
how_run: "Vivado GUI, project-mode run impl_1"
results:
  wns_ns: ...
  whs_ns: ...
  failing_endpoints: 0
  luts: ...
  registers: ...
  bram36: ...
  dsp: 0
  power_total_w: ...
  power_type: vectorless     # becomes 'saif' from M5
notes: >
  Purpose: prove SystemVerilog elaboration, BRAM inference, timing closure
  and report generation on the target part.
```

That header is what makes a number quotable in the paper (REQ-REP-01). A report with no header is an orphan.

---

## 8. Simulation, and the SAIF power flow

### 8.1 What the testbench must do
To be worth running, the testbench has to:
1. Generate an 8 ns clock and hold reset for a few cycles.
2. Feed N words with `tlast` on the final one.
3. Apply **random back-pressure** on `m_axis_tready`, because the handshake bugs only appear when the downstream stalls.
4. Check that the words come out **in order and unchanged**, and that `tlast` lands on the last one.
5. Check the final `checksum` against the XOR computed in the testbench.
6. Print a clear PASS or FAIL line and call `$finish`.

The timing discipline that avoids race conditions: **drive stimulus on the falling edge, sample the DUT's outputs on the falling edge too**, since the DUT only changes on the rising edge. Everything is then stable when you look at it.

### 8.2 Reference testbench

```systemverilog
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

  // ---- driver ----------------------------------------------------------
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

  // ---- receiver with random back-pressure ------------------------------
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

  // ---- end of test ------------------------------------------------------
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
```

The final `initial` block is a **timeout**. Without one, a handshake bug hangs the simulation instead of failing it.

### 8.3 Add the testbench and run it
1. **Add Sources** → **Add or create simulation sources** → **Next** → **Create File** → *File type:* SystemVerilog · *Name:* `tb_axis_smoke.sv` · *Location:* `D:/QKD-Key-Distillation/tb` → **OK** → **Finish** → **Cancel** the Define Module dialog.
2. Type in the testbench and save.
3. In *Sources → **Simulation Sources** → sim_1*, confirm `tb_axis_smoke` is bold (the top). If not, right-click → **Set as Top**.
4. Flow Navigator → **SIMULATION → Run Simulation → Run Behavioral Simulation**.
5. In the simulation window, type `run all` in the Tcl console at the bottom, or press the **Run All** button.
6. Read the **Tcl Console**. You want `TEST PASSED`.

**Using the waveform:** signals from the top level appear automatically. To add internal DUT signals, select `dut` in the **Scope** pane, drag signals from **Objects** into the waveform, then press **Restart** and **Run All**. Useful ones here: `count`, `out_valid`, `do_wr`, `do_rd`.

### 8.4 Post-implementation timing simulation
This runs the routed netlist with real delays, and it catches bad constraints and X-propagation from uninitialised memory that behavioural simulation hides.

Flow Navigator → **SIMULATION → Run Simulation → Run Post-Implementation Timing Simulation**. The same testbench drives it. Expect it to be much slower, so keep N small.

> If signals come up as `X` and stay there, the usual cause is that memory contents are undefined until written. Make the testbench write before it reads, which the reference testbench already does.

### 8.5 Capture switching activity (SAIF)
*Tools → Settings → Project Settings → **Simulation** → **Simulation** tab*. The properties you need are the `xsim.simulate.saif*` ones:

| Property | Set it to |
|---|---|
| `xsim.simulate.saif_scope` | the instance to record, e.g. `tb_axis_smoke/dut` |
| `xsim.simulate.saif` | the output filename, e.g. `axis_smoke.saif` |
| `xsim.simulate.saif_all_signals` | tick it if you want every signal, not only ports |

Then re-run the post-implementation timing simulation. The `.saif` file lands in the simulation run directory (`vivado/axis_smoke/axis_smoke.sim/sim_1/impl/timing/xsim/`).

**The activity is only as representative as your stimulus.** For the real accelerator, drive frames at the QBER you want to characterise, not an idle or a worst-case pattern.

### 8.6 Power with real activity
1. **Open Implemented Design**.
2. *Reports → **Report Power***.
3. In the dialog, switch to the switching-activity settings and point the **SAIF file** field at the file from §8.5. (The exact tab label moves between versions; it is the section that mentions SAIF or switching activity.)
4. **OK**.
5. Record the total power, the dynamic/static split, **and** the confidence level, which should now be better than *Low*.

In the paper this is always "estimated from post-implementation simulation activity", never "measured" (REQ-REP-02, REQ-REP-03).

---

## 9. Pass criteria for the week-1 flow test

- [ ] Synthesis: 0 errors, 0 critical warnings
- [ ] Utilisation after synthesis: **Block RAM Tile ≥ 1**, **IO = 0**
- [ ] Implementation completes
- [ ] **WNS ≥ 0** and 0 failing endpoints at the 8 ns constraint
- [ ] Behavioural simulation prints **TEST PASSED**
- [ ] A power report exists (vectorless is fine at this stage)
- [ ] Reports plus `result.yaml` copied into `results/axis_smoke_xc7z020clg400-1/`

Send me the numbers — WNS, WHS, LUT, FF, BRAM, power — and I'll record them in the toolflow doc, the version-pin table and the weekly log.

---

## 10. Troubleshooting

| Symptom (as Vivado words it) | Cause | Fix |
|---|---|---|
| `[Place 30-640] Place Check : This design requires more … IO` | OOC not enabled | §4; verify IO = 0 in the utilisation report |
| `[Synth 8-439] module 'axis_smoke' not found` | File not added, or added as the wrong type | Sources pane → right-click → *Set File Type* |
| `[Synth 8-327] inferring latch for variable` | `always_comb` branch leaves a signal unassigned | Assign a default at the top of the block |
| `[Synth 8-6014] Unused sequential element … removed` | Logic doesn't reach any output | Make sure every result path ends at a port |
| Block RAM Tile = 0 | Asynchronous read, reset on the array, or a tiny depth | Register the read; remove the array reset; check the RAM table in `runme.log` |
| WNS negative by a small amount | Critical path slightly too long | Inspect the worst path; pipeline it, or state the achieved Fmax |
| Simulation hangs, never prints PASS | Handshake deadlock | The timeout block prints the word count; look at `count`, `out_valid`, `do_rd` in the waveform |
| Output words shifted by one, or one missing | The read-enable condition is wrong | Re-read §2.2: read only when `count != 0 && (!out_valid || m_tready)` |
| Everything `X` in post-implementation simulation | Memory read before written, or missing reset | Write before reading; check `rst_n` polarity and length |
| Reports look stale, run marked out of date | Sources changed after the run | Re-run synthesis, then implementation |

---

## 11. After you change the RTL

1. Save the file (**Ctrl+S**).
2. Vivado marks the runs out of date (orange triangle in Design Runs).
3. **Run Synthesis** again — it offers to reset the previous run; accept.
4. **Run Implementation**.
5. Re-run the behavioural simulation.
6. Copy the new reports into a **new** `results/` subfolder, or overwrite with an updated `result.yaml`. Never edit the numbers in an old header; each header describes one run.

---

## 12. Division of work

| Claude does | You do |
|---|---|
| Documentation, specifications, the learning guide | Everything inside Vivado: projects, RTL, constraints, runs, reports |
| Python reference models, analysis scripts, plots (Linux side) | Writing and editing RTL and testbenches |
| Explaining messages and reviewing numbers you paste in | Deciding and applying the fix in the tool |
| Recording your results in the docs and the log | Copying reports into `results/` and writing `result.yaml` |

---

## 13. Menu quick reference

| Task | Path |
|---|---|
| New project | *Quick Start → Create Project* |
| Target language | *Tools → Settings → Project Settings → General* |
| Add RTL / constraints / testbench | *Flow Navigator → Add Sources* |
| OOC mode | *Settings → Project Settings → Synthesis → More Options* |
| Run synthesis / implementation | *Flow Navigator → Run Synthesis / Run Implementation* |
| Utilisation, timing, power | *Reports →* (with the design open) |
| All runs at a glance | *Window → Design Runs* |
| Behavioural simulation | *Flow Navigator → Run Simulation → Run Behavioral Simulation* |
| Post-implementation timing simulation | *…→ Run Post-Implementation Timing Simulation* |
| Simulation and SAIF settings | *Tools → Settings → Project Settings → Simulation* |
| Constraint syntax help | *Window → Language Templates → XDC* |

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

**All Vivado work is done by hand in the GUI** — see [15-vivado-gui-guide](15-vivado-gui-guide.md) for the step-by-step procedure. In outline: create an RTL project on `xc7z020clg400-1`, add a small AXI4-Stream core and a 125 MHz constraint, enable **out-of-context** synthesis (the core has more ports than the clg400 package has user I/O pins), then run synthesis and implementation.

**Pass criteria:** 0 errors, WNS ≥ 0, block RAM inferred, reports copied into `results/` with a `result.yaml` header.

## 3. Power with switching activity (L6)
1. Run post-implementation timing simulation on representative frames, with SAIF capture enabled.
2. Open the implemented design and run Report Power with that SAIF file.
3. Record the number **and** the confidence level Vivado reports (REQ-REP-02).

Full menu-level steps: [15 §8](15-vivado-gui-guide.md#8-simulation-and-the-saif-power-flow).

## 4. Version pins (fill in on install)

| Tool | Version | Date installed |
|---|---|---|
| Vivado | **v2025.2 (64-bit)**, SW Build 6299465 (14 Nov 2025), installed at D:/AMDDesignTools/2025.2/Vivado | 2026-10-11 |
| Verilator | **5.052** (built from source, tag `v5.052`, installed in `/usr/local/bin`) | 2026-10-11 |
| Icarus Verilog | 12.0 (stable) | 2026-10-11 |
| Python | 3.12.3 (Ubuntu 24.04) | 2026-10-11 |
| uv | 0.13.0 (installed via pipx) | 2026-10-11 |
| cocotb | 2.1.0 | 2026-10-11 |
| NumPy / Numba | 2.5.4 / 0.68.0 (SciPy 1.18.1, Matplotlib 3.11.2) | 2026-10-11 |

> **Verilator is built from source, not from apt.** cocotb 2.x requires Verilator >= 5.036, and Ubuntu 24.04 ships 5.020. The apt package was removed (`apt-get remove verilator`) so only the source build is on the system. Verify with `verilator --version` before trusting any simulation result.
>
> Build recipe used (Ubuntu 24.04, as root):
>
> ```bash
> apt-get install -y git help2man perl make autoconf g++ flex bison ccache libgoogle-perftools-dev numactl perl-doc libfl2 libfl-dev zlib1g-dev
> git clone https://github.com/verilator/verilator.git /opt/src/verilator
> cd /opt/src/verilator && git checkout v5.052
> autoconf && ./configure && make -j$(nproc) && make install
> ```
>
> Toolchain smoke test (cocotb 2.1.0 driving a `always_ff` flip-flop through Verilator 5.052): **passed**, 2026-10-11.

### 4.1 Python environment (uv)
The repository is a uv project: [`pyproject.toml`](../pyproject.toml) declares the dependencies and `uv.lock` pins the exact resolved versions (commit the lock file).

```bash
cd /mnt/d/QKD-Key-Distillation
uv sync --extra sim     # creates .venv with models + cocotb
uv run python -c "import numpy, numba; print(numba.__version__)"
uv run pytest           # once tests exist
```

The `sim` extra holds the RTL-verification packages (cocotb, pytest); plain `uv sync` installs only what the models need.

## 5. Reproducing a result
Each run gets its own folder under `results/`, holding the Vivado reports, a machine-readable `result.yaml` header and a `README.md` evaluation report (timing, utilisation, power breakdown, thermal and derived metrics). See [results/axis_smoke_xc7z020clg400-1](../results/axis_smoke_xc7z020clg400-1/README.md) as the pattern.

Every `result.yaml` starts with a header:

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

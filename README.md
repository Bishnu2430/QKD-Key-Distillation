# QKD Key Distillation on FPGA

**A rate-adaptive, low-power FPGA accelerator for discrete-variable QKD key distillation on a Zynq-7020**

This project designs, verifies and evaluates FPGA hardware for the classical post-processing stages of a discrete-variable quantum key distribution (DV-QKD) system:

- **Information reconciliation**: a rate-adaptive QC-LDPC syndrome decoder (layered normalized min-sum)
- **Error verification**: a universal-hash tag compare
- **Privacy amplification**: Toeplitz hashing

The target device is the AMD Zynq-7020 (`xc7z020clg400-1`). No physical board or optics are used. Results come from bit-exact simulation plus Vivado post-implementation (place-and-route) timing and power reports. See [the charter](docs/01-charter.md) for the scope and the reasoning behind this validation approach.

## Status

| Area | State |
|---|---|
| Foundation docs (charter → algorithm spec) | Draft v0.1 |
| Hardware docs | Outlines |
| Python reference model | Not started |
| RTL | Not started |

## Documentation map

**New to the topic? Start with the [learning guide](docs/00-learning-guide.md).** It explains every concept used in this project, from entropy and LDPC codes to FPGA timing.

| # | Document | Purpose | State |
|---|---|---|---|
| 00 | [Learning guide](docs/00-learning-guide.md) | All theory, maths and engineering concepts, with worked examples | Draft |
| 01 | [Project charter](docs/01-charter.md) | Problem, research question, contributions, scope, success criteria | Draft |
| 02 | [Related work](docs/02-related-work.md) + [matrix](docs/related-work.csv) | Prior art and gap statement | Draft |
| 03 | [Requirements](docs/03-requirements.md) | Numbered, testable targets (REQ-IDs) | Draft |
| 04 | [System model](docs/04-system-model.md) | Protocol, channel and security assumptions; notation | Draft |
| 05 | [Algorithm spec](docs/05-algorithm-spec.md) | **Bit-exact golden reference** for model and RTL | Draft |
| 06 | [LDPC code design](docs/06-ldpc-code-design.md) | Code construction and rate adaptation (C1) | Outline |
| 07 | [Hardware architecture](docs/07-hw-architecture.md) | PS/PL split, dataflow, budgets | Outline |
| 08 | [Interfaces and register map](docs/08-interfaces-regmap.md) | AXI4-Stream formats, AXI4-Lite registers | Outline |
| 09 | [Block micro-architecture](docs/blocks/) | Decoder, verification hash, privacy amplification | Outline |
| 10 | [Verification plan](docs/10-verification-plan.md) | L1–L6 ladder, tests mapped to REQ-IDs | Outline |
| 11 | [Evaluation plan](docs/11-evaluation-plan.md) | Experiments E1–E7, metrics, reporting rules | Outline |
| 12 | [Toolflow and reproducibility](docs/12-toolflow.md) | Environment setup, pinned versions, how to reproduce | Draft |
| 13 | [RTL coding guidelines](docs/13-rtl-coding-guidelines.md) | SystemVerilog conventions | Outline |
| 14 | [Problem, solution and rationale](docs/14-rationale.md) | **Why** — problem statement, our solution, the reason behind every choice, methodology | Draft |
| 15 | [Vivado GUI guide](docs/15-vivado-gui-guide.md) | Step-by-step procedure for every Vivado task, done by hand in the GUI | Draft |
| — | [Decision records](docs/decisions/) | Why each major choice was made | Ongoing |
| — | [Progress log](docs/log/) | Weekly notes | Ongoing |

## Repository layout

```
docs/      Specifications, plans, decisions, log
model/     Python reference models (floating-point L1, bit-true L2)
rtl/       SystemVerilog sources
tb/        cocotb testbenches
scripts/   Vivado Tcl, sweeps, plotting
results/   Summarised results (each tied to a commit and tool version)
paper/     LaTeX drafts
```

## Conventions

- Requirements are referenced as `REQ-<AREA>-<nn>` (for example `REQ-PERF-03`). Tests and results cite the REQ-IDs they cover.
- Decisions are recorded as `ADR-<nnn>` in `docs/decisions/`.
- All documents are Markdown with GitHub-flavoured maths (`$...$`) and Mermaid diagrams.

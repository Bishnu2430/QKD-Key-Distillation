# ADR-006: Target device xc7z020clg400-1

| Status | Accepted |
|---|---|
| Date | 2026-09-21 |
| Related | REQ-IMP-01, C2–C4 |

## Context
The project claims low cost and low power, and needs a PS for per-block control and DDR buffering.

## Options considered
1. **Zynq-7020** (53,200 LUT; 5,040 Kb BRAM; 220 DSP; ARM Cortex-A9; on PYNQ-Z2 and Zybo Z7-20): low-cost SoC; results can later run on a borrowed board.
2. **Artix-7 35T / 100T**: cheaper, but no hard CPU. 100T kept as a second data point.
3. **Kria K26 / UltraScale+**: much more memory, but higher cost; weakens the "low-cost" claim.

## Decision
Primary target xc7z020clg400-1 (speed grade -1). Secondary data point xc7a100t.

## Consequences
BRAM limits the LDPC frame to about 2^16–2^17 bits; large PA blocks need PS DDR. This trade-off is contribution C4.

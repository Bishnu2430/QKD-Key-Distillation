# ADR-002: Toolchain and pinned Vivado version

| Status | Accepted |
|---|---|
| Date | 2026-09-21 |
| Related | REQ-IMP-01, REQ-REP-01, [12-toolflow](../12-toolflow.md) |

## Context
From Vivado 2026.1, AMD moved to tiered licensing. The free BASIC tier still covers 7-series and Zynq-7000 devices, but needs a free licence file renewed every 12 months, and AMD describes its simulation and debug features as limited, without full detail yet. Results must be reproducible for the whole project and after publication.

## Options considered
1. **Last 2025.x release** (before the change): no licence file for 7-series; stable for the project's lifetime.
2. **2026.1 with the free BASIC licence**: newest tools; annual renewal; unclear feature limits.

## Decision
Option 1. Pin one 2025.x version for all results. Run heavy simulation in Verilator/cocotb, independent of Vivado's simulator limits.

## Consequences
Record the exact version in [12 §4](../12-toolflow.md#4-version-pins-fill-in-on-install) and in every result header. Revisit only if a needed feature or bug fix requires 2026.x.

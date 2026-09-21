# ADR-003: LDPC syndrome reconciliation over Cascade and polar codes

| Status | Accepted |
|---|---|
| Date | 2026-09-21 |
| Related | REQ-FUN-01, C1, C2 |

## Context
Information reconciliation must reach f close to 1 at tens of Mbps on a low-cost FPGA.

## Options considered
1. **Cascade**: good efficiency, but many interactive rounds; sequential and latency-bound. Poor hardware fit.
2. **LDPC (one-way syndrome)**: f ≈ 1.05–1.15 with long codes; highly parallel; proven in FPGA systems (Constantin 2017); rate-adaptive by puncturing and shortening.
3. **Polar (SC/SCL)**: f ≈ 1.11 at N = 2^20 (Liao 2025), but successive decoding is sequential and needs large memory (DDR in Liao 2025).

## Decision
LDPC with layered normalized min-sum. Cascade stays as a software baseline; polar results are cited for comparison.

## Consequences
Code design (C1) becomes a core contribution. The decoder must handle rate masks and syndrome-aware checks.

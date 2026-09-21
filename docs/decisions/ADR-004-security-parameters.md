# ADR-004: Security parameters

| Status | Proposed (confirm with guide) |
|---|---|
| Date | 2026-09-21 |
| Related | REQ-SEC-02, [04 §5](../04-system-model.md#5-finite-key-secret-key-length) |

## Context
The finite-key length depends on ε_sec and ε_cor. Values must be stated and fixed for all experiments.

## Decision (proposed)
ε_sec = 10^-9, ε_cor = 10^-12 per block. These are orders of magnitude typical of published finite-key analyses. Once the reference paper is chosen, confirm or align them with its values.

## Consequences
Constant penalties ≈ 205.7 bits (6·log2(21/ε_sec)) and ≈ 40.9 bits (log2(2/ε_cor)). A 64-bit per-frame tag gives ε_cor ≤ K·2^-64 for K frames.

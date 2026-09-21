# Block: Verification Hash

| Version | 0.0 (outline) · Milestone M6 · Implements [05 §4](../05-algorithm-spec.md#4-error-verification) |
|---|---|

## 1. Function
Compute a 64-bit Toeplitz tag of $\hat{x}_{key}$ with a public per-frame seed. Compare it with Alice's tag and flag keep or drop.

## 2. Design options
- **(a)** Reuse the PA datapath with $\ell = 64$ (contribution C3 sharing).
- **(b)** A dedicated polynomial hash over GF(2⁶⁴): one carry-less multiplier; seed of only 64 bits.
Record the choice in an ADR with area, throughput and collision-bound comparison.

## 3. Ports, micro-architecture, timing
To fill in M6.

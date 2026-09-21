# Block: Toeplitz Privacy Amplification

| Version | 0.0 (outline) · Milestone M6 · Implements [05 §5](../05-algorithm-spec.md#5-privacy-amplification) |
|---|---|

## 1. Function
$k = T_\tau X$: compress an $N$-bit block to $\ell$ bits with a Toeplitz matrix defined by a public seed $\tau$ of $N+\ell-1$ bits.

## 2. Method options (analysed for contribution C3)

| Method | Cost | Fits Zynq-7020 at | Notes |
|---|---|---|---|
| Direct, output-chunked (process $w$ input bits × $B$ output bits per cycle) | $N\ell/(wB)$ cycles | $N \lesssim 2^{17}$ at tens of Mbps | Simple; see the learning guide §17 |
| FFT/NTT polynomial multiplication | ~$N \log N$ | $N \ge 10^6$ | Uses DSP blocks; complex |
| Hybrid (PS NTT + PL XOR fold) | — | — | HW/SW co-design option |

## 3. Block storage
BRAM for $N \le$ (TBC); PS DDR streaming via AXI DMA above that.

## 4. Ports, micro-architecture, timing
To fill in M6.

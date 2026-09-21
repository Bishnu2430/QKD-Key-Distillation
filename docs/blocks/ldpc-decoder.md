# Block: LDPC Syndrome Decoder

| Version | 0.0 (outline) · Milestone M4 · Implements [05 §3.3–3.6](../05-algorithm-spec.md#3-reconciliation) |
|---|---|

## 1. Function
Layered normalized min-sum decoding of one frame per [05 §3.6](../05-algorithm-spec.md#36-decoding-layered-normalized-min-sum-l2-bit-true), with syndrome-aware check update, rate masks and early termination.

## 2. Ports (to fill)

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk`, `rst_n` | in | 1 | Clock, synchronous active-low reset |
| `s_axis_*` | in | 64 | Frame input |
| `m_axis_*` | out | 64 | Decoded key output |
| `cfg_*` | in | — | `i_max`, `mask_id`, `A` |
| `stat_*` | out | — | `ok`, `iters`, `busy` |

## 3. Micro-architecture (to design)
- $Z$-parallel layer processing (working assumption $P = Z = 128$).
- **APP memory:** banking for 1,024-bit/cycle read and write; read-modify-write hazards between consecutive layers.
- **Cyclic shifter:** barrel shifter of $Z$ × `W_APP` bits (7 stages for $Z = 128$).
- **Check-node unit (CNU):** serial min1/min2/idx/sign tracking; compressed message store.
- **Early-termination unit:** syndrome check of hard decisions at the iteration boundary.
- **Mask unit:** LLR initialisation for $\mathcal{P}$ and $\mathcal{S}$.

## 4. Pipeline and timing diagram
To add: WaveDrom diagram of one layer; pipeline depth; stall conditions.

## 5. Resource estimate vs actual
Table: LUT/FF/BRAM/DSP estimate from the learning guide §16 versus post-implementation numbers.

## 6. Verification hooks
Debug outputs for the L3 bit-exact compare: per-layer APP dump (simulation only).

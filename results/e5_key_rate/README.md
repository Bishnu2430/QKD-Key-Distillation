# E5 — secret key rate against distance

| Field | Value |
|---|---|
| Question | What do this project's hardware numbers — efficiency f, frame error rate, block size — do to the key rate of a real link? |
| Model | [model/keyrate.py](../../model/keyrate.py): decoy-state GLLP (asymptotic) and a 1-decoy finite-key estimate |
| Channel | **Illustrative** parameters: 0.2 dB/km, detector efficiency 0.2, dark counts 10⁻⁶/gate, misalignment 1%, 1 GHz repetition, symmetric sifting |
| Data | [e5.csv](e5.csv), [meta.json](meta.json), [e5.png](e5.png) |

> **Two caveats, both important.** The channel parameters are illustrative, not a published system — choosing and citing a reference system is still an open M1 item. And the finite-key curves are **provisional**: the decoy estimators are transcribed verbatim from arXiv:2405.16578v3, but its ε bookkeeping (the γ, α₂, ζ′ and Δ_ci terms of Eq. 121) is not, so those curves carry placeholder constants and must not be quoted.

## 1. Asymptotic rate against distance (secret bits/s, 1% frame loss)

| Distance | f = 1.0 | f = 1.15 | f = 1.4 | f = 1.6 |
|---|---|---|---|---|
| 0 km | 2.68 × 10⁷ | 2.59 × 10⁷ | 2.44 × 10⁷ | 2.33 × 10⁷ |
| 50 km | 2.63 × 10⁶ | 2.54 × 10⁶ | 2.39 × 10⁶ | 2.27 × 10⁶ |
| 100 km | 2.61 × 10⁵ | 2.51 × 10⁵ | 2.36 × 10⁵ | 2.24 × 10⁵ |
| 150 km | 2.43 × 10⁴ | 2.31 × 10⁴ | 2.12 × 10⁴ | 1.97 × 10⁴ |
| 175 km | 6.43 × 10³ | 5.91 × 10³ | 5.06 × 10³ | 4.40 × 10³ |
| **200 km** | **965** | **679** | **215** | **0** |

## 2. The finding that matters for this project

**Reconciliation efficiency costs little at short range and decides the maximum range.**

Keeping f = 1.15 instead of a perfect f = 1.0 costs:

| Distance | key retained |
|---|---|
| 0–100 km | about 96% |
| 150 km | 95% |
| 175 km | 92% |
| 200 km | **70%** |

And at 200 km, f = 1.6 produces **no key at all** while f = 1.0 still yields about 1 kbit/s. The reason is structural: the leakage term is subtracted from a secret fraction that is itself shrinking with distance, so a fixed relative inefficiency eats a growing share of what remains until it eats all of it.

This is the system-level argument for contribution C1. An improvement from f ≈ 1.6 to f ≈ 1.2 is nearly invisible in a lab link at 25 km and is the difference between a working and a dead link at 200 km.

## 3. Finite block size (provisional)

| Block | 0 km | 50 km | 100 km | 150 km | 200 km |
|---|---|---|---|---|---|
| 10¹⁰ pulses (10 s at 1 GHz) | 1.66 × 10⁷ | 1.58 × 10⁶ | 1.46 × 10⁵ | 1.09 × 10⁴ | **0** |
| 10¹² pulses (1,000 s) | 1.68 × 10⁷ | 1.64 × 10⁶ | 1.62 × 10⁵ | 1.54 × 10⁴ | 1.35 × 10³ |

The same shape as the efficiency effect, from a different cause: statistical margins scale as 1/√(block), so a short block is penalised everywhere and fatally at long range, where there is little key left to pay from. At 200 km the 10-second block yields nothing while the 1,000-second block still works.

**This is the other half of contribution C4.** Hardware wants small blocks — privacy amplification costs N·ℓ operations, and memory is finite. Security wants large ones. The project's job is to find where on that curve a Zynq-7020 should sit, and these curves are the "security wants large" side of the trade-off, measured on the same footing as the hardware side.

## 4. What is still missing

1. A **cited reference system**: swap the illustrative channel parameters for a published one (M1 item in [04 §3](../../docs/04-system-model.md#3-physical-link-model-used-for-key-rate-experiments-e5-and-e6)).
2. The **ε bookkeeping** of Eq. (121) of arXiv:2405.16578v3, which turns the provisional finite-key curves into quotable ones.
3. Intensity optimisation for the finite-key case: the asymptotic curves optimise μ per distance, the finite-key ones use a fixed 1-decoy pair (0.5, 0.1).

## Reproduce

```bash
uv run python scripts/sweep_e5.py
```

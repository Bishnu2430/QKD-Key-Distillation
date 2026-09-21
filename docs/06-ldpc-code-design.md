# 06 — LDPC Code Design (Contribution C1)

| Version | 0.0 (outline), 21 Sep 2026 |
|---|---|
| Owner milestone | M3 |
| Implements | [05 §3.1, §3.3](05-algorithm-spec.md#3-reconciliation) |

> **Outline.** Section headings and the decisions each section must record are fixed. Content arrives in M3.

## 1. Design targets (from [03](03-requirements.md))
- $n = 65{,}536$; QBER 1–10%; $f \le 1.15$ (stretch 1.10) at FER ≤ 10⁻² over $Q \in [2\%, 8\%]$.
- Hardware constraints: single-circulant base entries ([05 §3.1](05-algorithm-spec.md#31-code-representation-qc-ldpc)); lifting $Z$ matches decoder parallelism (working assumption $Z = 128$, $n_b = 512$).

## 2. Required rate range
Table of $Q$ → required rate $R = 1 - f\,h(Q)$ (see the [learning guide §9](00-learning-guide.md#9-ldpc-codes-in-depth)). The rate spans about 0.48–0.91, which sets the mother-code rate $R_0$ and the puncture/shorten ranges.

## 3. Baseline codes (for comparison only)
- 5G NR BG1/BG2 at the largest lifting size.
- IEEE 802.11n codes, for early RTL bring-up.

## 4. Degree distribution
- Density evolution for the BSC: variable/check degree distributions $\lambda(x), \rho(x)$ and decoding thresholds.
- Record the threshold $Q^*$ versus rate, and compare with the Shannon limit $h^{-1}(1-R)$.

## 5. Base-matrix construction
- Protograph choice, PEG (or ACE/PEG) lifting, girth target (≥ 6, aim for 8), circulant shift optimisation.
- Record: $m_b$, $n_b$, $Z$, number of edges $E$, average degrees, girth histogram.

## 6. Rate adaptation masks
For each mask id: design QBER $Q_d$, sets $\mathcal{P}$ and $\mathcal{S}$, sizes $p$ and $s$, effective $R$, **rank check of the punctured columns** (for [05 §3.5](05-algorithm-spec.md#35-leakage-accounting)), and resulting $\lambda_{frame}$.

| mask_id | $Q_d$ | $p$ | $s$ | $R$ | rank OK? | $\lambda_{frame}$ |
|---|---|---|---|---|---|---|
| … | | | | | | |

## 7. Results (from L1/L2, experiment E1)
FER and $f$ against $Q$ for each mask; comparison with the baselines of §3.

## 8. Decisions to record as ADRs
Mother rate $R_0$ · lifting size $Z$ · layer schedule · mask set · final quantisation (linked to E2).

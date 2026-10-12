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

## 2a. Measured constraints from the L1 model (M2, results/c1_rate_adaptation)

Before designing anything, the baseline random QC-LDPC code was swept with
puncture/shorten masks across QBER 1-6%. The findings constrain this design:

| Finding | Constraint it imposes |
|---|---|
| Puncturing works up to about **10% of positions**; 15% is marginal; 20% fails outright | Cap puncturing at 10%, and cover the high-rate end another way |
| One R0 = 0.672 mother code could not reach the 1% QBER point at all | **Use two mother codes**: R0 about 0.85-0.88 for Q = 1-3%, R0 about 0.60-0.65 for Q = 4-10% |
| Concentrating degree on punctured columns helped at a 10% budget (FER 0.96 -> 0.24 at 3%) but failed beyond it | Design a **puncturable subset that is larger than the punctured set**, so spares stay unpunctured |
| Achieved f was 1.38-1.87 against the 1.15 target | The gap must come from degree-distribution optimisation (density evolution), PEG construction and the longer n = 65,536 |
| Heavy-puncture candidates produced f < 1 under the `m - p` accounting | **Check the rank of the punctured columns** (spec section 3.5) for every mask, and fall back to the conservative `m` when it fails |


## 2b. Efficiency is an outcome, not an input (M3 first pass)

The first M3 attempt (results/m3_code_design) built masks to hit f = 1.15 at
each QBER and **every operating point failed to decode**. Asking for f = 1.15
at QBER Q fixes the effective rate at R = 1 - 1.15 h(Q); for these ensembles
the decoding threshold at that rate is *below* Q, so the decoder cannot work
there no matter how the mask is built.

The design loop therefore runs the other way:

1. Compute the density-evolution threshold as a function of rate for the chosen
   degree profile.
2. For each QBER, take the highest rate whose threshold still exceeds Q with a
   finite-length margin.
3. The achievable efficiency follows as f = (1 - R) / h(Q).

The best f any ensemble can reach is set by the gap between its threshold and
the Shannon limit. For the profile {3: 0.75, 6: 0.125, 8: 0.125} at R0 = 0.619
the threshold is 5.74% against a Shannon limit of 7.38%, which caps f at about
1.20 **at threshold** - and real operation needs margin below threshold, so
f = 1.25-1.35 is the realistic target for this ensemble at n = 65,536.

That is above the REQ-PERF-01 target of f <= 1.15, so one of three things has
to give: a better degree profile, a longer code, or the requirement.


## 2c. The design rule (M3, from results/m3_code_design_v3)

    A mother code sits at the TOP of the rate range it serves.
    Lower rates are reached by SHORTENING, which measurement shows is safe.
    PUNCTURING is used only within the 10% budget, to nudge above R0.

Three mother codes at n = 65,536 (base 512 columns, Z = 128), profile
{3: 0.75, 6: 0.125, 8: 0.125}:

| Code | R0 | base | serves | measured FER |
|---|---|---|---|---|
| v3_mother_0_r850 | 0.850 | 77 x 512 | Q = 1-2% | 0.00 |
| v3_mother_1_r700 | 0.700 | 154 x 512 | Q = 3-6% | 0.00 |
| v3_mother_2_r400 | 0.400 | 307 x 512 | Q = 8% | 0.00 |

Every punctured column set passes the GF(2) rank check, so `leak = m - p`
is licensed rather than assumed.

**Efficiency reached: f = 1.29-1.56 (margin 1.05) against a target of 1.15.**
The ensemble's threshold gap caps f at about 1.22 before any finite-length
margin, so closing the gap needs a numerically optimised degree distribution -
this pass searched only 12 hand-written profiles. That optimisation is the
next task for this document.


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

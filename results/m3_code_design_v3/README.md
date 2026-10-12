# M3 — code design (contribution C1): three passes and what each taught

| Field | Value |
|---|---|
| Goal | Mother codes plus rate masks covering QBER 1–8% at n = 65,536, with honest leakage accounting |
| Decoder | Layered normalized min-sum, α = 0.75, bit-true L2 model |
| Degree profile | {3: 0.75, 6: 0.125, 8: 0.125} (node perspective), average column degree 4.0 |
| Codes | `codes/v3_mother_*.npz`, base 512 columns, Z = 128 |
| Data | [design.json](design.json), plus [v1](../m3_code_design/), [v2](../m3_code_design_v2/), margin sweeps [1.10](../m3_margin_1.10/), [1.05](../m3_margin_1.05/) |
| Undetected errors | **0** in every run |

## 1. The three passes

| Pass | Rule used | Outcome |
|---|---|---|
| **v1** | Build each mask to hit a target efficiency f = 1.15 | **Every point failed** (FER ≈ 1.0) |
| **v2** | Drive the rate from the density-evolution threshold | High-rate code worked (FER 0 at 1–4%); low-rate code failed at 5–6% |
| **v3** | Mother code at the **top** of its range; shorten downward; puncture only within 10% | **Every point decodes, FER 0.00** |

**v1's lesson: efficiency is an outcome, not an input.** Asking for f = 1.15 at QBER Q fixes the rate at R = 1 − 1.15·h(Q), and for this ensemble the threshold at that rate lies *below* Q. No mask can rescue a rate the code cannot decode.

**v2's lesson: a mother code must sit at the top of the range it serves.** v2 put the low-rate mother at R₀ = 0.40, the bottom of its range, so every other point had to be reached by puncturing 24–30% of positions — far past the ~10% budget measured in [C1](../c1_rate_adaptation/README.md). Those points failed exactly as that budget predicts. Shortening has no comparable limit, so the range must be walked downward.

## 2. The threshold curve — the number that governs everything

Density evolution for this profile, under the decoder we actually use:

| Rate | 0.475 | 0.550 | 0.625 | 0.700 | 0.775 | 0.850 | 0.925 |
|---|---|---|---|---|---|---|---|
| Threshold | 8.78% | 7.07% | 5.49% | 4.04% | 2.73% | 1.58% | 0.59% |
| Shannon limit | 11.85% | 9.41% | 7.24% | 5.32% | 3.63% | 2.15% | 0.91% |
| **f at threshold** | 1.223 | 1.221 | 1.223 | 1.229 | 1.245 | 1.278 | 1.432 |

**f at threshold is ≈ 1.22, almost independent of rate.** That is this ensemble's ceiling: no mask, margin or iteration count can beat it, because it is the gap between the ensemble's threshold and the Shannon limit. Operating *below* threshold (which finite codes must) costs more on top.

## 3. The final design (margin 1.25)

Three mother codes, each at the top of its range:

| Code | R₀ | base | serves |
|---|---|---|---|
| `v3_mother_0_r850` | 0.850 | 77 × 512 | Q = 1–2% |
| `v3_mother_1_r700` | 0.700 | 154 × 512 | Q = 3–6% |
| `v3_mother_2_r400` | 0.400 | 307 × 512 | Q = 8% |

| QBER | code R₀ | mask rate | punctured | shortened | leak (bits) | rank OK | f | FER | iterations |
|---|---|---|---|---|---|---|---|---|---|
| 1% | 0.850 | 0.850 | 0 | 0 | 9,920 | ✓ | 1.874 | 0.00 | 5.0 |
| 2% | 0.850 | 0.775 | 0 | 21,760 | 9,920 | ✓ | 1.602 | 0.00 | 6.4 |
| 3% | 0.700 | 0.701 | 128 | 0 | 19,648 | ✓ | 1.545 | 0.00 | 6.5 |
| 4% | 0.700 | 0.625 | 0 | 12,928 | 19,776 | ✓ | 1.551 | 0.00 | 5.9 |
| 5% | 0.700 | 0.575 | 0 | 19,200 | 19,776 | ✓ | 1.490 | 0.00 | 6.6 |
| 6% | 0.700 | 0.525 | 0 | 24,064 | 19,776 | ✓ | 1.456 | 0.00 | 6.6 |
| 8% | 0.400 | 0.400 | 0 | 0 | 39,360 | ✓ | 1.493 | 0.00 | 5.9 |

Every punctured column set passed the GF(2) **rank check**, so the `leak = m − p` accounting of [spec §3.5](../../docs/05-algorithm-spec.md#35-leakage-accounting) is licensed rather than assumed.

## 4. The margin trade-off

Decoding at 5–7 iterations means the operating points sit far below threshold. Tightening the margin buys efficiency and costs iterations:

| Margin | f range | average iterations | FER |
|---|---|---|---|
| 1.25 | 1.46 – 1.87 | 5 – 7 | 0.00 everywhere |
| 1.10 | 1.35 – 1.56 | 8 – 11 | 0.00 everywhere |
| **1.05** | **1.29 – 1.56** | 11 – 20 | 0.00, except 0.07 at Q = 3% |

Since decoder throughput is inversely proportional to the iteration count, this *is* the E3 trade-off, measured: going from margin 1.25 to 1.05 buys roughly 0.17 of efficiency and costs about 2× in throughput. The choice belongs to the C4 optimisation, not to the code designer alone.

## 5. Where this leaves REQ-PERF-01

The requirement asks for **f ≤ 1.15** over Q = 2–8%. The measured floor here is **f ≈ 1.30**. The gap decomposes cleanly:

| Contribution | Size |
|---|---|
| Ensemble's threshold gap (f at threshold) | ≈ 1.22 |
| Finite-length margin needed to reach FER ≤ 10⁻² | ≈ +0.08 at margin 1.05 |

So the requirement is not reachable by tuning masks or margins. Three levers remain, in order of expected value:

1. **A properly optimised degree distribution.** This pass searched 12 hand-written profiles. Real LDPC design optimises λ(x) and ρ(x) numerically against the density-evolution threshold; published irregular ensembles reach much closer to capacity than f = 1.22. This is the biggest single lever and the obvious next task.
2. **Raise the rate ceiling for the 1% point.** Its f = 1.87 is an artefact of the rate grid stopping at 0.925; the 1% point wants a rate near 0.95.
3. **Accept and re-state the requirement.** If the optimised ensemble lands at f ≈ 1.2, REQ-PERF-01 should say so, with the measurement behind it. A measured 1.2 beats an aspirational 1.15.

## 6. What is solid

- Three mother codes that **decode every operating point from 1% to 8% QBER** at n = 65,536, with zero undetected errors.
- A design rule derived from measurement, not taste: *mother code at the top of its range, shorten downward, puncture only inside the 10% budget*.
- Leakage accounting backed by an actual rank check.
- A quantified efficiency-against-iterations trade-off for the C4 study.

## Reproduce

```bash
uv run python scripts/design_codes.py                      # v1, the failed first rule
uv run python scripts/design_codes2.py --margin 1.25       # v2, threshold-driven
uv run python scripts/design_codes3.py --margin 1.25       # v3, final rule
uv run python scripts/design_codes3.py --margin 1.05 --out results/m3_margin_1.05
```

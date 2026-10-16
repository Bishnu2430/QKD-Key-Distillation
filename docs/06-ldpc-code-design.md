# 06 — LDPC Code Design (Contribution C1)

| Version | 1.0, 16 Oct 2026 |
|---|---|
| Status | Codes built and validated; efficiency target not met (§7) |
| Codes | `codes/v3_mother_{0,1,2}_*.npz`, generated into `rtl/gen/` |
| Evidence | [results/m3_code_design_v3](../results/m3_code_design_v3/README.md), [results/c1_rate_adaptation](../results/c1_rate_adaptation/README.md) |
| Implements | [05 §3.1, §3.3](05-algorithm-spec.md#3-reconciliation) |

---

## 1. Targets

| Quantity | Target | Source |
|---|---|---|
| Frame length | n = 65,536 | REQ-FUN-09, BRAM budget ([07](07-hw-architecture.md)) |
| QBER range | 1–10% | REQ-FUN-02 |
| Efficiency | f ≤ 1.15 at FER ≤ 10⁻² over 2–8% | REQ-PERF-01 |
| Structure | One circulant per base entry, lifting Z matched to decoder parallelism (Z = 128, n_b = 512) | [05 §3.1](05-algorithm-spec.md#31-code-representation-qc-ldpc) |

The required code rate spans **0.48 to 0.91** across the QBER range, which is what forces rate adaptation.

## 2. The two rules that came out of measurement

**Rule 1 — puncture at most 10% of positions.** Measured on the baseline code ([C1](../results/c1_rate_adaptation/README.md)):

| Puncture fraction | Outcome |
|---|---|
| ≤ 10% | decodes reliably |
| 15% | marginal, FER 0.48–0.68 |
| ≥ 20% | fails completely |

A punctured variable arrives with zero channel information and must be rebuilt from its neighbours; past a tenth of the positions this construction cannot. Concentrating degree on the punctured columns helps *inside* that budget (FER 0.96 → 0.24 at 3%) and backfires beyond it, so the **puncturable subset must be larger than the punctured set**.

**Rule 2 — a mother code sits at the top of the range it serves.** Lower rates are reached by shortening, which measurement shows is safe to σ ≈ 0.4; puncturing is used only to nudge above R₀, inside the budget. Design pass v2 placed a mother code at the *bottom* of its range and every other point needed 24–30% puncturing; all of them failed.

## 3. Efficiency is an outcome, not an input

Design pass v1 built masks to hit f = 1.15 at each QBER and **every point failed**. Asking for f = 1.15 at QBER Q fixes the rate at R = 1 − 1.15·h(Q), and the decoding threshold at that rate lies below Q. The loop therefore runs the other way:

1. Compute the density-evolution threshold against rate for the degree profile.
2. For each QBER take the **highest rate whose threshold still exceeds Q** with a finite-length margin.
3. Efficiency follows: f = (1 − R) / h(Q).

## 4. Degree profile and the threshold curve

Chosen profile (node perspective): **{3: 0.75, 6: 0.125, 8: 0.125}**, average column degree 4.0, heavy columns placed first so masks have a contiguous puncturable region.

Density evolution under the actual decoder (normalized min-sum, α = 0.75), from `model/de.py`:

| Rate | 0.475 | 0.550 | 0.625 | 0.700 | 0.775 | 0.850 | 0.925 |
|---|---|---|---|---|---|---|---|
| Threshold | 8.78% | 7.07% | 5.49% | 4.04% | 2.73% | 1.58% | 0.59% |
| Shannon limit | 11.85% | 9.41% | 7.24% | 5.32% | 3.63% | 2.15% | 0.91% |
| **f at threshold** | 1.223 | 1.221 | 1.223 | 1.229 | 1.245 | 1.278 | 1.432 |

**f at threshold is ≈ 1.22 at every rate.** That is the ensemble's ceiling — the gap between its threshold and capacity — and no mask, margin or iteration count can beat it.

## 5. The three mother codes

Built with PEG plus 4-cycle-free lifting (`model/peg.py`), n = 65,536, Z = 128, n_b = 512, 2,048 base edges each:

| Code | R₀ | layers m_b | syndrome bits | max row degree | serves |
|---|---|---|---|---|---|
| `v3_mother_0_r850` | 0.850 | 77 | 9,856 | **27** | Q = 1–2% |
| `v3_mother_1_r700` | 0.700 | 154 | 19,712 | 14 | Q = 3–6% |
| `v3_mother_2_r400` | 0.400 | 307 | 39,296 | 7 | Q = 8% |

## 6. Mask table and measured performance

Margin 1.25 (threshold must exceed QBER by that factor):

| QBER | code R₀ | mask rate | punctured | shortened | leak | rank OK | f | **FER** | iterations |
|---|---|---|---|---|---|---|---|---|---|
| 1% | 0.850 | 0.850 | 0 | 0 | 9,920 | ✓ | 1.874 | 0.00 | 5.0 |
| 2% | 0.850 | 0.775 | 0 | 21,760 | 9,920 | ✓ | 1.602 | 0.00 | 6.4 |
| 3% | 0.700 | 0.701 | 128 | 0 | 19,648 | ✓ | 1.545 | 0.00 | 6.5 |
| 4% | 0.700 | 0.625 | 0 | 12,928 | 19,776 | ✓ | 1.551 | 0.00 | 5.9 |
| 5% | 0.700 | 0.575 | 0 | 19,200 | 19,776 | ✓ | 1.490 | 0.00 | 6.6 |
| 6% | 0.700 | 0.525 | 0 | 24,064 | 19,776 | ✓ | 1.456 | 0.00 | 6.6 |
| 8% | 0.400 | 0.400 | 0 | 0 | 39,360 | ✓ | 1.493 | 0.00 | 5.9 |

Zero undetected errors. Every punctured column set passed the **GF(2) rank check** (`model/rank.py`), so the `leak = m − p` accounting of [05 §3.5](05-algorithm-spec.md#35-leakage-accounting) is licensed rather than assumed.

Tightening the margin trades efficiency against iterations, and therefore against decoder throughput:

| Margin | f range | iterations | FER |
|---|---|---|---|
| 1.25 | 1.46–1.87 | 5–7 | 0.00 |
| 1.10 | 1.35–1.56 | 8–11 | 0.00 |
| 1.05 | 1.29–1.56 | 11–20 | 0.00 except 0.07 at Q = 3% |

## 7. REQ-PERF-01 is not met

Target f ≤ 1.15; measured floor **f ≈ 1.30**. The gap decomposes as:

| Contribution | Size |
|---|---|
| Ensemble's threshold gap | ≈ 1.22 |
| Finite-length margin for FER ≤ 10⁻² | ≈ +0.08 at margin 1.05 |

Masks and margins cannot close this. The levers, in order of expected value:

1. **Optimise the degree distribution numerically** against the DE threshold. This pass evaluated 12 hand-written profiles; real LDPC design searches λ(x) and ρ(x), and published irregular ensembles sit much closer to capacity. **This is the next task for this document.**
2. **Extend the rate grid above 0.925** — the 1% point's f = 1.87 is an artefact of the grid ceiling, not of the code.
3. **Re-state the requirement** if the optimised ensemble lands near 1.2. A measured 1.2 is worth more than an aspirational 1.15.

## 8. Reproduce

```bash
uv run python scripts/design_codes3.py --margin 1.25     # the current design
uv run python scripts/export_code_mem.py --code codes/v3_mother_1_r700.npz --out rtl/gen
```

Design passes v1 and v2 are kept as `scripts/design_codes.py` and `design_codes2.py`; v2 also computes the threshold curve that v3 reuses.

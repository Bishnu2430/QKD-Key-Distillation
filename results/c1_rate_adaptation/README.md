# C1 — rate adaptation from one mother code (L1, baseline code)

| Field | Value |
|---|---|
| Question | Can one mother code, plus puncture/shorten masks, cover QBER 1–10% at a usable efficiency? |
| Model level | L1 float, layered normalized min-sum, α = 0.75, max 60 iterations |
| Mother code | Baseline random QC-LDPC, base 84 × 256, Z = 32 → **n = 8,192**, R₀ = 0.672, column weight 3 |
| Frames per candidate | 25 (smoke scale — see "What this is not") |
| Selection rule | Lowest-leakage mask whose FER ≤ 0.10, i.e. what the PS picks at run time (spec §6) |
| Data | [candidates.csv](candidates.csv), [meta.json](meta.json), [c1.png](c1.png), [puncture_probe.txt](puncture_probe.txt) |
| Undetected errors | **0** across every run |

## 1. Selected operating points

| QBER | effective rate R | punctured bits | shortened bits | achieved f | FER | avg iterations |
|---|---|---|---|---|---|---|
| 1% | — | — | — | **none met the FER target** | — | — |
| 2% | 0.745 | 800 | 0 | 1.867 | 0.00 | 6.2 |
| 3% | 0.699 | 320 | 0 | 1.589 | 0.00 | 8.7 |
| 4% | 0.625 | 0 | 1,024 | 1.585 | 0.00 | 6.3 |
| 5% | 0.613 | 0 | 1,248 | 1.384 | 0.08 | 13.2 |
| 6% | 0.494 | 0 | 2,880 | 1.582 | 0.00 | 6.3 |

The target is **f ≤ 1.15** over 2–8% (REQ-PERF-01). This baseline code reaches **1.38–1.87**, and fails the 1% point entirely. That is the gap the M3 code design has to close, now measured rather than assumed.

## 2. Where the failure comes from

Puncturing raises the rate, and at low QBER a high rate is exactly what you need: reaching R = 0.91 at 1% QBER from an R₀ = 0.672 mother code demands puncturing **26% of all positions**. Every such candidate failed with FER = 1.00. The pattern across the sweep:

| Puncture fraction of n | Outcome |
|---|---|
| ≤ 10% (≈ 800 bits) | decodes reliably |
| 15% (≈ 1,200 bits) | marginal: FER 0.48–0.68 |
| ≥ 20% (≈ 1,600 bits) | fails completely |

A punctured variable node arrives with zero channel information, so the decoder has to reconstruct it purely from neighbours. Past roughly a tenth of the positions, this construction cannot.

Shortening behaves much better — it only removes positions, and FER stays at 0 even at σ ≈ 35%. The cost is key bits: shortening 2,880 of 8,192 positions leaves fewer key bits per frame, so throughput per frame drops even though f stays flat.

## 3. Probe: does puncturing high-degree columns help?

A natural hypothesis: a punctured node recovers better when it has more neighbours, so a protograph with designated heavy columns should tolerate heavier puncturing. [puncture_probe.txt](puncture_probe.txt) tests it — 20% of columns at weight 6, the rest at weight 3, puncturing exactly the heavy ones, against the regular code with spread puncturing.

**The hypothesis holds only inside the 10% budget, and backfires beyond it.**

| QBER | punctured columns | regular + spread | irregular + heavy-column |
|---|---|---|---|
| 3% | 26 (10%) | FER 0.96 | **FER 0.24** |
| 2% | 38 (15%) | FER 0.68 | FER 1.00 |
| 1% | 38–51 (15–20%) | FER 0.00 | FER 1.00 |

At a 10% puncture budget, concentrating degree on the punctured columns is a clear win (0.96 → 0.24 FER at 3%). Beyond it, puncturing *all* the heavy columns strips the graph of its strongest nodes and the remaining weight-3 columns cannot carry the code. So "make punctured nodes heavy" is necessary but not sufficient: the heavy set must be **larger than the punctured set**, with spares left unpunctured.

## 4. Design implications for M3 (docs/06)

1. **Cap puncturing at about 10% of positions.** Treat it as a hard design rule, not a knob to push.
2. **Use two mother codes.** One at R₀ ≈ 0.85–0.88 to cover Q = 1–3% with light puncturing, one at R₀ ≈ 0.6–0.65 for Q = 4–10% via shortening. The single-code assumption in [docs/06](../../docs/06-ldpc-code-design.md) does not survive this measurement.
3. **Design a puncturable subset**, heavier than average, and puncture only part of it.
4. **Check the rank condition** of the punctured columns (spec §3.5). The sweep produced candidate points with f < 1 at heavy puncturing — those all had FER = 1.00, so nothing unphysical happened, but a point with f < 1 *and* successful decoding would mean the `m − p` accounting is wrong. `pipeline.measure` now flags this as `leak_below_limit`.
5. **Longer codes.** At n = 8,192 the finite-length penalty is large. The real design runs at n = 65,536.

## 5. What this is not

25 frames per candidate gives FER resolution of about 0.04 and no confidence interval worth quoting; the code is an unoptimised random construction with no density-evolution input; and n is 8× shorter than the target. The conclusions that survive this sample size are the **qualitative** ones in §4 — they are about which direction the design must move, not about the exact f it will reach.

## Reproduce

```bash
uv run python scripts/sweep_c1.py --frames 25 --qber 0.01 0.02 0.03 0.04 0.05 0.06
uv run python scripts/probe_puncturing.py
```

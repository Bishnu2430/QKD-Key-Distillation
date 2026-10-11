# E1, first run — L1 float model, baseline code

| Field | Value |
|---|---|
| Experiment | E1: FER and reconciliation efficiency against QBER ([11-evaluation-plan](../../docs/11-evaluation-plan.md)) |
| Model level | L1 (floating point), layered normalized min-sum, α = 0.75, max 50 iterations |
| Code | Baseline random QC-LDPC: base 64 × 192, Z = 32 → **n = 6,144**, m = 2,048, R₀ = 0.667, column weight 3 |
| Frames per point | 20 (a smoke-scale run; REQ-VER-02 wants ≥ 100 failures or 10⁵ frames for publishable curves) |
| Purpose | Prove the pipeline end to end and get a first feel for the baseline code |
| Data | [e1.csv](e1.csv), [meta.json](meta.json), [e1.png](e1.png) |

## Results

| QBER | FER | efficiency f | avg iterations (successes) |
|---|---|---|---|
| 1% | 0.00 | 4.255 | 2.0 |
| 2% | 0.00 | 2.430 | 3.0 |
| 3% | 0.00 | 1.768 | 5.2 |
| 4% | 0.20 | 1.419 | 17.0 |
| 5% | 1.00 | (1.200) | — |

## Reading

**1. Rate adaptation is not optional — this is the measurement that proves it.** A single fixed rate-0.667 code leaks 4.3× the Slepian–Wolf minimum at 1% QBER. Every one of those wasted bits comes straight off the final key. Contribution **C1** exists to collapse that number towards 1.1 across the whole 1–10% range, by puncturing at low QBER and shortening at high QBER.

**2. The decoding threshold of this baseline code sits between 4% and 5%.** For rate 0.667 the Shannon limit is h(Q) = 1 − R, i.e. Q\* ≈ 6.1%. A random (3, 9)-regular base graph with 4-cycle avoidance therefore loses roughly 1.3 percentage points to the limit — typical for an unoptimised construction, and the gap that density-evolution-guided degree distributions and PEG construction have to close in M3.

**3. Iteration count tracks the threshold.** 2 iterations at 1%, 17 at 4%, failure at 5%. Since throughput is inversely proportional to the average iteration count, the operating point chosen in E3 directly sets decoder speed; running a code near its threshold is slow as well as unreliable.

**4. No undetected errors.** Every frame that satisfied the syndrome also matched its verification tag, and every accepted frame was bit-identical to Alice's. That is the correctness property the 64-bit tag exists to guarantee.

## What this run is not

It is 20 frames per point on a 6,144-bit placeholder code, so the FER figures carry no statistical weight and the code is not the one we will publish. The real E1 runs on the M3 code set at n = 65,536 with the sample sizes in REQ-VER-02.

## Reproduce

```bash
uv run python scripts/sweep_e1.py --nb 192 --z 32 --frames 20 \
    --qber 0.01 0.02 0.03 0.04 0.05 --max-iters 50
```

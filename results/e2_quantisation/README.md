# E2 — quantisation study (L1 float against L2 bit-true)

| Field | Value |
|---|---|
| Question | Which fixed-point word widths does the RTL actually need? |
| Method | Same code, same frames, same seeds; only the fixed-point configuration changes. Each row is compared against the floating-point reference |
| Code | Baseline QC-LDPC, base 42 × 128, Z = 32 → n = 4,096, R₀ = 0.667, column weight 3 |
| Frames per point | 30, max 60 iterations |
| Data | [e2.csv](e2.csv), [meta.json](meta.json) |
| Undetected errors | 0 everywhere |

## Result: the spec defaults are right, and they sit exactly on the cliff edge

| Configuration | FER at 2% | 3% | 4% | vs float |
|---|---|---|---|---|
| **float reference** | 0.00 | 0.00 | 0.47 | — |
| **default: W_CH 5, W_MSG 6, W_APP 8, Δ 0.25, α 0.75** | 0.00 | 0.00 | 0.47 | **no loss** |
| W_MSG = 4 | 1.00 | 1.00 | 1.00 | catastrophic |
| W_MSG = 5 | 0.77 | 1.00 | 1.00 | catastrophic |
| W_MSG = 7 | 0.00 | 0.00 | 0.47 | no gain |
| W_APP = 6 | 1.00 | 0.90 | 0.50 | catastrophic |
| W_APP = 7 | 0.00 | 0.00 | 0.47 | **no loss** |
| W_APP = 10 | 0.00 | 0.00 | 0.47 | no gain |
| Δ = 0.5 | 0.00 | 0.00 | 0.67 | worse at 4% |
| Δ = 0.125 | 0.00 | 0.00 | 0.47 | no gain |
| α = 0.5 | 0.33 | 0.87 | 1.00 | catastrophic |
| α = 0.875 | 0.00 | 0.00 | 0.47 | no loss |
| α = 1.0 (plain min-sum) | 0.00 | 0.20 | 1.00 | clearly worse |

## Reading

**1. Six-bit messages, and not one bit fewer.** Dropping W_MSG from 6 to 5 takes the FER at 2% QBER from 0 to 0.77. Raising it to 7 buys nothing. The spec's choice is the minimum that works, which is exactly where you want to be when memory is the binding resource.

**2. W_APP = 7 is enough; the spec's 8 carries one bit of margin.** Seven bits matches float exactly, six bits collapses. Since check-node and APP storage dominate the decoder's BRAM budget ([docs/07 §5.1](../../docs/07-hw-architecture.md)), that bit is worth revisiting in M4 — though whether it saves real BRAM depends on how the words pack into 36-bit memories.

**3. Normalisation is doing real work.** Plain min-sum (α = 1.0) loses at 3% and fails at 4%; over-normalising (α = 0.5) is worse still. α = 0.75 and 0.875 both match float, and 0.75 is the cheaper one in hardware: two shifts and an add, against three shifts and two adds.

**4. Δ = 0.25 is the right LLR step.** Coarser (0.5) costs 20 points of FER at 4% QBER; finer (0.125) gains nothing while needing wider words.

**5. The quantisation loss of the chosen configuration is zero at this sample size.** That is the claim the paper needs: the bit-true model behaves like the float model, so the FER curves measured in software describe the hardware.

## Caveats

30 frames per point resolves FER to about ±0.03, so "no loss" means "no loss I can see at this resolution" — small degradations at low FER would hide. The code is the n = 4,096 baseline, not the M3 design, and the cliff positions can move with the degree distribution. **E2 must be re-run on the final code set before the widths are frozen in RTL.** The qualitative ordering (6-bit messages, 7–8-bit APP, α = 0.75, Δ = 0.25) is unlikely to change.

## Reproduce

```bash
uv run python scripts/sweep_e2.py --frames 30 --qber 0.02 0.03 0.04
```

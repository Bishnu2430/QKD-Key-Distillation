# E3 — the two run-time knobs: mask rate and I_max

| Question | The hardware is fixed. What can the PS still choose per frame, and what does each choice cost? |
|---|---|
| Model | L2 bit-true, 40 frames per point, `v3_mother_1_r700`, seed 11 |
| Hardware | The implemented stage-8 decoder: 10,149 cycles an iteration, 1,181 fixed per frame, 125 MHz, 0.917 W |
| Data | [rate_sweep.csv](rate_sweep.csv), [imax_sweep.csv](imax_sweep.csv), [meta.json](meta.json) |
| Reproduce | `uv run python scripts/sweep_e3.py --frames 40` |
| Requirements | REQ-PERF-04 (throughput), REQ-PERF-05 (latency), REQ-FUN-04 (I_max) |

Throughput and energy come from the model's iteration counts put through the measured cycle model, so they describe the decoder that exists. The power figure behind the energy column is still the vectorless estimate ([stage 9](../../docs/stages/09-power-saif.md) replaces it).

## 1. REQ-PERF-04 is met — at a mask we had not been using

The project has been quoting 37 Mbit/s at Q = 5% and calling the requirement missed. That number came from the stage-5 vector set, whose mask has **16 punctured columns as well as 125 shortened** ones. Puncturing raises the rate, and the decoder pays for it in iterations:

| Mask at Q = 5% | Rate | *f* | Iterations | Throughput |
|---|---|---|---|---|
| 16 punctured + 125 shortened (the test set) | 0.628 | 1.30 | 15.75 | 37 Mbit/s |
| **125 shortened, none punctured** | 0.599 | 1.41 | **8.4** | **71.6 Mbit/s** |

**Those 16 punctured columns nearly double the decode time.** Dropping them costs 0.11 in efficiency and takes the design from missing REQ-PERF-04 by 26% to clearing it by 43% — on the same gates, with no RTL change. It is consistent with what [C1](../c1_rate_adaptation/README.md) found at the code-design level: punctured variables arrive with no channel information, and the decoder has to reconstruct them from their neighbours.

## 2. The full trade curve

Each row is 40 frames. `secret` is the asymptotic secret key rate — throughput × (1 − f·h(Q) − h(Q)) — which is what a QKD system actually gets.

### Q = 5%

| Shortened columns | Rate | *f* | FER | Iterations | Mbit/s | Secret Mbit/s | nJ/bit |
|---|---|---|---|---|---|---|---|
| 64 | 0.656 | 1.204 | 0.97 | 28.0 | 25.1 | 9.3 | 36.5 |
| 96 | 0.630 | 1.297 | 0.00 | 14.2 | 45.7 | 15.6 | 20.1 |
| 128 | 0.599 | 1.405 | 0.00 | 8.1 | 73.5 | 22.9 | 12.5 |
| **160** | **0.562** | **1.533** | **0.00** | **6.1** | **89.6** | **24.6** | **10.2** |
| 192 | 0.519 | 1.686 | 0.00 | 5.0 | 99.6 | 23.0 | 9.2 |

### The optimum is not where efficiency is best

| QBER | Best *f* that decodes | Most secret key | | |
|---|---|---|---|---|
| | | columns | *f* | secret Mbit/s |
| 3% | 1.552 (0 shortened) | 32 | 1.656 | **68.9** |
| 4% | 1.245 → fails; 1.328 decodes | 128 | 1.661 | **41.4** |
| 5% | 1.204 → FER 0.97; 1.297 decodes | 160 | 1.533 | **24.6** |
| 6% | 1.229 → FER 0.78; 1.340 decodes | 192 | 1.474 | **14.6** |

**Shortening past the efficiency optimum is worth it.** Going from 96 to 160 shortened columns at Q = 5% makes *f* worse by 0.24 — but iterations fall from 14.2 to 6.1, throughput doubles, and the secret key rate rises by 58%. The gain runs out at 192 columns, where the leakage finally outweighs the speed.

That is a result about this *system*, not this code: with early termination, the decoder's time is proportional to iterations, and iterations fall much faster than efficiency degrades. Choosing a mask purely to minimise leakage leaves secret key on the floor.

### And it halves the energy

Energy per bit falls monotonically with shortening — 20.1 → 10.2 nJ/bit at Q = 5% between the 96- and 160-column masks — because energy is cycles, and cycles are iterations. The operating point that maximises secret key rate is also the efficient one to run.

## 3. I_max — how low it can go

At Q = 5% with 125 shortened columns (average 8.4 iterations):

| I_max | FER | Worst-case latency | REQ-PERF-05 (≤2 ms) |
|---|---|---|---|
| 8 | **0.475** | 0.66 ms | frames fail |
| 12 | 0.000 | 0.98 ms | ✅ |
| 16 | 0.000 | 1.31 ms | ✅ |
| 20 | 0.000 | 1.63 ms | ✅ |
| **24** | 0.000 | **1.96 ms** | ✅ |
| 28 | 0.000 | 2.28 ms | ❌ |
| 32 | 0.000 | 2.61 ms | ❌ |

I_max cannot exceed **24** without breaking the latency requirement at 125 MHz, and nothing above 12 improves FER at this operating point. **24 is the right default**: it satisfies REQ-PERF-05 with no measured FER cost and leaves 12 iterations of headroom over the average for harder frames than these 40.

REQ-FUN-04 marks the default "TBC". This is the number to confirm it at.

## 4. What this does not say

- **40 frames per point** resolves FER down to about 0.025. A point reported as FER 0.00 here is consistent with anything below that, and REQ-PERF-03 asks for ≤10⁻². Confirming the chosen operating point needs a long run at that point alone.
- **One mother code.** Everything here is `v3_mother_1_r700`. At Q = 3% the r850 code would be the right starting rate, and at Q = 8% the r400 one — neither has been built in hardware, so neither appears.
- **Asymptotic key rate**, no finite-key correction; the `secret` column is an upper bound.
- **The energy column inherits the vectorless power estimate.** Stage 9 replaces 0.917 W with a measurement, and every nJ/bit here scales with it.

## 5. What changes as a result

| | Before | After |
|---|---|---|
| REQ-PERF-04 at Q = 5% | 37 Mbit/s, **missed** | **71.6 Mbit/s** at the no-puncture mask, met |
| REQ-PERF-05 | met only at I_max = 24, untested | met at I_max ≤ 24, FER unchanged down to 12 |
| Operating point policy | "lowest leakage that decodes" | **"most secret key"** — which is 1–2 mask steps lower in rate |

The mask tables the PS uses should be rebuilt around the secret-key-rate optimum rather than the efficiency optimum. That is a change to [spec §6](../../docs/05-algorithm-spec.md)'s selection rule, and it is free.

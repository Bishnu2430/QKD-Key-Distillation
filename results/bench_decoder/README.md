# Decoder throughput: reference models vs Numba kernels

| Field | Value |
|---|---|
| Question | Can we afford the sample sizes REQ-VER-02 asks for (≥ 100 frame errors or 10⁵ frames per point)? |
| Method | Same frames, same seeds, decoded by each implementation in turn; JIT warmed up before timing |
| Conditions | QBER 3%, max 30 iterations, 20 frames per size, single core |
| Data | [bench.json](bench.json) |

## Results

| Code size | reference (bit-true) | Numba kernel | speed-up | frames/s | time for 10⁵ frames |
|---|---|---|---|---|---|
| n = 4,096 | 0.42 s | 0.04 s | **11.3×** | 544 | 0.05 h |
| n = 8,192 | 1.06 s | 0.05 s | **21.5×** | 406 | 0.07 h |
| n = 16,384 | 1.01 s | 0.14 s | 7.2× | 143 | 0.19 h |
| **n = 65,536** | 2.78 s | 0.54 s | **5.2×** | 37 | **0.75 h** |

The kernels are bit-exact with the reference implementations — identical hard decisions, identical iteration counts, identical final LLRs — which is enforced by `tests/test_fast.py`. That is what makes them usable for published curves.

## What this unlocks

At the target frame length **n = 65,536**, one 10⁵-frame point now costs about **45 minutes on one core**. A full E1 sweep of 10 QBER points × 2 masks is therefore roughly 15 core-hours, which is an overnight run, or about 1.5 hours spread across the 12 cores available. Before acceleration the same sweep would have taken most of a week.

## Notes

- The speed-up shrinks with code size (21× at n = 8,192, 5× at n = 65,536) because the NumPy reference amortises its per-call overhead better when the per-layer arrays get larger. The absolute kernel time is what matters, and it scales roughly linearly with n.
- Timings are at QBER 3%, where most frames converge in a handful of iterations. Near the decoding threshold the average iteration count rises and throughput falls proportionally — budget for the worst QBER point, not the average.
- Everything here is single core. The obvious next step for long sweeps is to run points in parallel across cores, since each (QBER, mask) point is independent.
- Code construction is not a bottleneck: the n = 65,536 base matrix with 4-cycle rejection builds in 0.2 s.

## Reproduce

```bash
uv run python scripts/bench_decoder.py --frames 20 --max-iters 30
```

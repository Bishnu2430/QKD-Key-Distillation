# Stage 14 — Error verification

`toeplitz_tag` computes the 64-bit Toeplitz tag of [spec §4](../../docs/05-algorithm-spec.md#4-error-verification)
over a decoded key, so a frame can be shown to be *correct* rather than merely
self-consistent. Verified against the L2 model and implemented at 125 MHz.

**It costs 3.1% of the LUTs, 18 mW, and about 0.8% of a frame's cycles.**

## Verification

Four frames from `tv/r700_q05_m16s125/`, each hashed twice — once with the
correct decoded key and once with key bit 0 flipped — with randomised stalls on
the input stream:

```
frame 0: tag=14fa78d75f0b328e  (expected 14fa78d75f0b328e)  ok=1
          bit0 flipped -> a743d9ed2bafdd1e  (expected a743d9ed2bafdd1e)  ok=0
frame 1: tag=40bbe5558a9235ae  (expected 40bbe5558a9235ae)  ok=1
          bit0 flipped -> a3eacf9eb68a9136  (expected a3eacf9eb68a9136)  ok=0
frame 2: tag=52a562cda4a471ad  (expected 52a562cda4a471ad)  ok=1
          bit0 flipped -> 17476cf7d3ac3cf6  (expected 17476cf7d3ac3cf6)  ok=0
frame 3: tag=eb1a1248773846ca  (expected eb1a1248773846ca)  ok=1
          bit0 flipped -> e5bf9c8aed69263b  (expected e5bf9c8aed69263b)  ok=0
STAGE 14 PASSED
```

All eight tags bit-exact. The tags are computed over the **real decoded keys**
already in that vector set, not synthetic bits, so this exercises the decoder's
actual output.

The corrupted half is the half that matters. A tag unit that reproduces a
number proves arithmetic; one that *changes* when the key changes proves it
does the job of §4. `tag_ok` asserts on all four correct keys and drops on all
four corrupted ones.

## Implementation

| | Value |
|---|---|
| WNS | **+1.518 ns**, 0 failing of 677 endpoints |
| WHS | +0.159 ns |
| Slice LUTs | **1,629 (3.06%)** |
| Slice registers | 222 (0.21%) |
| Block RAM tiles | 4 (2.86%) |
| Dynamic power | **0.018 W** |
| Total on-chip | 0.121 W (0.103 W of it static) |

Fully routed, zero routing errors, zero DRC violations.

The critical path is exactly the architecture: `seed_mem` block RAM
clock-to-out → the AND-XOR tree → `acc_reg[51]`. Four LUT levels (two LUT6, one
LUT5, one LUT4), 6.427 ns of data path, 75% of it routing. The forecast was
about three levels, which is close enough that the AND-XOR reduction is
collapsing into LUT6s as intended.

### Cost against the decoder

| | Decoder | Tag | Tag as % |
|---|---|---|---|
| Slice LUTs | 25,489 | 1,629 | 6.4% |
| Dynamic power | 0.824 W | 0.018 W | 2.2% |
| Cycles per frame | ~180,800 | ~1,489 | 0.8% |

Verification is cheap in every dimension that was in doubt. The real cost is
not on this table: the seed is `n_key + 63` bits, **5,944 bytes per frame**,
about the size of the key itself, and it has to cross AXI every frame.

## The block RAM came in at double the forecast

Predicted 2 tiles, got **4**, and the reason is a parameter sitting eight words
on the wrong side of a boundary.

`SEED_DEPTH` is 1,032 × 64 bits. A RAMB36 in 1024 × 36 mode needs **two tiles
side by side** to reach 64 bits wide, and 1,032 > 1,024 needs **two rows**. Two
by two is four. At `SEED_DEPTH = 1024` it would be one row of two.

1,032 was chosen to cover the largest key the code can produce — an entirely
unpunctured, unshortened block, `n_key` = 65,536 bits, which needs 1,025 seed
words. But **no mask in this project is anywhere near that**: every mask
punctures 16 base columns, capping `n_key` at 63,488 bits, or 993 seed words.
The mask actually used here needs 743.

So `SEED_DEPTH = 1024` would halve the block RAM and still cover every mask the
code design produces, at the cost of refusing a hypothetical zero-puncture
zero-shortening key. That is a two-tile saving out of 86 free, so it is not
urgent — it is recorded because the same boundary will matter much more in
stage 15, where the memories are larger and the tile count is not a rounding
error.

Flagged as reasoning, not measurement: the 4-tile figure is measured, the
2-tile figure is a prediction, and the last BRAM prediction in this project was
the one that missed.

## Requirements

| | Target | Status |
|---|---|---|
| REQ-IMP-02 timing | WNS ≥ 0 at 125 MHz | ✅ +1.518 ns |
| REQ-IMP-03 resources | ≤70% LUT, ≤80% BRAM | ✅ 3.1% / 2.9% |
| Spec §4 | 64-bit tag, 2-universal | ✅ bit-exact against the model |

## What this is the first half of

The spec notes that the tag "reuses the §5 datapath with ℓ = t" — contribution
**C3**, one GF(2) multiply shared by verification and privacy amplification.
This module is that datapath with the output chunk equal to the whole output,
`B = t = 64`, which is why a single 128-bit shift register serves all 64 output
bits and one pass over the key suffices.

It asserts `T <= W + 1` and **stage 15 will trip that assertion**. Privacy
amplification wants thousands of output bits, which needs several chunks and a
pass over the key per chunk. The arithmetic here is that inner loop; the
chunking is what stage 15 adds around it.

## Files

| File | Contents |
|---|---|
| `tag_timing_summary_routed.rpt` | WNS +1.518 ns, 0 of 677 failing |
| `tag_utilization_placed.rpt` | 1,629 LUTs, 222 FFs, 4 block RAM tiles |
| `tag_power_routed.rpt` | 0.018 W dynamic, 0.121 W total |
| `tag_route_status.rpt` | Fully routed, no routing errors |

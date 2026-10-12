# 03 — Requirements Specification

| Version | 0.1 (draft), 21 Sep 2026 |
|---|---|
| Status | Targets are **provisional** until the M3 code-design results; items marked **TBC** will be fixed then |

## 1. How to read this document

Each requirement has an ID `REQ-<AREA>-<nn>`, a measurable target, a rationale, and a verification method. The method is one of:

- **T**: test (simulation)
- **A**: analysis (calculation or report)
- **I**: inspection (review)

Verification and evaluation items are defined in [10-verification-plan](10-verification-plan.md) (L1–L6) and [11-evaluation-plan](11-evaluation-plan.md) (E1–E7).

| Area | Meaning |
|---|---|
| FUN | Functional behaviour |
| SEC | Security accounting |
| PERF | Performance |
| IMP | Implementation constraints |
| IF | Interfaces |
| VER | Verification quality |
| REP | Reporting and reproducibility |

Symbols follow the [system model](04-system-model.md#notation).

---

## 2. Functional requirements

| ID | Requirement | Target | Rationale | Verify |
|---|---|---|---|---|
| REQ-FUN-01 | Reconcile sifted-key frames by one-way, syndrome-based LDPC decoding. Alice sends $s = Hx_A$; Bob decodes $y$ to $\hat{x}$ with $H\hat{x} = s$. | — | One-way, parallel, hardware-friendly (see [ADR-003](decisions/ADR-003-ldpc-over-cascade-and-polar.md)) | T (L3) |
| REQ-FUN-02 | Operate over a QBER range | $Q \in [1.0\%, 10.0\%]$ | Covers metro to long-haul DV-QKD operating points | T (E1) |
| REQ-FUN-03 | Adapt the rate from **one mother code** using puncture/shorten masks selectable per frame | ≥ 10 rate points (TBC) | One datapath and one matrix ROM | T (L3, E1) |
| REQ-FUN-04 | Iterative decoding with early termination when $H\hat{x} = s$; configurable maximum iterations | $I_{max}$ ∈ [1, 63], default 32 (TBC) | Throughput depends on average, not maximum, iterations | T (L3) |
| REQ-FUN-05 | Report per-frame status: decode success flag and iterations used | — | Needed for FER and throughput accounting | T (L3) |
| REQ-FUN-06 | Verify each frame with a universal-hash tag; discard frames whose tags differ | Tag length $t = 64$ bits | Catches decoder convergence to a wrong codeword | T (L3), A |
| REQ-FUN-07 | Privacy amplification by Toeplitz hashing, with runtime-configurable input length $N$ and output length $\ell \le N$ | $N$ up to $2^{20}$ in the model; RTL range TBC in C3 | Standard 2-universal family; parallel structure | T (L3) |
| REQ-FUN-08 | The accelerator generates **no** randomness. All seeds (puncture fill, verification, PA) are supplied by the PS. | — | Keeps entropy sourcing auditable and outside the RTL | I |
| REQ-FUN-09 | Mother-code frame length | $n = 65{,}536$ (primary). Models also support $2^{14}$–$2^{17}$ | Best efficiency that fits BRAM on `xc7z020` (see [07](07-hw-architecture.md)) | A (E6) |

## 3. Security-accounting requirements

| ID | Requirement | Target | Rationale | Verify |
|---|---|---|---|---|
| REQ-SEC-01 | Account for all information disclosed during reconciliation and verification: $\lambda_{EC} = \sum_{\text{frames}} (m - p) + t$ per frame. Use $m$ instead of $m-p$ if [05 §3.5](05-algorithm-spec.md#35-leakage-accounting)'s rank condition isn't met. | Exact accounting | Leaked bits reduce the final key one for one | A, I |
| REQ-SEC-02 | Security parameters (project defaults) | $\varepsilon_{cor} \le 10^{-12}$ per block, $\varepsilon_{sec} \le 10^{-9}$ | Typical order of magnitude in the literature; recorded in [ADR-004](decisions/ADR-004-security-parameters.md) | A |
| REQ-SEC-03 | Failed or unverified frames are never passed to privacy amplification | — | Correctness | T (L3) |
| REQ-SEC-04 | The PS computes output length $\ell$ from the finite-key formula in [04 §5](04-system-model.md#5-finite-key-secret-key-length) | — | Security proof compliance | A |
| REQ-SEC-05 | Leakage from discarded frames is counted conservatively (included in $\lambda_{EC}$) unless a later ADR justifies otherwise | — | Conservative by default | I |

## 4. Performance requirements

Targets apply at the post-implementation Fmax on `xc7z020clg400-1`, with $n = 65{,}536$.

| ID | Requirement | Target | Stretch | Rationale | Verify |
|---|---|---|---|---|---|
| REQ-PERF-01 | Reconciliation efficiency for $Q \in [2\%, 8\%]$ at FER ≤ $10^{-2}$ | $f \le 1.15$ | $f \le 1.10$ | Comparable to f ≈ 1.1 in Mao & Li 2019 and f ≈ 1.11 in Liao 2025 | T (E1, L2) |
| REQ-PERF-02 | Reconciliation efficiency at the range edges ($Q$ = 1%, 9%, 10%) | $f \le 1.25$ | $f \le 1.15$ | High-rate and low-rate edges are harder | T (E1) |
| REQ-PERF-03 | Frame error rate at the selected operating point | FER ≤ $10^{-2}$ | ≤ $10^{-3}$ | Failed frames waste raw key | T (E1) |
| REQ-PERF-04 | Decoder throughput at $Q = 5\%$ using the average iteration count | ≥ 50 Mbps | ≥ 100 Mbps | Matches tens-of-Mbps sifted-key rates of modern systems | A (E3, E4) |
| REQ-PERF-05 | Worst-case decoder latency per frame (at $I_{max}$) | ≤ 2 ms (TBC) | — | Bounds buffering | A (E4) |
| REQ-PERF-06 | Estimated PL dynamic power of the accelerator | ≤ 1.0 W | ≤ 0.5 W | Low-power goal | A (L6, E4) |
| REQ-PERF-07 | Decoder energy per corrected bit | ≤ 40 nJ/bit | ≤ 10 nJ/bit | More than 20× better than ≈ 970 nJ/bit (Liao 2025, estimated) | A (E4, E7) |
| REQ-PERF-08 | PA throughput, direct Toeplitz method | ≥ 25 Mbps at $N = 2^{17}$ (TBC) | NTT method: ≥ 50 Mbps at $N = 10^6$ | Direct cost grows as $N\ell$; see the [learning guide §17](00-learning-guide.md#17-hardware-for-toeplitz-hashing) | A (E6) |

## 5. Implementation requirements

| ID | Requirement | Target | Rationale | Verify |
|---|---|---|---|---|
| REQ-IMP-01 | Target device and tool | `xc7z020clg400-1`; Vivado version pinned in [ADR-002](decisions/ADR-002-toolchain-and-vivado-version.md) | Low-cost SoC used on PYNQ-Z2 and Zybo Z7-20 | I |
| REQ-IMP-02 | Timing closure | WNS ≥ 0 at ≥ 125 MHz PL clock (stretch 150 MHz) | Throughput target | A (L4) |
| REQ-IMP-03 | Resource ceiling for the full accelerator | ≤ 70% LUT, ≤ 80% BRAM36, ≤ 50% DSP | Leaves room for AXI infrastructure and routing | A (L4) |
| REQ-IMP-04 | HDL | Synthesisable SystemVerilog-2012 subset ([13](13-rtl-coding-guidelines.md)); no encrypted IP in the datapath (AXI DMA/interconnect IP allowed) | Portability and open-source release | I |
| REQ-IMP-05 | Parameterisable design | Frame length, lifting size, message widths and $\alpha$ as SV parameters | Enables the E2/E6 sweeps | I |

## 6. Interface requirements

| ID | Requirement | Target | Verify |
|---|---|---|---|
| REQ-IF-01 | Data interfaces | AXI4-Stream, 64-bit TDATA, with TLAST at frame end | T (L3) |
| REQ-IF-02 | Control interface | AXI4-Lite, 32-bit registers, map defined in [08](08-interfaces-regmap.md) | T (L3) |
| REQ-IF-03 | Bit order | As defined in [05 §2](05-algorithm-spec.md#2-conventions) (LSB-first packing) | T (L3) |

## 7. Verification-quality requirements

| ID | Requirement | Target | Verify |
|---|---|---|---|
| REQ-VER-01 | RTL is bit-exact against the L2 model | ≥ 1,000 random frames per (QBER, rate) point, zero mismatches | T (L3) |
| REQ-VER-02 | Statistical confidence of the FER/f curves (from L2) | ≥ 100 frame errors per point, or ≥ $10^5$ frames | T (E1) |
| REQ-VER-03 | Post-implementation timing simulation is bit-exact | ≥ 10 frames per rate | T (L5) |
| REQ-VER-04 | Power estimated with switching activity from simulation, not vectorless | SAIF-annotated `report_power` | A (L6) |
| REQ-VER-05 | L1 (float) and L2 (fixed) models agree within the stated quantisation loss | Documented $\Delta f$ and $\Delta$FER per point | T (E2) |

## 8. Reporting and reproducibility requirements

| ID | Requirement | Verify |
|---|---|---|
| REQ-REP-01 | Every published number is traceable to: git commit, tool versions, part and speed grade, clock constraint, WNS, and random seeds | I |
| REQ-REP-02 | Power is always labelled "estimated", with Vivado's confidence level | I |
| REQ-REP-03 | The words "post-implementation" or "simulation" are used; never "measured" or "real-time demonstrated" | I |
| REQ-REP-04 | Code, models and scripts are released under an open licence (choice in a later ADR) | I |

## 9. Open items (TBC list)

| Item | Decided by | When |
|---|---|---|
| Number of rate points and QBER bins (REQ-FUN-03) | Code design (06) | M3 |
| **Single mother code (REQ-FUN-03)** — the L1 sweep shows one code cannot cover 1-10% within the puncture budget; likely becomes two mother codes | Code design (06), results/c1_rate_adaptation | M3 |
| Default $I_{max}$ (REQ-FUN-04) | E3 | M3 |
| RTL range of $N$ (REQ-FUN-07) and PA target (REQ-PERF-08) | C3 analysis | M6 |
| Latency bound (REQ-PERF-05) | Architecture (07) | M4 |
| Licence (REQ-REP-04) | ADR | M8 |

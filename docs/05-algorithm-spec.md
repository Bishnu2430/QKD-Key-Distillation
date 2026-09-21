# 05 — Algorithm Specification (Golden Reference)

| Version | 0.1 (draft), 21 Sep 2026 |
|---|---|
| Status | Normative for the L1/L2 models and the RTL. Parameters marked **TBC** are fixed by E2 (quantisation) and [06](06-ldpc-code-design.md) (code design). |

> **Rule:** if the RTL and this document disagree, one of them is wrong. Fix it here first, bump the version, then change the code. Models and RTL cite the section numbers they implement.

The words **MUST**, **SHOULD** and **MAY** are used as in RFC 2119.

---

## 1. Scope

This document defines, bit-exactly:

1. LDPC syndrome reconciliation with rate adaptation (§3).
2. Error verification (§4).
3. Toeplitz privacy amplification (§5).
4. PS-side rate selection (§6).

Sifting, parameter estimation, the finite-key length computation and authentication are defined in [04-system-model](04-system-model.md).

## 2. Conventions

| Item | Convention |
|---|---|
| Bit indexing | Frames and blocks are sequences $b_0, b_1, \dots$ Index 0 is the first bit. |
| Word packing | Bit $j$ is stored in 64-bit word $\lfloor j/64\rfloor$, at bit position $j \bmod 64$ (**LSB-first**). Lengths that aren't multiples of 64 are zero-padded in the last word. |
| Arithmetic on bits | Addition is XOR (⊕), multiplication is AND. All matrix/vector products are over GF(2). |
| LLR sign | $L > 0$ favours bit 0; $L < 0$ favours bit 1. Hard decision: $\hat{x} = 1 \iff L < 0$ (so $L = 0 \Rightarrow 0$). |
| $\operatorname{sign}(v)$ | $+1$ if $v \ge 0$, else $-1$ |
| Signed integers | Two's complement, width $W$. Symmetric range $[-M_W, +M_W]$ with $M_W = 2^{W-1}-1$. The value $-2^{W-1}$ MUST never be produced. |
| $\operatorname{sat}_W(v)$ | $\min(\max(v, -M_W), +M_W)$ |
| Right shift | $v \gg k$ on a **non-negative** integer is $\lfloor v / 2^k \rfloor$ |

### 2.1 Fixed-point parameters

| Parameter | Meaning | Default | Status |
|---|---|---|---|
| `W_CH` | Channel-LLR magnitude width (signed) | 5 → $M = 15$ | TBC (E2) |
| `W_MSG` | Check-to-variable message width | 6 → $M = 31$ | TBC (E2) |
| `W_APP` | A-posteriori LLR width | 8 → $M = 127$ | TBC (E2) |
| $\Delta$ | LLR quantisation step | 0.25 | TBC (E2) |
| $\alpha$ | Normalisation factor | 0.75, implemented as $(v\gg1)+(v\gg2)$ | TBC (E2) |

## 3. Reconciliation

### 3.1 Code representation (QC-LDPC)

The mother code is defined by a base matrix $B$ of size $m_b \times n_b$ and a lifting size $Z$. Then $n = n_b Z$ and $m = m_b Z$.

- $B[r,c] = -1$ means an all-zero $Z\times Z$ block.
- $B[r,c] = k \in [0, Z-1]$ means the block $P^k$, where $P^k$ has ones exactly at $(i, (i+k) \bmod Z)$ for $i = 0,\dots,Z-1$.

So check $r Z + i$ connects to variable $c Z + ((i + B[r,c]) \bmod Z)$ for every $c$ with $B[r,c] \ne -1$.

**Structural constraint (MUST):** every non-negative entry of $B$ is a *single* circulant. Consequently, within one block row (a **layer**), each variable node connects to at most one check. This makes the $Z$ checks of a layer independent, so processing them in parallel gives *exactly* the same result as processing them serially. The RTL relies on this for bit-exactness.

**Neighbour order:** for check $i$ in layer $r$, its neighbours $\mathcal{N}(i)$ are listed in increasing base-column index $c$. This order defines tie-breaking in §3.6.

### 3.2 Syndrome computation (Alice)

Given the full $n$-bit word $w$ (§3.3), Alice computes $s_i = \bigoplus_{j \in \mathcal{N}(i)} w_j$ for $i = 0,\dots,m-1$ and sends $s$ ($m$ bits).

### 3.3 Rate adaptation (puncturing and shortening)

A **rate mask** with id `mask_id` defines two disjoint position sets $\mathcal{P}$ (punctured, size $p$) and $\mathcal{S}$ (shortened, size $s$). They are tabulated in [06](06-ldpc-code-design.md). The key positions are $\mathcal{K} = \{0..n-1\} \setminus (\mathcal{P} \cup \mathcal{S})$, with $n_{key} = n - p - s$.

**Alice builds $w$:**
- Key bits $x_A$ fill $\mathcal{K}$ in increasing position order.
- $w_j$ for $j \in \mathcal{P}$ is a fresh **private** uniformly random bit.
- $w_j = 0$ for $j \in \mathcal{S}$.

**Bob initialises LLRs:**

| Position | Initial $L_j$ |
|---|---|
| $j \in \mathcal{K}$ | $+A$ if $y_j = 0$, else $-A$ (§3.4) |
| $j \in \mathcal{P}$ | $0$ |
| $j \in \mathcal{S}$ | $+M_{W\_APP}$ (known 0) |

Effective rate: $R = (R_0 - \sigma)/(1 - \pi - \sigma)$ with $\pi = p/n$ and $\sigma = s/n$.

### 3.4 Channel LLR quantisation

The PS computes, from $\hat{Q}$:

$$L_{ch} = \ln\frac{1-\hat{Q}}{\hat{Q}},\qquad A = \min\!\left(M_{W\_CH},\ \max\!\left(1,\ \operatorname{round}(L_{ch}/\Delta)\right)\right)$$

`round` is round-half-away-from-zero. $A$ is written to the accelerator per frame (see [08](08-interfaces-regmap.md)). The L1 float model uses $L_{ch}$ directly.

### 3.5 Leakage accounting

Per frame, the disclosed information is

$$\lambda_{frame} = \begin{cases} m - p + t & \text{if the columns of } H \text{ indexed by } \mathcal{P} \text{ are linearly independent over GF(2)} \\ m + t & \text{otherwise (conservative)} \end{cases}$$

where $t = 64$ is the verification tag length (§4). *Reasoning:* the syndrome reveals $m$ bits about $w$. When the punctured columns have full rank, the $p$ private random fill bits hide $p$ of those bits. The rank condition MUST be checked once per mask during code design and recorded in [06](06-ldpc-code-design.md).

### 3.6 Decoding: layered normalized min-sum (L2, bit-true)

**State:** APP values $L_j$ (`W_APP` bits) for $j = 0..n-1$, and messages $R_{ij}$ (`W_MSG` bits) for every edge, all initially $0$ except $L_j$ from §3.3.

```text
for it = 1 .. I_max:
    for r = 0 .. m_b-1:                       # layer order: natural (TBC in 06)
        for each check i in layer r:          # Z checks; order irrelevant (§3.1)
            for j in N(i):                    # neighbour order (§3.1)
                T[j]  = sat_APP( L[j] - R[i][j] )
                a[j]  = min( |T[j]|, M_MSG )
            sgn  = (-1)^s[i] * prod_j sign(T[j])
            idx  = first j in N(i) order with a[j] == min_j a[j]
            min1 = a[idx]
            min2 = min_{j != idx} a[j]
            for j in N(i):
                mag      = min2 if j == idx else min1
                Rn       = sgn * sign(T[j]) * norm(mag)      # norm(v) = (v>>1)+(v>>2)
                R[i][j]  = Rn
                L[j]     = sat_APP( T[j] + Rn )
    x_hat[j] = 1 if L[j] < 0 else 0,  for all j
    if H x_hat == s:  return (success, it, x_hat)
return (failure, I_max, x_hat)
```

Notes (normative):

1. `sgn * sign(T[j])` equals the product of the signs of all *other* neighbours, times $(-1)^{s_i}$. This is the syndrome-aware check update.
2. Early termination is evaluated **only at iteration boundaries**, so every implementation stops on the same iteration.
3. An implementation MAY store check messages in compressed form (min1, min2, idx, sign bits) if it reproduces $R_{ij}$ exactly.
4. **Output:** $\hat{x}_{key}$, the bits of $\hat{x}$ at positions $\mathcal{K}$ in increasing order; `iters` = `it`; `ok` = success flag.

### 3.7 Floating-point reference (L1)

Same as §3.6 with real numbers: $L_j$ initialised with $\pm L_{ch}$; $\pm\infty$ (or a large constant, 1e3) at $\mathcal{S}$; no saturation; `norm(v)` = $\alpha v$ with real $\alpha$. L1 MAY also provide sum-product decoding as a performance reference:

$$R_{ij} = (-1)^{s_i}\, 2\tanh^{-1}\!\Big(\prod_{j' \in \mathcal{N}(i)\setminus j}\tanh(T_{j'}/2)\Big).$$

## 4. Error verification

For each frame that decodes successfully, Alice draws a public seed $v$ of $n_{key} + t - 1$ bits (**after** Bob reports decoding). Both parties compute a $t = 64$-bit Toeplitz tag:

$$\text{tag}_i = \bigoplus_{j=0}^{n_{key}-1} v_{i+j}\, x_j,\qquad i = 0,\dots,t-1$$

Alice uses $x = x_A$ and Bob uses $x = \hat{x}_{key}$. Alice sends $\text{tag}^A$. If $\text{tag}^A \ne \text{tag}^B$, the frame MUST be discarded.

- Toeplitz hashing is 2-universal, so for $\hat{x}_{key} \ne x_A$, $\Pr[\text{tags equal}] \le 2^{-t}$.
- Over a block of $K$ frames, $\varepsilon_{cor} \le K \cdot 2^{-64}$. Example: $K = 153$ frames (≈ 10⁷ bits) gives ≈ 8.3 × 10⁻¹⁸, well below $10^{-12}$.
- The tag reuses the §5 datapath with $\ell = t$ (contribution C3). A polynomial hash over GF(2⁶⁴) is an alternative, to be evaluated in an ADR.

## 5. Privacy amplification

**Input:** block $X$ of $N$ bits, the concatenation of $\hat{x}_{key}$ (Bob) or $x_A$ (Alice) over the kept frames, in frame-sequence order.
**Seed:** public $\tau$ of $N + \ell - 1$ bits, drawn by Alice after verification.
**Output:** $k$ of $\ell$ bits,

$$k_i = \bigoplus_{j=0}^{N-1} \tau_{i+j}\, X_j,\qquad i = 0,\dots,\ell-1.$$

Equivalently, $k$ is a window of the GF(2) polynomial product $\tau(z)\cdot X^{rev}(z)$. Any implementation (direct, word-parallel, FFT/NTT) MUST produce identical bits. $\ell$ comes from [04 §5](04-system-model.md#5-finite-key-secret-key-length). A modified-Toeplitz variant $[I_\ell \mid T']$ (seed $N-1$ bits) MAY be added later behind a mode flag; it is not the default.

## 6. Rate selection (PS)

Given $\hat{Q}$, the PS selects the mask with the **lowest leakage** among masks whose design QBER $Q_d \ge \hat{Q}$ (table in [06](06-ldpc-code-design.md)). If $\hat{Q}$ exceeds the largest $Q_d$, the frame is not reconciled and the block is aborted.

## 7. Test vectors

The M2/M3 models MUST generate test vectors in `model/tv/`:

| Set | Content |
|---|---|
| TV-SYN | Random $w$ → $s$ for every mask |
| TV-DEC | $(y, s, \text{mask}, A)$ → $(\hat{x}_{key}, \text{iters}, \text{ok})$ from L2, ≥ 1,000 per (QBER, mask) point |
| TV-VER | $(x, v)$ → tag |
| TV-PA | $(X, \tau, \ell)$ → $k$, including $N$ not a multiple of 64 |

Files are packed per §2 and stored as hex, one 64-bit word per line (LSB-first), with a JSON header giving parameters and the RNG seed.

## Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-09-21 | Initial draft |

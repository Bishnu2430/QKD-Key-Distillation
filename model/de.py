"""Density evolution for normalized min-sum on the binary symmetric channel.

Density evolution predicts, for an *ensemble* of codes described only by its
degree distributions, the largest channel error rate at which decoding still
drives the error probability to zero: the **threshold**. It is how a degree
distribution is chosen before any matrix is built (docs/06 section 4).

This implementation tracks the message density on a uniform LLR grid and
applies the update rules of the decoder we actually use — normalized min-sum,
not sum-product — so the prediction matches the hardware's algorithm.

Conventions
-----------
* All-zero codeword assumption, which is standard and valid for symmetric
  channels: a negative LLR is an error.
* Edge-perspective degree distributions: ``lam[i]`` is the fraction of *edges*
  attached to a variable node of degree ``i``; ``rho[j]`` likewise for checks.
* The check-node update is **exact** for min-sum (no sign/magnitude
  factorisation). Writing the incoming message as a (sign, magnitude) pair and
  letting ``T+-(m) = P(magnitude >= m, sign = +-)``, the tails of the outgoing
  message over ``d`` independent inputs follow from

      U = T+ + T-,   D = T+ - T-,   U_d = U**d,   D_d = D**d,
      T+-_d = (U_d +- D_d) / 2

  because the minimum needs every input to exceed ``m`` and the signs multiply
  (a convolution over Z_2, diagonalised by the sum and difference). An earlier
  version treated sign and magnitude as independent and produced thresholds
  *above* the Shannon limit, which is how the error was caught; thresholds are
  still cross-checked against simulation in ``scripts/design_codes.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .info import channel_llr


@dataclass(frozen=True)
class Grid:
    """Uniform LLR grid, symmetric around zero: values (k - K) * step."""

    step: float = 0.05
    half: int = 1200  # K; range is +/- half*step

    @property
    def size(self) -> int:
        return 2 * self.half + 1

    @property
    def values(self) -> np.ndarray:
        return (np.arange(self.size) - self.half) * self.step

    def index_of(self, llr: float) -> int:
        return int(np.clip(round(llr / self.step) + self.half, 0, self.size - 1))


DEFAULT_GRID = Grid()


def channel_density(qber: float, grid: Grid = DEFAULT_GRID) -> np.ndarray:
    """BSC(Q) LLR density: mass 1-Q at +ln((1-Q)/Q), mass Q at -that."""
    p = np.zeros(grid.size)
    c = channel_llr(qber)
    p[grid.index_of(+c)] += 1.0 - qber
    p[grid.index_of(-c)] += qber
    return p


def _convolve(a: np.ndarray, b: np.ndarray, grid: Grid) -> np.ndarray:
    """Density of the sum of two independent LLRs, folding the tails inward."""
    full = np.convolve(a, b)  # index r <-> value (r - 2K) * step
    k = grid.half
    out = np.zeros(grid.size)
    out[:] = full[k : k + grid.size]
    out[0] += full[:k].sum()  # everything below the grid saturates
    out[-1] += full[k + grid.size :].sum()
    return out


def check_update(p: np.ndarray, deg: int, alpha: float, grid: Grid) -> np.ndarray:
    """Outgoing check-node density for ``deg - 1`` i.i.d. incoming messages.

    Exact for min-sum: the outgoing magnitude is the minimum of the incoming
    magnitudes and the outgoing sign is the product of the incoming signs, and
    the two are *not* treated as independent (see the module docstring).
    """
    d = deg - 1
    if d <= 0:
        out = np.zeros(grid.size)
        out[grid.half] = 1.0
        return out

    k = grid.half
    # mass by (magnitude, sign); magnitude 0 counts as positive, as sign(0) = +
    mass_pos = np.zeros(k + 1)
    mass_neg = np.zeros(k + 1)
    mass_pos[0] = p[k]
    mass_pos[1:] = p[k + 1 :]
    mass_neg[1:] = p[:k][::-1]

    # tails T(m) = P(magnitude >= m, sign), with a zero entry past the end
    t_pos = np.concatenate([np.cumsum(mass_pos[::-1])[::-1], [0.0]])
    t_neg = np.concatenate([np.cumsum(mass_neg[::-1])[::-1], [0.0]])

    u = np.clip(t_pos + t_neg, 0.0, 1.0) ** d  # P(all magnitudes >= m)
    v = (t_pos - t_neg) ** d  # sign parity factor
    tail_pos = 0.5 * (u + v)
    tail_neg = 0.5 * (u - v)

    pmf_pos = np.clip(tail_pos[:-1] - tail_pos[1:], 0.0, 1.0)
    pmf_neg = np.clip(tail_neg[:-1] - tail_neg[1:], 0.0, 1.0)

    out = np.zeros(grid.size)
    scaled = np.clip(np.rint(alpha * np.arange(k + 1)).astype(int), 0, k)
    np.add.at(out, k + scaled, pmf_pos)
    np.add.at(out, k - scaled, pmf_neg)
    total = out.sum()
    if total > 0:
        out /= total  # guard against rounding drift
    return out


def variable_update(
    ch: np.ndarray,
    check_density: np.ndarray,
    lam: dict[int, float],
    grid: Grid,
) -> np.ndarray:
    """Outgoing variable-node density, mixed over the variable degrees."""
    max_deg = max(lam)
    powers = {0: None}
    acc = None
    out = np.zeros(grid.size)
    for d in range(1, max_deg):
        acc = check_density.copy() if acc is None else _convolve(acc, check_density, grid)
        powers[d] = acc
    for deg, weight in lam.items():
        if weight <= 0:
            continue
        dens = ch if deg == 1 else _convolve(ch, powers[deg - 1], grid)
        out += weight * dens
    return out


def error_probability(p: np.ndarray, grid: Grid) -> float:
    """P(LLR < 0) + half the mass exactly at zero."""
    k = grid.half
    return float(p[:k].sum() + 0.5 * p[k])


def evolve(
    qber: float,
    lam: dict[int, float],
    rho: dict[int, float],
    alpha: float = 0.75,
    iterations: int = 200,
    grid: Grid = DEFAULT_GRID,
    tol: float = 1e-7,
) -> tuple[bool, float, int]:
    """Run density evolution at one QBER.

    Returns ``(converged, final error probability, iterations used)``.
    """
    ch = channel_density(qber, grid)
    edge = ch.copy()
    prev = 1.0
    for it in range(1, iterations + 1):
        chk = np.zeros(grid.size)
        for deg, weight in rho.items():
            if weight > 0:
                chk += weight * check_update(edge, deg, alpha, grid)
        edge = variable_update(ch, chk, lam, grid)

        err = error_probability(edge, grid)
        if err < tol:
            return True, err, it
        if err > prev - 1e-12 and it > 10:  # stalled: no longer improving
            return False, err, it
        prev = err
    return False, error_probability(edge, grid), iterations


def threshold(
    lam: dict[int, float],
    rho: dict[int, float],
    alpha: float = 0.75,
    lo: float = 0.001,
    hi: float = 0.2,
    steps: int = 18,
    iterations: int = 200,
    grid: Grid = DEFAULT_GRID,
) -> float:
    """Largest QBER at which the ensemble still converges (bisection)."""
    if not evolve(lo, lam, rho, alpha, iterations, grid)[0]:
        return 0.0
    for _ in range(steps):
        mid = 0.5 * (lo + hi)
        if evolve(mid, lam, rho, alpha, iterations, grid)[0]:
            lo = mid
        else:
            hi = mid
    return lo


# ---------------------------------------------------------------------------
# degree-distribution helpers
# ---------------------------------------------------------------------------
def regular(dv: int, dc: int) -> tuple[dict[int, float], dict[int, float]]:
    """Edge-perspective distributions of a regular (dv, dc) ensemble."""
    return {dv: 1.0}, {dc: 1.0}


def design_rate(lam: dict[int, float], rho: dict[int, float]) -> float:
    """R = 1 - (sum rho_j / j) / (sum lam_i / i)."""
    num = sum(w / j for j, w in rho.items())
    den = sum(w / i for i, w in lam.items())
    return 1.0 - num / den


def node_to_edge(node_fractions: dict[int, float]) -> dict[int, float]:
    """Convert node-perspective degree fractions to edge perspective."""
    total = sum(f * d for d, f in node_fractions.items())
    return {d: f * d / total for d, f in node_fractions.items() if f > 0}


def check_degrees_for_rate(lam: dict[int, float], rate: float) -> dict[int, float]:
    """Pick a (possibly mixed) check degree giving the target design rate.

    Solves ``sum rho_j / j = (1 - R) * sum lam_i / i`` with mass on two
    neighbouring integer degrees, which is what a real base matrix can realise.
    """
    target = (1.0 - rate) * sum(w / i for i, w in lam.items())
    dc = 1.0 / target
    lo, hi = int(np.floor(dc)), int(np.ceil(dc))
    if lo == hi or lo < 2:
        return {max(2, lo): 1.0}
    # weight w on lo, 1-w on hi such that w/lo + (1-w)/hi == target
    w = (target - 1.0 / hi) / (1.0 / lo - 1.0 / hi)
    w = float(np.clip(w, 0.0, 1.0))
    return {lo: w, hi: 1.0 - w}

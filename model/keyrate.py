"""Secret-key rate: channel model, asymptotic decoy rate, finite-key skeleton.

Implements docs/04-system-model.md sections 3 and 5, and produces the E5 curve
(secret key rate against fibre distance) that connects this project's hardware
numbers — reconciliation efficiency f, frame error rate, block size — to the
quantity QKD people actually care about.

Two levels of rigour, deliberately separated:

``asymptotic_rate``
    The standard decoy-state GLLP rate (Lo, Ma & Chen 2005; Ma et al. 2005).
    Complete and quotable.

``finite_key_length``
    **Not publication-ready.** The decoy estimators are transcribed verbatim
    from Wiesemann, Krause, Tupkary, Lütkenhaus, Rusca & Walenta, *Quantum*
    (2026), arXiv:2405.16578v3 — Eq. (103) for the vacuum bound, Eq. (114) for
    the single-photon bound, the v_{X,1}^+ bound, Eq. (117) for the phase error
    and the Hoeffding deviation delta(n, eps) = sqrt(n ln(1/eps) / 2). The
    final epsilon bookkeeping of their Eq. (121) — the terms gamma, alpha_2,
    zeta' and Delta_ci — is **not** transcribed: those are exposed as
    parameters with conservative placeholder values. Before any number from
    this function appears in a paper, read section 6 of that paper and replace
    them. ``finite_key_length`` refuses to pretend otherwise: it returns a
    result flagged ``provisional=True``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .info import h

E0 = 0.5  # a dark count is wrong half the time


@dataclass(frozen=True)
class Channel:
    """Physical link parameters (docs/04-system-model.md section 3).

    Defaults are illustrative, not a reference system. Choosing and citing a
    published parameter set is an open M1 item.
    """

    attenuation_db_km: float = 0.2  # standard single-mode fibre at 1550 nm
    detector_efficiency: float = 0.2  # eta_Bob * eta_det
    dark_count_rate: float = 1e-6  # Y_0, per gate
    misalignment: float = 0.01  # e_d
    rep_rate_hz: float = 1e9
    sift_factor: float = 0.5  # q: symmetric BB84

    def transmittance(self, distance_km: float) -> float:
        return 10.0 ** (-self.attenuation_db_km * distance_km / 10.0)

    def eta(self, distance_km: float) -> float:
        return self.detector_efficiency * self.transmittance(distance_km)

    def gain(self, mu: float, distance_km: float) -> float:
        """Q_mu = Y_0 + 1 - exp(-eta*mu): probability Bob registers a click."""
        return self.dark_count_rate + 1.0 - math.exp(-self.eta(distance_km) * mu)

    def qber(self, mu: float, distance_km: float) -> float:
        """E_mu from E_mu Q_mu = e_0 Y_0 + e_d (1 - exp(-eta*mu))."""
        detections = 1.0 - math.exp(-self.eta(distance_km) * mu)
        return (E0 * self.dark_count_rate + self.misalignment * detections) / self.gain(mu, distance_km)

    def single_photon_yield(self, distance_km: float) -> float:
        """Y_1 in the infinite-decoy limit: Y_0 + eta - Y_0*eta."""
        eta = self.eta(distance_km)
        return self.dark_count_rate + eta - self.dark_count_rate * eta

    def single_photon_error(self, distance_km: float) -> float:
        """e_1 = (e_0 Y_0 + e_d eta) / Y_1."""
        eta = self.eta(distance_km)
        return (E0 * self.dark_count_rate + self.misalignment * eta) / self.single_photon_yield(distance_km)


def asymptotic_rate(
    channel: Channel,
    distance_km: float,
    mu: float = 0.5,
    f_ec: float = 1.15,
    fer: float = 0.0,
) -> dict:
    """Decoy-state GLLP rate: q{-Q_mu f h(E_mu) + Q_1 [1 - h(e_1)]}.

    ``fer`` discounts frames the decoder fails on, which is how this project's
    hardware performance enters the key rate.
    """
    q_mu = channel.gain(mu, distance_km)
    e_mu = channel.qber(mu, distance_km)
    y1 = channel.single_photon_yield(distance_km)
    e1 = channel.single_photon_error(distance_km)
    q1 = y1 * mu * math.exp(-mu)

    fraction = -q_mu * f_ec * h(e_mu) + q1 * (1.0 - h(min(e1, 0.5)))
    per_pulse = channel.sift_factor * max(0.0, fraction) * (1.0 - fer)
    return {
        "distance_km": distance_km,
        "mu": mu,
        "gain": q_mu,
        "qber": e_mu,
        "y1": y1,
        "e1": e1,
        "secret_per_pulse": per_pulse,
        "secret_bps": per_pulse * channel.rep_rate_hz,
        "f_ec": f_ec,
        "fer": fer,
    }


def optimal_mu(
    channel: Channel,
    distance_km: float,
    f_ec: float = 1.15,
    fer: float = 0.0,
    grid: np.ndarray | None = None,
) -> tuple[float, dict]:
    """Pick the intensity that maximises the asymptotic rate at this distance."""
    grid = np.linspace(0.05, 0.9, 35) if grid is None else grid
    best, best_mu = None, grid[0]
    for mu in grid:
        r = asymptotic_rate(channel, distance_km, float(mu), f_ec, fer)
        if best is None or r["secret_per_pulse"] > best["secret_per_pulse"]:
            best, best_mu = r, float(mu)
    return best_mu, best


# ---------------------------------------------------------------------------
# finite-key (provisional - see the module docstring)
# ---------------------------------------------------------------------------
def tau(n: int, intensities: dict[float, float]) -> float:
    """tau_n = sum_k p_k exp(-mu_k) mu_k^n / n!: probability Alice sends n photons."""
    return sum(p * math.exp(-mu) * mu**n / math.factorial(n) for mu, p in intensities.items())


def hoeffding_delta(n_total: float, eps: float) -> float:
    """delta(n, eps) = sqrt(n ln(1/eps) / 2)  [arXiv:2405.16578v3]."""
    return math.sqrt(0.5 * n_total * math.log(1.0 / eps))


@dataclass
class FiniteKeyResult:
    length: int
    s0: float
    s1: float
    phase_error: float
    leak_ec: float
    provisional: bool = True
    note: str = (
        "Decoy estimators are verbatim from arXiv:2405.16578v3; the epsilon "
        "bookkeeping of its Eq. (121) uses placeholder values. Not quotable."
    )


def finite_key_length(
    n_z: dict[float, float],
    c_x: dict[float, float],
    intensities: dict[float, float],
    n_z_total: float,
    n_x_total: float,
    leak_ec: float,
    eps_stat: float = 1e-12,
    eps_cor: float = 1e-12,
    eps_sec: float = 1e-9,
    gamma: float = 0.0,
    security_correction_bits: float | None = None,
) -> FiniteKeyResult:
    """1-decoy finite-key length, **provisional** (see the module docstring).

    Parameters
    ----------
    n_z, c_x : detections in the key basis and errors in the test basis, per
        intensity (mu -> count).
    intensities : mu -> probability that Alice picks that intensity.
    n_z_total, n_x_total : total sifted counts in each basis, for the Hoeffding
        deviation.
    leak_ec : bits disclosed by reconciliation and verification — the project's
        own hardware number.
    gamma, security_correction_bits : the unverified terms of Eq. (121). The
        default correction is the conservative placeholder
        ``2 log2(1/eps_sec) + log2(2/eps_cor)``.
    """
    mus = sorted(intensities, reverse=True)
    if len(mus) != 2:
        raise ValueError("this implements the 1-decoy protocol: two intensities")
    mu1, mu2 = mus
    p1, p2 = intensities[mu1], intensities[mu2]
    tau0, tau1 = tau(0, intensities), tau(1, intensities)

    d_z = hoeffding_delta(n_z_total, eps_stat)
    d_x = hoeffding_delta(n_x_total, eps_stat)
    n1_plus, n1_minus = n_z[mu1] + d_z, max(0.0, n_z[mu1] - d_z)
    n2_plus, n2_minus = n_z[mu2] + d_z, max(0.0, n_z[mu2] - d_z)
    c1_plus = c_x[mu1] + d_x
    c2_minus = max(0.0, c_x[mu2] - d_x)

    # Eq. (103): vacuum lower bound
    s0 = (tau0 / (mu1 - mu2)) * (
        mu1 * math.exp(mu2) * n2_minus / p2 - mu2 * math.exp(mu1) * n1_plus / p1
    )
    s0 = max(0.0, s0)
    # Upper bound on vacuum events. The paper states the lower bound only, so
    # this is Eq. (103) with the two Hoeffding deviations swapped - the natural
    # counterpart, and one of the terms to verify against section 6 before any
    # number from this function is quoted.
    s0_plus = max(s0, (tau0 / (mu1 - mu2)) * (
        mu1 * math.exp(mu2) * n2_plus / p2 - mu2 * math.exp(mu1) * n1_minus / p1
    ))

    # Eq. (114): single-photon lower bound (1-decoy)
    s1 = (mu1 * tau1 / (mu2 * (mu1 - mu2))) * (
        math.exp(mu2) * n2_minus / p2
        - (mu2**2 / mu1**2) * math.exp(mu1) * n1_plus / p1
        - ((mu1**2 - mu2**2) / mu1**2) * s0_plus / tau0
    )
    s1 = max(0.0, s1)

    # v_{X,1}^+ and Eq. (117): phase error bound
    v1 = (tau1 / (mu1 - mu2)) * (
        math.exp(mu1) * c1_plus / p1 - math.exp(mu2) * c2_minus / p2
    )
    v1 = max(0.0, v1)
    phase = min(0.5, v1 / s1) if s1 > 0 else 0.5

    if security_correction_bits is None:
        security_correction_bits = 2 * math.log2(1.0 / eps_sec) + math.log2(2.0 / eps_cor)

    length = s0 + s1 * (1.0 - h(min(0.5, phase + gamma))) - leak_ec - security_correction_bits
    return FiniteKeyResult(int(max(0, math.floor(length))), s0, s1, phase, leak_ec)


def expected_counts(
    channel: Channel,
    distance_km: float,
    intensities: dict[float, float],
    pulses: float,
    basis_prob: float,
) -> tuple[dict[float, float], dict[float, float], float]:
    """Expected sifted detections and errors per intensity, for a block.

    Returns ``(detections, errors, total)``. Expectation values, not samples:
    enough for a key-rate curve, not for a statistical study.
    """
    det: dict[float, float] = {}
    err: dict[float, float] = {}
    for mu, p in intensities.items():
        gain = channel.gain(mu, distance_km)
        det[mu] = pulses * p * basis_prob * gain
        err[mu] = det[mu] * channel.qber(mu, distance_km)
    return det, err, sum(det.values())

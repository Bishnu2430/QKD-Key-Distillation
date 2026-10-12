"""Key-rate model tests (docs/04-system-model.md sections 3 and 5)."""

from __future__ import annotations

import math

import pytest

from model import keyrate


@pytest.fixture
def channel() -> keyrate.Channel:
    return keyrate.Channel()


def test_transmittance_matches_the_loss_budget(channel):
    assert channel.transmittance(0) == pytest.approx(1.0)
    assert channel.transmittance(50) == pytest.approx(0.1)  # 10 dB
    assert channel.transmittance(100) == pytest.approx(0.01)


def test_gain_and_qber_at_short_distance(channel):
    """At 50 km the illustrative parameters give about 1% QBER (docs/00 section 6.1)."""
    assert channel.gain(0.5, 50) == pytest.approx(9.95e-3, rel=1e-2)
    assert channel.qber(0.5, 50) == pytest.approx(0.0100, abs=5e-4)


def test_qber_rises_when_dark_counts_dominate(channel):
    """Long distance: real clicks fall to the dark-count level and QBER explodes."""
    assert channel.qber(0.5, 250) > 0.2


def test_key_rate_falls_with_distance(channel):
    rates = [keyrate.asymptotic_rate(channel, d)["secret_per_pulse"] for d in (10, 50, 100, 150)]
    assert all(a > b for a, b in zip(rates, rates[1:]))


def test_key_rate_eventually_hits_zero(channel):
    assert keyrate.asymptotic_rate(channel, 300)["secret_per_pulse"] == 0.0


def test_worse_efficiency_costs_key(channel):
    good = keyrate.asymptotic_rate(channel, 50, f_ec=1.0)["secret_per_pulse"]
    poor = keyrate.asymptotic_rate(channel, 50, f_ec=1.5)["secret_per_pulse"]
    assert good > poor > 0


def test_frame_errors_scale_the_rate_linearly(channel):
    full = keyrate.asymptotic_rate(channel, 50, fer=0.0)["secret_per_pulse"]
    lossy = keyrate.asymptotic_rate(channel, 50, fer=0.1)["secret_per_pulse"]
    assert lossy == pytest.approx(0.9 * full)


def test_optimal_mu_beats_a_fixed_choice(channel):
    mu, best = keyrate.optimal_mu(channel, 100)
    fixed = keyrate.asymptotic_rate(channel, 100, mu=0.05)
    assert best["secret_per_pulse"] >= fixed["secret_per_pulse"]
    assert 0.0 < mu < 1.0


def test_tau_is_the_photon_number_distribution():
    intensities = {0.5: 0.7, 0.1: 0.3}
    t0 = keyrate.tau(0, intensities)
    t1 = keyrate.tau(1, intensities)
    assert t0 == pytest.approx(0.7 * math.exp(-0.5) + 0.3 * math.exp(-0.1))
    assert t1 == pytest.approx(0.7 * 0.5 * math.exp(-0.5) + 0.3 * 0.1 * math.exp(-0.1))
    assert 0 < t1 < t0 < 1


def test_hoeffding_delta_formula():
    assert keyrate.hoeffding_delta(1e6, 1e-10) == pytest.approx(
        math.sqrt(0.5 * 1e6 * math.log(1e10))
    )


def test_finite_key_is_flagged_provisional(channel):
    det, err, total = keyrate.expected_counts(
        channel, 50, {0.5: 0.7, 0.1: 0.3}, pulses=1e10, basis_prob=0.5
    )
    res = keyrate.finite_key_length(det, err, {0.5: 0.7, 0.1: 0.3},
                                    n_z_total=total, n_x_total=total,
                                    leak_ec=0.2 * total)
    assert res.provisional is True
    assert res.length >= 0
    assert 0.0 <= res.phase_error <= 0.5


def test_finite_key_grows_with_block_size(channel):
    intensities = {0.5: 0.7, 0.1: 0.3}
    lengths = []
    for pulses in (1e9, 1e10, 1e11):
        det, err, total = keyrate.expected_counts(channel, 50, intensities, pulses, 0.5)
        res = keyrate.finite_key_length(det, err, intensities, total, total,
                                        leak_ec=0.2 * total)
        lengths.append(res.length)
    assert lengths[0] < lengths[1] < lengths[2]

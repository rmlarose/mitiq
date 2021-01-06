# Copyright (C) 2020 Unitary Fund
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for zero-noise inference and extrapolation methods (factories) with
classically generated data.
"""
from copy import copy, deepcopy
from typing import Callable, List
from pytest import mark, raises, warns

import numpy as np
from numpy.random import RandomState

import cirq
from mitiq.zne.inference import (
    ExtrapolationError,
    ExtrapolationWarning,
    ConvergenceWarning,
    RichardsonFactory,
    FakeNodesFactory,
    LinearFactory,
    PolyFactory,
    ExpFactory,
    PolyExpFactory,
    AdaExpFactory,
    ExpBayesFactory,
)


# Constant parameters for test functions:
A = 0.5
B = 0.7
C = 0.4
D = 0.3
X_VALS = [1, 1.3, 1.7, 2.2, 2.4]

# FakeNodesFactory only accepts equally spaced scale factors
UNIFORM_X = np.linspace(1.0, 3.0, 20)

# FakeNodesFactory needs a larger tolerance
LARGE_TOL = 1.0e-1

STAT_NOISE = 0.0001
CLOSE_TOL = 1.0e-2
# PolyExp fit is non-linear, so we set a larger tolerance
POLYEXP_TOL = 2 * CLOSE_TOL
NOT_CLOSE_TOL = 1.0e-1

# Set a seed.
SEED = 808


def apply_seed_to_func(func: Callable, seed: int) -> Callable:
    """Applies the input seed to the input function by
    using a random state and returns the seeded function."""
    rnd_state = RandomState(seed)

    def seeded_func(x: float, err: float = STAT_NOISE) -> float:
        return func(x, err=err, rnd_state=rnd_state)

    return seeded_func


# Classical test functions with statistical error:
def f_lin(
    x: float, err: float = STAT_NOISE, rnd_state: RandomState = np.random
) -> float:
    """Linear function."""
    return A + B * x + rnd_state.normal(scale=err)


def f_non_lin(
    x: float, err: float = STAT_NOISE, rnd_state: RandomState = np.random
) -> float:
    """Non-linear function."""
    return A + B * x + C * x ** 2 + rnd_state.normal(scale=err)


def f_exp_down(
    x: float, err: float = STAT_NOISE, rnd_state: RandomState = np.random
) -> float:
    """Exponential decay."""
    return A + B * np.exp(-C * x) + rnd_state.normal(scale=err)


def f_exp_up(
    x: float, err: float = STAT_NOISE, rnd_state: RandomState = np.random
) -> float:
    """Exponential growth."""
    return A - B * np.exp(-C * x) + rnd_state.normal(scale=err)


def f_poly_exp_down(
    x: float, err: float = STAT_NOISE, rnd_state: RandomState = np.random
) -> float:
    """Poly-exponential decay."""
    return A + B * np.exp(-C * x - D * x ** 2) + rnd_state.normal(scale=err)


def f_poly_exp_up(
    x: float, err: float = STAT_NOISE, rnd_state: RandomState = np.random
) -> float:
    """Poly-exponential growth."""
    return A - B * np.exp(-C * x - D * x ** 2) + rnd_state.normal(scale=err)


def f_lin_shot(x: float, shots=1) -> float:
    """Linear function with "shots" argument."""
    return A + B * x + 0.001 / np.sqrt(shots)


def f_runge(x: float) -> float:
    """Function with a peak at x=3, which has a strong Runge effect
    with RichardsonFactory but not with FakeNodesFactory.
    """
    return 1.0 / ((x - 2) ** 2 + 1.0)


def f_exp_bayes(
    x: float, err: float = STAT_NOISE, rnd_state: RandomState = np.random
) -> float:
    """Exponential decay with with parameters suiting BayesFactroy."""
    return 0.5 + 0.5 * np.exp(-0.5 * x) + rnd_state.normal(scale=err)


@mark.parametrize("test_f", [f_lin, f_non_lin])
def test_noise_seeding(test_f: Callable[[float], float]):
    """Check that seeding works as expected."""
    seeded_f = apply_seed_to_func(test_f, SEED)
    noise_a = seeded_f(0)
    noise_b = seeded_f(0)
    seeded_f = apply_seed_to_func(test_f, SEED)
    noise_c = seeded_f(0)
    assert noise_a != noise_b
    assert noise_a == noise_c


@mark.parametrize(
    "factory",
    (
        LinearFactory,
        RichardsonFactory,
        FakeNodesFactory,
        PolyFactory,
        ExpFactory,
        PolyExpFactory,
        ExpBayesFactory,
    ),
)
def test_get_scale_factors_static_factories(factory):
    scale_factors = np.linspace(1.0, 10.0, num=20)
    if factory is PolyFactory or factory is PolyExpFactory:
        fac = factory(scale_factors=scale_factors, order=2)
    else:
        fac = factory(scale_factors=scale_factors)

    # Expectation values haven't been computed at any scale factors yet
    assert not fac.get_scale_factors()

    # Compute expectation values at all the scale factors
    fac.run_classical(apply_seed_to_func(f_lin, seed=1))
    assert isinstance(fac.get_scale_factors(), np.ndarray)
    assert np.allclose(fac.get_scale_factors(), scale_factors)


@mark.parametrize("factory", (AdaExpFactory,))
def test_get_scale_factors_adaptive_factories(factory):
    num_steps = 8
    fac = AdaExpFactory(steps=num_steps, scale_factor=2.0, asymptote=None)

    # Expectation values haven't been computed at any scale factors yet
    assert isinstance(fac.get_scale_factors(), np.ndarray)
    assert len(fac.get_scale_factors()) == 0

    # Compute expectation values at all the scale factors
    fac.run_classical(apply_seed_to_func(f_exp_up, seed=1))
    assert isinstance(fac.get_scale_factors(), np.ndarray)

    # Given this seeded executor, the scale factors should be as follows
    correct_scale_factors = np.array(
        [
            1.0,
            2.0,
            4.0,
            4.20469548,
            4.20310693,
            4.2054822,
            4.2031916,
            4.2052843,
        ]
    )
    assert len(fac.get_scale_factors()) == num_steps
    assert np.allclose(fac.get_scale_factors(), correct_scale_factors)


@mark.parametrize(
    "factory",
    (
        LinearFactory,
        RichardsonFactory,
        FakeNodesFactory,
        PolyFactory,
        ExpFactory,
        PolyExpFactory,
        ExpBayesFactory,
    ),
)
def test_get_expectation_values_static_factories(factory):
    scale_factors = np.linspace(1.0, 10.0, num=20)
    executor = apply_seed_to_func(f_lin, seed=1)
    expectation_values = np.array([executor(scale) for scale in scale_factors])

    if factory is PolyFactory or factory is PolyExpFactory:
        fac = factory(scale_factors=scale_factors, order=2)
    else:
        fac = factory(scale_factors=scale_factors)

    # Expectation values haven't been computed at any scale factors yet
    assert isinstance(fac.get_expectation_values(), np.ndarray)
    assert len(fac.get_expectation_values()) == 0

    # Compute expectation values at all the scale factors
    fac.run_classical(executor)
    assert isinstance(fac.get_expectation_values(), np.ndarray)
    assert np.allclose(
        fac.get_expectation_values(), expectation_values, atol=1e-3
    )


@mark.parametrize("factory", (AdaExpFactory,))
def test_get_expectation_values_adaptive_factories(factory):
    num_steps = 8
    fac = AdaExpFactory(steps=num_steps, scale_factor=2.0, asymptote=None)
    executor = apply_seed_to_func(f_exp_up, seed=1)

    # Expectation values haven't been computed at any scale factors yet
    assert isinstance(fac.get_expectation_values(), np.ndarray)
    assert len(fac.get_expectation_values()) == 0

    # Compute expectation values at all the scale factors
    fac.run_classical(executor)
    assert isinstance(fac.get_scale_factors(), np.ndarray)

    # Given this seeded executor, the scale factors should be as follows
    correct_scale_factors = np.array(
        [
            1.0,
            2.0,
            4.0,
            4.20469548,
            4.20310693,
            4.2054822,
            4.2031916,
            4.2052843,
        ]
    )
    correct_expectation_values = np.array(
        [executor(scale) for scale in correct_scale_factors]
    )
    assert len(fac.get_expectation_values()) == num_steps
    assert np.allclose(
        fac.get_expectation_values(), correct_expectation_values, atol=1e-3
    )


@mark.parametrize(
    "factory",
    (
        LinearFactory,
        RichardsonFactory,
        FakeNodesFactory,
        PolyFactory,
        ExpFactory,
        PolyExpFactory,
        ExpBayesFactory,
    ),
)
@mark.parametrize("batched", (True, False))
def test_run_sequential_and_batched(factory, batched):
    scale_factors = np.linspace(1.0, 10.0, num=20)

    if factory is PolyFactory or factory is PolyExpFactory:
        fac = factory(scale_factors=scale_factors, order=2)
    else:
        fac = factory(scale_factors=scale_factors)

    # Expectation values haven't been computed at any scale factors yet
    assert isinstance(fac.get_expectation_values(), np.ndarray)
    assert len(fac.get_expectation_values()) == 0

    # Compute expectation values at all the scale factors
    if batched:

        def executor(circuits) -> List[float]:
            return [1.0] * len(circuits)

    else:

        def executor(circuit):
            return 1.0

    fac.run(cirq.Circuit(), executor, scale_noise=lambda circ, _: circ)

    assert isinstance(fac.get_expectation_values(), np.ndarray)
    assert np.allclose(
        fac.get_expectation_values(), np.ones_like(scale_factors)
    )


@mark.parametrize(
    "factory",
    (
        LinearFactory,
        RichardsonFactory,
        FakeNodesFactory,
        PolyFactory,
        ExpFactory,
        PolyExpFactory,
        ExpBayesFactory,
    ),
)
def test_run_batched_with_keyword_args_list(factory):
    scale_factors = np.linspace(1.0, 10.0, num=20)
    shot_list = [int(scale) for scale in scale_factors]

    if factory is PolyFactory or factory is PolyExpFactory:
        fac = factory(
            scale_factors=scale_factors, order=2, shot_list=shot_list
        )
    else:
        fac = factory(scale_factors=scale_factors, shot_list=shot_list)

    # Expectation values haven't been computed at any scale factors yet
    assert isinstance(fac.get_expectation_values(), np.ndarray)
    assert len(fac.get_expectation_values()) == 0

    # Compute expectation values at all the scale factors
    def executor(circuits, kwargs_list) -> List[float]:
        assert len(circuits) == len(kwargs_list)
        return [1.0] * len(circuits)

    fac.run(cirq.Circuit(), executor, scale_noise=lambda circ, _: circ)

    assert isinstance(fac.get_expectation_values(), np.ndarray)
    assert np.allclose(
        fac.get_expectation_values(), np.ones_like(scale_factors)
    )


@mark.parametrize("test_f", [f_lin, f_non_lin])
def test_richardson_extr(test_f: Callable[[float], float]):
    """Test of the Richardson's extrapolator."""
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = RichardsonFactory(scale_factors=X_VALS)
    assert not fac._opt_params
    fac.run_classical(seeded_f)
    zne_value = fac.reduce()
    assert np.isclose(zne_value, seeded_f(0, err=0), atol=CLOSE_TOL)
    assert len(fac._opt_params) == len(X_VALS)
    assert np.isclose(fac._opt_params[-1], zne_value)


def test_fake_nodes_factory():
    """Test FakeNodesFactory in a specific regime in which the fake nodes
    interpolation method works well.
    """
    fac = FakeNodesFactory(UNIFORM_X)
    assert not fac._opt_params
    fac.run_classical(f_runge)
    zne_value = fac.reduce()
    assert np.isclose(zne_value, f_runge(0.0), atol=LARGE_TOL)
    assert len(fac._opt_params) == len(UNIFORM_X)
    assert np.isclose(fac._opt_params[-1], zne_value)


def test_fake_nodes_extrapolation():
    """Test that there exists a regime in which FakeNodesFactory
    is better than RichardsonFactory.
    Note: in many cases RichardsonFactory is better.
    """
    y_vals = [f_runge(x) for x in UNIFORM_X]
    zne_runge = FakeNodesFactory.extrapolate(UNIFORM_X, y_vals)
    zne_richard = RichardsonFactory.extrapolate(UNIFORM_X, y_vals)
    abs_err_runge = np.abs(zne_runge - f_runge(0.0))
    abs_err_richard = np.abs(zne_richard - f_runge(0.0))
    # Test Richardson extrapolation error is much larger
    assert 500 * abs_err_runge < abs_err_richard


def test_linear_extr():
    """Tests extrapolation with a LinearFactory."""
    seeded_f = apply_seed_to_func(f_lin, SEED)
    fac = LinearFactory(X_VALS)
    assert not fac._opt_params
    fac.run_classical(seeded_f)
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=CLOSE_TOL)
    assert np.allclose(fac._opt_params, [B, A], atol=CLOSE_TOL)


def test_poly_extr():
    """Test of polynomial extrapolator."""
    # test (order=1)
    fac = PolyFactory(X_VALS, order=1)
    fac.run_classical(f_lin)
    assert np.isclose(fac.reduce(), f_lin(0, err=0), atol=CLOSE_TOL)
    # test that, for some non-linear functions,
    # order=1 is bad while order=2 is better.
    seeded_f = apply_seed_to_func(f_non_lin, SEED)
    fac = PolyFactory(X_VALS, order=1)
    fac.run_classical(seeded_f)
    assert not np.isclose(fac.reduce(), seeded_f(0, err=0), atol=NOT_CLOSE_TOL)
    seeded_f = apply_seed_to_func(f_non_lin, SEED)
    fac = PolyFactory(X_VALS, order=2)
    fac.run_classical(seeded_f)
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=CLOSE_TOL)


def test_exp_bayes_extr():
    """Test of the ExpBayesFactory's extrapolator."""
    x_vals = np.linspace(1.0, 5.0, 20)
    seeded_f = apply_seed_to_func(f_exp_bayes, SEED)
    fac = ExpBayesFactory(scale_factors=x_vals)
    assert not fac._opt_params
    fac.run_classical(seeded_f)
    zne_value = fac.reduce()
    assert np.isclose(zne_value, seeded_f(0, err=0), atol=CLOSE_TOL)
    assert np.isclose(fac._zne_curve(0), seeded_f(0, err=0), atol=CLOSE_TOL)


@mark.parametrize("order", [2, 3, 4, 5])
def test_opt_params_poly_factory(order):
    """Tests that optimal parameters are stored after calling the reduce
    method.
    """
    fac = PolyFactory(scale_factors=np.linspace(1, 10, 10), order=order)
    assert not fac._opt_params
    fac.run_classical(apply_seed_to_func(f_non_lin, seed=SEED))
    zne_value = fac.reduce()
    assert len(fac._opt_params) == order + 1
    assert np.isclose(fac._opt_params[-1], zne_value)


@mark.parametrize("avoid_log", [False, True])
@mark.parametrize("test_f", [f_exp_down, f_exp_up])
def test_exp_factory_with_asympt(
    test_f: Callable[[float], float], avoid_log: bool
):
    """Test of exponential extrapolator."""
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = ExpFactory(X_VALS, asymptote=A, avoid_log=avoid_log)
    fac.run_classical(seeded_f)
    assert not fac._opt_params
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=CLOSE_TOL)

    # There are three parameters to fit in the exponential ansatz
    assert len(fac._opt_params) == 3


def test_exp_factory_bad_asympt():
    with raises(ValueError, match="must be either a float or None"):
        ExpFactory(X_VALS, asymptote=1j)


@mark.parametrize("test_f", [f_exp_down, f_exp_up])
def test_exp_factory_no_asympt(test_f: Callable[[float], float]):
    """Test of exponential extrapolator."""
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = ExpFactory(X_VALS, asymptote=None)
    fac.run_classical(seeded_f)
    assert not fac._opt_params
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=CLOSE_TOL)

    # There are three parameters to fit in the exponential ansatz
    assert len(fac._opt_params) == 3


@mark.parametrize("avoid_log", [False, True])
@mark.parametrize("test_f", [f_poly_exp_down, f_poly_exp_up])
def test_poly_exp_factory_with_asympt(
    test_f: Callable[[float], float], avoid_log: bool
):
    """Test of (almost) exponential extrapolator."""
    # test that, for a non-linear exponent,
    # order=1 is bad while order=2 is better.
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = PolyExpFactory(X_VALS, order=1, asymptote=A, avoid_log=avoid_log)
    fac.run_classical(seeded_f)
    assert not np.isclose(fac.reduce(), seeded_f(0, err=0), atol=NOT_CLOSE_TOL)
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = PolyExpFactory(X_VALS, order=2, asymptote=A, avoid_log=avoid_log)
    fac.run_classical(seeded_f)
    assert not fac._opt_params
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=POLYEXP_TOL)

    # There are four parameters to fit for the PolyExpFactory of order 1
    assert len(fac._opt_params) == 4


@mark.parametrize("test_f", [f_poly_exp_down, f_poly_exp_up])
def test_poly_exp_factory_no_asympt(test_f: Callable[[float], float]):
    """Test of (almost) exponential extrapolator."""
    seeded_f = apply_seed_to_func(test_f, SEED)
    # test that, for a non-linear exponent,
    # order=1 is bad while order=2 is better.
    fac = PolyExpFactory(X_VALS, order=1, asymptote=None)
    fac.run_classical(seeded_f)
    assert not np.isclose(fac.reduce(), seeded_f(0, err=0), atol=NOT_CLOSE_TOL)
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = PolyExpFactory(X_VALS, order=2, asymptote=None)
    fac.run_classical(seeded_f)
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=POLYEXP_TOL)


@mark.parametrize("avoid_log", [False, True])
@mark.parametrize("test_f", [f_exp_down, f_exp_up])
def test_ada_exp_factory_with_asympt(
    test_f: Callable[[float], float], avoid_log: bool
):
    """Test of the adaptive exponential extrapolator."""
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = AdaExpFactory(
        steps=3, scale_factor=2.0, asymptote=A, avoid_log=avoid_log
    )
    # Note: run_classical calls next which calls reduce, so calling
    # fac.run_classical with an AdaExpFactory sets the optimal parameters as
    # well. Hence we check that the opt_params are empty before
    # AdaExpFactory.run_classical is called.
    assert not fac._opt_params
    fac.run_classical(seeded_f)
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=CLOSE_TOL)

    # There are three parameters to fit for the (adaptive) exponential ansatz
    assert len(fac._opt_params) == 3


@mark.parametrize("avoid_log", [False, True])
@mark.parametrize("test_f", [f_exp_down, f_exp_up])
def test_ada_exp_fac_with_asympt_more_steps(
    test_f: Callable[[float], float], avoid_log: bool
):
    """Test of the adaptive exponential extrapolator with more steps.
    """
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = AdaExpFactory(
        steps=6, scale_factor=2.0, asymptote=A, avoid_log=avoid_log
    )
    fac.run_classical(seeded_f)
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=CLOSE_TOL)


@mark.parametrize("test_f", [f_exp_down, f_exp_up])
def test_ada_exp_factory_no_asympt(test_f: Callable[[float], float]):
    """Test of the adaptive exponential extrapolator."""
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = AdaExpFactory(steps=4, scale_factor=2.0, asymptote=None)
    fac.run_classical(seeded_f)
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=CLOSE_TOL)


@mark.parametrize("test_f", [f_exp_down, f_exp_up])
def test_ada_exp_factory_no_asympt_more_steps(
    test_f: Callable[[float], float],
):
    """Test of the adaptive exponential extrapolator."""
    seeded_f = apply_seed_to_func(test_f, SEED)
    fac = AdaExpFactory(steps=8, scale_factor=2.0, asymptote=None)
    fac.run_classical(seeded_f)
    assert np.isclose(fac.reduce(), seeded_f(0, err=0), atol=CLOSE_TOL)


def test_ada_exp_factory_bad_arguments():
    with raises(ValueError, match="must be an integer greater or equal to 3"):
        AdaExpFactory(steps=2.5)

    with raises(ValueError, match="must be strictly larger than one"):
        AdaExpFactory(steps=4, scale_factor=0.5)

    with raises(ValueError, match="must be strictly larger than one"):
        AdaExpFactory(steps=4, max_scale_factor=1)

    with raises(ValueError, match="must be either a float or None"):
        AdaExpFactory(steps=10, asymptote=1j)


def test_avoid_log_keyword():
    """Test that avoid_log=True and avoid_log=False give different results."""
    fac = ExpFactory(X_VALS, asymptote=A, avoid_log=False)
    fac.run_classical(f_exp_down)
    znl_with_log = fac.reduce()
    fac._options['avoid_log'] = True
    znl_without_log = fac.reduce()
    assert not znl_with_log == znl_without_log


@mark.parametrize(
    "factory",
    (
        LinearFactory,
        RichardsonFactory,
        FakeNodesFactory,
        ExpBayesFactory,
    )
)
def test_too_few_scale_factors(factory):
    """Test less than 2 scale_factors."""
    with raises(ValueError, match=r"At least 2 scale factors are necessary"):
        _ = factory([1])


def test_order_is_too_high_for_scale_factors():
    """Test that a wrong initialization error is raised."""
    with raises(ValueError, match=r"The extrapolation order cannot exceed"):
        _ = PolyFactory(X_VALS, order=10)


def test_too_few_points_for_polyfit_warning():
    """Test that the correct warning is raised if data is not enough to fit."""
    fac = PolyFactory(X_VALS, order=2)
    fac._instack = [
        {"scale_factor": 1.0, "shots": 100},
        {"scale_factor": 2.0, "shots": 100},
    ]
    fac._outstack = [1.0, 2.0]
    with warns(
        ExtrapolationWarning,
        match=r"The extrapolation fit may be ill-conditioned.",
    ):
        fac.reduce()
    # test also the static "extrapolate" method.
    with warns(
        ExtrapolationWarning,
        match=r"The extrapolation fit may be ill-conditioned.",
    ):
        PolyFactory.extrapolate([1.0, 2.0], [1.0, 2.0], order=2)


def test_failing_fit_error():
    """Test error handling for a failing fit."""
    fac = ExpFactory(X_VALS, asymptote=None)
    fac._instack = [{"scale_factor": x} for x in X_VALS]
    fac._outstack = [1.0, 2.0, 1.0, 2.0, 1.0]
    with raises(
        ExtrapolationError, match=r"The extrapolation fit failed to converge."
    ):
        fac.reduce()
    # test also the static "extrapolate" method.
    with raises(
        ExtrapolationError, match=r"The extrapolation fit failed to converge."
    ):
        ExpFactory.extrapolate(X_VALS, [1.0, 2.0, 1.0, 2.0, 1.0])


@mark.parametrize("fac", [LinearFactory([1, 1, 1]), ExpFactory([1, 1, 1])])
def test_failing_fit_warnings(fac):
    """Test that the correct warning is raised for an ill-conditioned fit."""
    fac._instack = [{"scale_factor": 1.0} for _ in range(4)]
    fac._outstack = [1, 1, 1, 1]
    with warns(
        ExtrapolationWarning,
        match=r"The extrapolation fit may be ill-conditioned.",
    ):
        fac.reduce()
    # test also the static "extrapolate" method.
    with warns(
        ExtrapolationWarning,
        match=r"The extrapolation fit may be ill-conditioned.",
    ):
        fac.extrapolate([1, 1, 1, 1], [1.0, 1.0, 1.0, 1.0])


def test_adaptive_factory_max_iteration_warnings():
    """Test that the correct warning is raised beyond the iteration limit."""
    fac = AdaExpFactory(steps=10)
    with warns(
        ConvergenceWarning,
        match=r"Factory iteration loop stopped before convergence.",
    ):
        fac.run_classical(lambda scale_factor: 1.0, max_iterations=3)


@mark.parametrize("factory", [LinearFactory, ExpFactory])
def test_equal_simple(factory):
    fac = factory(scale_factors=[1, 2, 3])
    assert fac != 1

    copied_fac = copy(fac)
    assert copied_fac == fac
    copied_fac._already_reduced = True
    assert copied_fac != fac

    fac._instack = [{"scale_factor": 1, "shots": 100}]
    copied_fac = deepcopy(fac)
    assert copied_fac == fac
    copied_fac._instack[0].update({"shots": 101})
    assert copied_fac != fac


@mark.parametrize(
    "factory",
    (
        LinearFactory,
        RichardsonFactory,
        FakeNodesFactory,
        PolyFactory,
        ExpBayesFactory,
    ),
)
def test_equal(factory):
    for run_classical in (True, False):
        if factory is PolyFactory:
            fac = factory(
                scale_factors=[1, 2, 3], order=2, shot_list=[1, 2, 3]
            )
        else:
            fac = factory(scale_factors=[1, 2, 3], shot_list=[1, 2, 3])
        if run_classical:
            fac.run_classical(
                scale_factor_to_expectation_value=lambda x, shots: np.exp(x)
                + 0.5
            )

        copied_factory = copy(fac)
        assert copied_factory == fac
        assert copied_factory is not fac

        if run_classical:
            fac.reduce()
            copied_factory = copy(fac)
            assert copied_factory == fac
            assert copied_factory is not fac


@mark.parametrize("fac_class", [LinearFactory, RichardsonFactory])
def test_iterate_with_shot_list(fac_class):
    """Tests factories with (and without) the "shot_list" argument."""
    # first test without shot_list
    fac = fac_class(X_VALS)
    fac.run_classical(f_lin_shot)
    assert np.isclose(fac.reduce(), f_lin_shot(0), atol=CLOSE_TOL)

    # Check instack and outstack are as expected
    SHOT_LIST = [100, 200, 300, 400, 500]
    for j, shots in enumerate(SHOT_LIST):
        assert fac._instack[j] == {"scale_factor": X_VALS[j]}
        assert fac._outstack[j] != f_lin_shot(X_VALS[j], shots=shots)
        assert fac._outstack[j] == f_lin_shot(X_VALS[j])

    # Now pass an arbitrary shot_list as an argument
    fac = fac_class(X_VALS, shot_list=SHOT_LIST)
    fac.run_classical(f_lin_shot)
    assert np.isclose(fac.reduce(), f_lin_shot(0), atol=CLOSE_TOL)

    # Check instack and outstack are as expected
    for j, shots in enumerate(SHOT_LIST):
        assert fac._instack[j] == {"scale_factor": X_VALS[j], "shots": shots}
        assert fac._outstack[j] == f_lin_shot(X_VALS[j], shots=shots)
        assert fac._outstack[j] != f_lin_shot(X_VALS[j])


def test_shot_list_errors():
    """Tests errors related to the "shot_lists" argument."""
    with raises(IndexError, match=r"must have the same length."):
        PolyFactory(X_VALS, order=2, shot_list=[1, 2])
    with raises(TypeError, match=r"valid iterator of integers"):
        PolyFactory(X_VALS, order=2, shot_list=[1.0, 2])


def test_push_after_already_reduced_warning():
    """Tests a warning is raised if new data is pushed in a factory
    which was already reduced."""
    fac = LinearFactory([1, 2])
    fac.push({"scale_factor": 1.0}, 1.0)
    fac.push({"scale_factor": 2.0}, 2.0)
    fac.reduce()
    with warns(
        ExtrapolationWarning,
        match=r"You are pushing new data into a factory object",
    ):
        fac.push({"scale_factor": 3.0}, 3.0)
    # Assert no warning is raised when .reset() is used
    fac.reset()
    fac.push({"scale_factor": 1.0}, 2.0)
    fac.push({"scale_factor": 2.0}, 1.0)
    assert np.isclose(3.0, fac.reduce())


def test_full_output_keyword():
    """Tests the full_output keyword in extrapolate method."""
    zne_limit = LinearFactory.extrapolate([1, 2], [1, 2])
    assert np.isclose(zne_limit, 0.0)
    (
        zne_limit,
        zne_std,
        opt_params,
        params_cov,
        zne_curve,
    ) = LinearFactory.extrapolate([1, 2], [1, 2], full_output=True)

    assert len(opt_params) == 2
    assert np.isclose(zne_limit, 0.0)
    assert np.isclose(0.0, opt_params[1])
    assert np.isclose(1.0, opt_params[0])
    assert zne_std is None
    assert params_cov is None
    assert np.isclose(zne_curve(0), 0.0)
    assert np.isclose(zne_curve(2), 2.0)


def test_full_output_keyword_cov_std():
    """Tests the full_output keyword in extrapolate method."""
    zne_limit = PolyFactory.extrapolate([1, 2, 3], [1, 4, 9], order=2)
    assert np.isclose(zne_limit, 0.0)
    (
        zne_limit,
        zne_std,
        opt_params,
        params_cov,
        zne_curve,
    ) = PolyFactory.extrapolate(
        [1, 2, 3], [1, 4, 9], order=2, full_output=True
    )

    assert len(opt_params) == 3
    assert np.isclose(zne_limit, 0.0)
    assert np.isclose(0.0, opt_params[1])
    assert np.isclose(1.0, opt_params[0])
    assert params_cov is None
    assert zne_std is None
    assert np.isclose(zne_curve(0), 0.0)
    assert np.isclose(zne_curve(2), 4.0)
    assert np.isclose(zne_curve(3), 9.0)


def test_params_cov_and_zne_std():
    """Tests the variance of the parametes and of the zne are produced."""
    x_values = [0, 0, 1]
    y_values = [-1, 1, 0]
    zne_limit = PolyFactory.extrapolate(x_values, y_values, order=1)
    assert np.isclose(zne_limit, 0.0, atol=1.0e-4)
    (
        zne_limit,
        zne_std,
        opt_params,
        params_cov,
        zne_curve,
    ) = PolyFactory.extrapolate(x_values, y_values, order=1, full_output=True)
    assert len(opt_params) == 2
    assert np.isclose(zne_limit, 0.0)
    assert np.isclose(0.0, opt_params[1])
    assert np.isclose(0.0, opt_params[0])
    assert np.allclose(params_cov, [[3.0, -1.0], [-1.0, 1.0]])
    assert np.isclose(zne_std, 1.0)
    assert np.isclose(zne_curve(0), 0.0)
    assert np.isclose(zne_curve(0.5), 0.0)


@mark.parametrize(
    "factory",
    [
        LinearFactory,
        RichardsonFactory,
        FakeNodesFactory,
        ExpBayesFactory,
    ]
)
def test_execute_with_zne_fit_fail(factory):
    """Tests errors are raised when asking for fitting parameters that can't
    be calculated.
    """
    with raises(ValueError, match="Data is either ill-defined or not enough"):
        factory([1.0, 2.0]).get_zero_noise_limit_error()
    with raises(ValueError, match="Data is either ill-defined or not enough"):
        factory([1.0, 2.0]).get_optimal_parameters()
    with raises(ValueError, match="Data is either ill-defined or not enough"):
        factory([1.0, 2.0]).get_parameters_covariance()
    with raises(ValueError, match="Data is either ill-defined or not enough"):
        factory([1.0, 2.0]).get_zero_noise_limit()
    with raises(ValueError, match="Data is either ill-defined or not enough"):
        factory([1.0, 2.0]).get_extrapolation_curve()


def test_get_methods_of_factories():
    """Tests the get methods of a factory"""
    x_values = [0, 0, 1]
    y_values = [-1, 1, 0]
    fac = LinearFactory(x_values)
    fac._instack = [
        {"scale_factor": 0},
        {"scale_factor": 0},
        {"scale_factor": 1},
    ]
    fac._outstack = y_values
    zne_reduce = fac.reduce()

    assert np.allclose(fac.get_expectation_values(), y_values)
    assert np.allclose(fac.get_extrapolation_curve()(0.0), zne_reduce)
    assert np.allclose(fac.get_optimal_parameters(), [0.0, 0.0])
    assert np.allclose(
        fac.get_parameters_covariance(), [[3.0, -1.0], [-1.0, 1.0]]
    )
    assert np.allclose(fac.get_scale_factors(), x_values)
    assert np.allclose(fac.get_zero_noise_limit(), zne_reduce)
    assert np.allclose(fac.get_zero_noise_limit_error(), 1.0)


def test__fakenodes_scale_factors_equally_spaced():
    """FakeNodesFactory should only accept equally spaced scale factors."""
    y_vals = [0.5, 1.0, 1.5]
    with raises(
        ValueError, match=r"The scale factors must be equally spaced."
    ):
        _ = FakeNodesFactory(X_VALS).extrapolate(X_VALS, y_vals)


def test_map_to_fakenodes():
    """Test the fake nodes map in FakeNodesFactory."""
    fac = FakeNodesFactory(UNIFORM_X)
    test_argument = 1.0
    assert np.isclose(fac._map_to_fake_nodes(1.0, 2.0, test_argument), 1.0,)

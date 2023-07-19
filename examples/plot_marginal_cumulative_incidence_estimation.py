"""
==================================================
Estimating marginal cumulative incidence functions
==================================================

This example demonstrates how to estimate the marginal cumulative incidence
using :class:`hazardous.GradientBoostingIncidence` and compares the results to
the Aalen-Johansen estimator and to the theoretical cumulated incidence curves
on synthetic data.

Here the data is generated by taking the minimum time of samples from three
competing Weibull distributions without any conditioning covariate. In this
case, the Aalen-Johansen estimator is expected to be unbiased, and this is
empirically confirmed by this example.

The :class:`hazardous.GradientBoostingIncidence` estimator on the other hand is
a predictive estimator that expects at least one conditioning covariate. In
this example, we use a dummy covariate that is constant for all samples. Here
we are not interested in the discrimination power of the estimator, but only in
its marginal calibration, that is, its ability to approximately recover an
unbiased estimate of the marginal cumulative incidence functions.
"""
# %%
import numpy as np
from scipy.stats import weibull_min
import pandas as pd
import matplotlib.pyplot as plt

from hazardous import GradientBoostingIncidence
from lifelines import AalenJohansenFitter

rng = np.random.default_rng(0)
n_samples = 5_000
base_scale = 1_000.0  # some arbitrary time unit
t_max = 3.0 * base_scale

distributions = [
    {"event_id": 1, "scale": 10 * base_scale, "shape": 0.5},
    {"event_id": 2, "scale": 3 * base_scale, "shape": 1},
    {"event_id": 3, "scale": 2 * base_scale, "shape": 5},
]
event_times = np.concatenate(
    [
        weibull_min.rvs(
            dist["shape"],
            scale=dist["scale"],
            size=n_samples,
            random_state=rng,
        ).reshape(-1, 1)
        for dist in distributions
    ],
    axis=1,
)
first_event_idx = np.argmin(event_times, axis=1)

y_uncensored = pd.DataFrame(
    dict(
        event=first_event_idx + 1,  # 0 is reserved as the censoring marker
        duration=event_times[np.arange(n_samples), first_event_idx],
    )
)
y_uncensored["event"].value_counts().sort_index()

# %%
#
# Add some uniform censoring with a large-enough upper bound to dilute the
# censoring. Lowering the upper bound will increase the censoring rate.
censoring_times = rng.uniform(
    low=0.0,
    high=1.2 * t_max,
    size=n_samples,
)
y_censored = pd.DataFrame(
    dict(
        event=np.where(
            censoring_times < y_uncensored["duration"], 0, y_uncensored["event"]
        ),
        duration=np.minimum(censoring_times, y_uncensored["duration"]),
    )
)
y_censored["event"].value_counts().sort_index()


# %%
#
# Since we know the true distribution of the data, we can compute the
# theoretical cumulative incidence functions (CIFs) by integrating the hazard
# functions. The CIFs are the probability of experiencing the event of interest
# before time t, given that the subject has not experienced any other event
# before time t.
#
# Note that true CIFs are independent of the censoring distribution. We can use
# them as reference to check that the estimators are unbiased by the censoring.


def weibull_hazard(t, shape=1.0, scale=1.0, **ignored_kwargs):
    # Plug an arbitrary finite hazard value at t==0 because fractional powers
    # of 0 are undefined.
    #
    # XXX: this does not seem correct but in practice it does make it possible
    # to integrate the hazard function into cumulative incidence functions in a
    # way that matches the Aalen Johansen estimator.
    with np.errstate(divide="ignore"):
        return np.where(t == 0, 0.0, (shape / scale) * (t / scale) ** (shape - 1.0))


def plot_cumulative_incidence_functions(distributions):
    _, axes = plt.subplots(figsize=(12, 4), ncols=len(distributions), sharey=True)

    # Non-informative covariate because scikit-learn estimators expect at least
    # one feature.
    X_dummy = np.zeros(shape=(n_samples, 1), dtype=np.float32)

    # Compute the estimate of the CIFs on a coarse grid.
    coarse_timegrid = np.linspace(0, t_max, num=100)

    # Compute the theoretical CIFs by integrating the hazard functions on a
    # fine-grained time grid. Note that integration errors can accumulate quite
    # quickly if the time grid is resolution too coarse, especially for the
    # Weibull distribution with shape < 1.
    fine_time_grid = np.linspace(0, t_max, num=100_000)
    dt = np.diff(fine_time_grid)[0]
    all_hazards = np.stack(
        [weibull_hazard(fine_time_grid, **dist) for dist in distributions],
        axis=0,
    )
    any_event_hazards = all_hazards.sum(axis=0)
    any_event_survival = np.exp(-(any_event_hazards.cumsum(axis=-1) * dt))

    censoring_fraction = (y_censored["event"] == 0).mean()
    plt.suptitle(
        "Cause-specific cumulative incidence functions"
        f" ({censoring_fraction:.2%} censoring)"
    )
    ajf = AalenJohansenFitter(calculate_variance=True, seed=0)
    for event_id, (ax, hazards_i) in enumerate(zip(axes, all_hazards), 1):
        theoretical_cif = (hazards_i * any_event_survival).cumsum(axis=-1) * dt
        ax.plot(
            fine_time_grid,
            theoretical_cif,
            linestyle="dashed",
            label="Theoretical incidence",
        ),
        ax.legend(loc="lower right")

        ajf.fit(y_censored["duration"], y_censored["event"], event_of_interest=event_id)
        ajf.plot(label="Aalen-Johansen", ax=ax)

        gb_incidence = GradientBoostingIncidence(
            learning_rate=0.03,
            n_iter=300,
            max_leaf_nodes=8,
            hard_zero_fraction=0.1,
            loss="ibs",
            event_of_interest=event_id,
            show_progressbar=False,
            random_state=0,
        )
        gb_incidence.fit(X_dummy, y_censored)
        cif_pred = gb_incidence.predict_cumulative_incidence(
            X_dummy[0:1], coarse_timegrid
        )[0]
        ax.plot(
            coarse_timegrid,
            cif_pred,
            label="GradientBoostingIncidence",
        )
        ax.legend(loc="lower right")
        ax.set(title=f"Event {event_id}")


plot_cumulative_incidence_functions(distributions)
# %%

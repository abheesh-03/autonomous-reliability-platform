"""Pure, dependency-free robust statistics -- no numpy/scipy, so the
whole `detectors/` package stays minimal-dependency per Phase 11B's own
guidance. Deliberately explainable (median + median absolute
deviation), never an opaque ML model, so a human can always recompute
a decision by hand from the reported observed/baseline values."""

import statistics

# Standard constant making MAD a consistent estimator of the standard
# deviation for normally-distributed data (Iglewicz & Hoaglin, 1993) --
# this is the well-known, standard robust z-score formula, not an
# invented constant.
MODIFIED_ZSCORE_CONSTANT = 0.6745


def median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def median_absolute_deviation(values: list[float], center: float) -> float:
    if not values:
        return 0.0
    deviations = [abs(v - center) for v in values]
    return statistics.median(deviations)


def modified_zscore(value: float, center: float, mad: float, *, mad_floor: float) -> float:
    """`mad_floor` is a deliberate, explicit, caller-supplied minimum
    MAD -- NEVER a silent division-by-zero guard invented ad hoc here.
    A perfectly flat baseline (MAD=0, e.g. a metric that is always
    exactly 0) would otherwise make ANY nonzero deviation register as
    an infinite z-score; using `mad_floor` instead keeps the score
    finite and the detector's own caller decides, explicitly, what
    that floor means for this specific metric's scale."""
    effective_mad = mad if mad > 0 else mad_floor
    return MODIFIED_ZSCORE_CONSTANT * (value - center) / effective_mad

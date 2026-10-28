"""Fixed exact-window calibration source; no dependency import or fit at import.

Future fitting requires the admitted real-dev authorization contract. Missing maps
produce null probabilities, never heuristic replacement confidence. No fitting was
performed to author this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import exp, fsum, isfinite
from typing import TYPE_CHECKING, Iterable
import warnings

if TYPE_CHECKING:
    from .tuning import FitAuthorization


FEATURE_ORDER = ("vis", "gapfree", "amp", "intv", "mean_g", "no_cycle")


def _features(values: tuple[float, ...]) -> tuple[float, ...] | None:
    """Validate immutable raw six-input vectors without normalization or fitting."""
    if not isinstance(values, tuple) or len(values) != len(FEATURE_ORDER):
        return None
    try:
        if any(isinstance(value, bool) or not isfinite(value) or not 0 <= value <= 1
               for value in values):
            return None
        if values[5] not in (0, 1):
            return None
        if values[5] == 1 and (values[2] != 0 or values[3] != 0):
            return None
        return tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError):
        return None


def fixed_sigmoid(coefficients: tuple[float, ...], intercept: float,
                  features: tuple[float, ...]) -> float | None:
    """Stable fixed-coefficient sigmoid; invalid/unavailable numerics stay null."""
    vector = _features(features)
    if vector is None or not isinstance(coefficients, tuple) or len(coefficients) != 6:
        return None
    try:
        if isinstance(intercept, bool) or not isfinite(intercept) or any(
            isinstance(value, bool) or not isfinite(value) for value in coefficients
        ):
            return None
        linear = fsum((intercept, *(weight * value for weight, value in zip(coefficients, vector))))
        if not isfinite(linear):
            return None
        if linear >= 0:
            probability = 1.0 / (1.0 + exp(-linear))
        else:
            odds = exp(linear)
            probability = odds / (1.0 + odds)
        return probability if isfinite(probability) and 0 <= probability <= 1 else None
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class FitRow:
    """Already-authorized supervised row, separate from inference input records.

    The guarded-label owner constructs target as filtered_count == truth. A row
    with hard/error/unscoreable status is excluded, never learned as a zero count.
    Identifiers are private audit keys, not public report labels.
    """

    person_id: str
    window_id: str
    trace_hash: str
    features: tuple[float, ...]
    target: bool
    status: str = "answered"
    hard_gate: bool = False
    scoreable: bool = True
    corpus: str = "real_dev"


@dataclass(frozen=True)
class MapArtifact:
    status: str
    reason: str | None
    coefficients: tuple[float, ...] | None
    intercept: float | None
    prior: float | None
    training_people: tuple[str, ...]
    support: int
    correct: int
    incorrect: int
    sklearn_version: str | None
    converged: bool
    feature_order: tuple[str, ...] = FEATURE_ORDER
    pins: tuple[tuple[str, str], ...] = ()
    excluded_support: int = 0
    allowed_people: tuple[str, ...] = ()

    def probability(self, features: tuple[float, ...]) -> float | None:
        if (self.status != "available" or not self.converged
                or self.feature_order != FEATURE_ORDER
                or self.coefficients is None or self.intercept is None):
            return None
        return fixed_sigmoid(self.coefficients, self.intercept, features)

    def as_dict(self) -> dict[str, object]:
        """JSON-compatible values, preserving null and truthful unavailable state."""
        return asdict(self)


def _people(values: Iterable[str]) -> tuple[str, ...]:
    people = tuple(values)
    if (not people or any(not isinstance(person, str) or not person or len(person) > 256
                          for person in people) or len(set(people)) != len(people)):
        raise ValueError("invalid_training_people")
    return tuple(sorted(people))


def _valid_pins(pins: tuple[tuple[str, str], ...]) -> bool:
    if not isinstance(pins, tuple):
        return False
    keys: set[str] = set()
    for pin in pins:
        if not isinstance(pin, tuple) or len(pin) != 2:
            return False
        key, value = pin
        if (not isinstance(key, str) or not key or len(key) > 128 or key in keys
                or not isinstance(value, str) or not value or len(value) > 256):
            return False
        keys.add(key)
    return True


def fit_map(rows: Iterable[FitRow], *, authorization: FitAuthorization,
            people: Iterable[str], pins: tuple[tuple[str, str], ...] = ()) -> MapArtifact:
    """Future fixed-map fit; authorization precedes optional dependency access.

    Seven-person LOPO training subsets and the final eight-person refit use the
    same approved real-dev roster. The caller must exclude the outer person's
    labels before constructing rows. This audit boundary is not hostile isolation.
    """
    from .tuning import FitAuthorization

    allowed = _people(people)
    if not isinstance(authorization, FitAuthorization):
        raise PermissionError("fit_authorization_required")
    authorization.require_people(allowed)
    if not _valid_pins(pins):
        raise ValueError("invalid_map_pins")
    materialized = tuple(rows)
    seen_windows: set[str] = set()
    seen_traces: set[str] = set()
    eligible: list[FitRow] = []
    excluded = 0
    for row in materialized:
        if not isinstance(row, FitRow):
            raise ValueError("invalid_training_row")
        if (row.person_id not in allowed or row.corpus != "real_dev"
                or not isinstance(row.window_id, str) or not row.window_id
                or len(row.window_id) > 256 or row.window_id in seen_windows
                or not isinstance(row.trace_hash, str) or len(row.trace_hash) != 64
                or any(c not in "0123456789abcdef" for c in row.trace_hash)
                or row.trace_hash in seen_traces
                or type(row.target) is not bool or type(row.hard_gate) is not bool
                or type(row.scoreable) is not bool
                or not isinstance(row.status, str)
                or row.status not in {"answered", "abstain", "error", "not_run",
                                      "calibration_unavailable", "unscoreable"}):
            raise ValueError("invalid_or_disjoint_training_row")
        seen_windows.add(row.window_id)
        seen_traces.add(row.trace_hash)
        if row.status != "answered" or row.hard_gate or not row.scoreable:
            excluded += 1
            continue
        if _features(row.features) is None:
            raise ValueError("invalid_training_features")
        eligible.append(row)

    support = len(eligible)
    correct = sum(row.target for row in eligible)
    incorrect = support - correct
    contributing_people = tuple(sorted({row.person_id for row in eligible}))
    prior = correct / support if support else None

    def unavailable(reason: str, version: str | None = None) -> MapArtifact:
        return MapArtifact(
            "calibration_unavailable", reason, None, None, prior,
            contributing_people, support, correct, incorrect, version, False,
            pins=pins, excluded_support=excluded, allowed_people=allowed,
        )

    if correct < 5 or incorrect < 5:
        return unavailable("insufficient_support")
    # This is the only optional dependency path. It is not run during Dirty Mode.
    try:
        import sklearn
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import LogisticRegression
    except Exception:
        # An installed but binary-incompatible optional dependency is unavailable
        # too; no environment repair or successful fit is inferred from it.
        return unavailable("dependency_unavailable")
    version = str(sklearn.__version__)
    try:
        model = LogisticRegression(C=1.0, penalty="l2", solver="lbfgs",
                                   max_iter=1000, tol=1e-6, random_state=17017)
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", ConvergenceWarning)
            model.fit([row.features for row in eligible], [row.target for row in eligible])
        if any(issubclass(item.category, ConvergenceWarning) for item in observed):
            return unavailable("nonconvergence", version)
        if any(int(iterations) >= 1000 for iterations in model.n_iter_):
            return unavailable("nonconvergence", version)
        if list(model.classes_) != [False, True]:
            return unavailable("invalid_class_order", version)
        coefficients = tuple(float(value) for value in model.coef_[0])
        intercept = float(model.intercept_[0])
        if (len(coefficients) != 6 or not isfinite(intercept)
                or any(not isfinite(value) for value in coefficients)):
            return unavailable("nonfinite_fit", version)
    except Exception:
        # Preserve unavailable status rather than exposing data-bearing library
        # exception text or inventing successful convergence/probability.
        return unavailable("fit_failed", version)
    return MapArtifact(
        "available", None, coefficients, intercept, prior, contributing_people,
        support, correct, incorrect, version, True, pins=pins,
        excluded_support=excluded, allowed_people=allowed,
    )

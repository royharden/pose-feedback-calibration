"""Original whole-person paired inference and closed pilot claim selection.

No draws, evaluation, dataset reads or claims execute at module import. The
public result contains aggregates only; private window/person keys stay local.
"""

from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from math import ceil, floor, isfinite
from random import Random
from typing import Iterable

from .metrics import EvalWindow, Metric, _auroc, validate_windows


@dataclass(frozen=True)
class Interval:
    estimate: float | None
    low: float | None
    high: float | None
    draws: int
    seed: int
    undefined_draws: int
    status: str
    reason: str | None
    conditional_low: float | None = None
    conditional_high: float | None = None


@dataclass(frozen=True)
class Comparison:
    corpus: str
    split: str
    edition: str
    people: int
    delta_fc: Metric
    delta_mae: Metric
    person_macro_fc: Metric
    person_macro_mae: Metric
    primary_fc: Interval
    primary_mae: Interval
    sensitivity_fc: Interval
    sensitivity_mae: Interval
    sign_flip_p: Metric
    same_subset_available: bool
    a2_available: bool = False
    a0_subset_mae: Metric = Metric(None, "not_measured")
    a2_subset_mae: Metric = Metric(None, "not_measured")
    complete_census: bool = False


@dataclass(frozen=True)
class ClaimGates:
    """Operator-supplied edition-bound receipts, not signature verification.

    All critical fields are required. True flags without named SHA commitments
    cannot support a claim; hashes themselves do not establish consent/rights.
    """

    edition: str
    admission: bool
    freeze: bool
    custody: bool
    qualified_oof: bool
    final_map: bool
    commitments: tuple[tuple[str, str], ...]
    a2h_calibration_evidence: bool = False
    scheduled_manifest_verified: bool = False
    schedule_commitment: str | None = None


@dataclass(frozen=True)
class Claim:
    category: str
    statement: str
    failed_gates: tuple[str, ...]
    lower_error: bool
    attribution: str


def _metric_ratio(numerator: int | float, denominator: int | float,
                  reason: str) -> Metric:
    if denominator <= 0:
        return Metric(None, reason, None, None)
    try:
        value = numerator / denominator
        if not isfinite(value):
            return Metric(None, "nonfinite_ratio", None, None)
        return Metric(value, None, numerator, denominator)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return Metric(None, "nonfinite_ratio", None, None)


def _answered(row: EvalWindow) -> bool:
    return (row.status == "answered" and not row.hard_gate
            and row.final_count is not None)


def _paired(a0rows: Iterable[EvalWindow], a2rows: Iterable[EvalWindow]) -> tuple[tuple[EvalWindow, EvalWindow], ...]:
    a0 = validate_windows(a0rows)
    a2 = validate_windows(a2rows)
    if not a0 or not a2:
        raise ValueError("paired_comparison_requires_scheduled_windows")
    if {row.arm for row in a0} != {"A0"} or {row.arm for row in a2} != {"A2"}:
        raise ValueError("paired_comparison_requires_A0_and_A2_no_substitution")
    first0, first2 = a0[0], a2[0]
    if (first0.corpus, first0.split, first0.edition) != (first2.corpus, first2.split, first2.edition):
        raise ValueError("paired_corpus_split_edition_mismatch")
    by_key = {row.key: row for row in a2}
    if len(a0) != len(a2) or {row.key for row in a0} != set(by_key):
        raise ValueError("paired_windows_must_not_be_dropped_or_added")
    pairs = []
    for baseline in a0:
        selective = by_key[baseline.key]
        if (baseline.person_id, baseline.window_id, baseline.positive,
            baseline.scoreable, baseline.truth_count, baseline.scheduled_seconds) != (
                selective.person_id, selective.window_id, selective.positive,
                selective.scoreable, selective.truth_count, selective.scheduled_seconds):
            raise ValueError("paired_support_or_truth_mismatch")
        pairs.append((baseline, selective))
    return tuple(pairs)


def _point(pairs: tuple[tuple[EvalWindow, EvalWindow], ...]) -> tuple[Metric, Metric, bool]:
    negatives = [(a0, a2) for a0, a2 in pairs if not a2.positive]
    # Never shrink scheduled exposure because source observations are missing.
    seconds = sum(a2.scheduled_seconds for _, a2 in negatives)
    emitted0 = sum(event.emitted for row, _ in negatives for event in row.events)
    emitted2 = sum(event.emitted for _, row in negatives for event in row.events)
    delta_fc = _metric_ratio((emitted0 - emitted2) * 60, seconds,
                             "scheduled_negative_exposure_unavailable")
    selected = [(a0, a2) for a0, a2 in pairs
                if a2.positive and a2.scoreable and _answered(a2)]
    if not selected:
        return delta_fc, Metric(None, "A2_answered_positive_subset_empty", None, None), False
    if any(not _answered(a0) for a0, _ in selected):
        return delta_fc, Metric(None, "A0_subset_nonanswer", None, None), False
    # The exact same selected windows form both means; no omitted baseline pair.
    error_difference = sum(abs(a2.final_count - a2.truth_count)
                           - abs(a0.final_count - a0.truth_count)
                           for a0, a2 in selected)
    return delta_fc, _metric_ratio(error_difference, len(selected), "subset_empty"), True


def _subset_maes(pairs: tuple[tuple[EvalWindow, EvalWindow], ...]) -> tuple[Metric, Metric]:
    """Actual A0/A2 means on precisely the A2-answered positive subset."""
    selected = [(a0, a2) for a0, a2 in pairs
                if a2.positive and a2.scoreable and _answered(a2)]
    reason = ("A2_answered_positive_subset_empty" if not selected
              else "A0_subset_nonanswer" if any(not _answered(a0) for a0, _ in selected)
              else None)
    if reason is not None:
        return Metric(None, reason), Metric(None, reason)
    baseline = sum(abs(a0.final_count - a0.truth_count) for a0, _ in selected)
    selective = sum(abs(a2.final_count - a2.truth_count) for _, a2 in selected)
    return (_metric_ratio(baseline, len(selected), "subset_empty"),
            _metric_ratio(selective, len(selected), "subset_empty"))


def _percentile(sorted_values: list[float], probability: float) -> float:
    """Linear interpolation at (n-1)*p, with endpoints retained (not a draw run)."""
    position = (len(sorted_values) - 1) * probability
    lower, upper = floor(position), ceil(position)
    weight = position - lower
    return (1 - weight) * sorted_values[lower] + weight * sorted_values[upper]


def _interval(values: list[float], *, estimate: Metric, draws: int, seed: int,
              undefined: int) -> Interval:
    ordered = sorted(values)
    low = _percentile(ordered, 0.025) if ordered else None
    high = _percentile(ordered, 0.975) if ordered else None
    if any(value is not None and not isfinite(value) for value in (low, high)):
        return Interval(estimate.value, None, None, draws, seed, undefined,
                        "unavailable", "nonfinite_interval")
    if undefined:
        return Interval(estimate.value, None, None, draws, seed, undefined,
                        "unavailable", "undefined_draws", low, high)
    if len(values) != draws or estimate.value is None:
        return Interval(estimate.value, None, None, draws, seed, undefined,
                        "unavailable", estimate.reason or "point_or_draw_support_unavailable", low, high)
    return Interval(estimate.value, low, high, draws, seed, 0, "available", None)


def _bootstrap(groups: tuple[tuple[tuple[EvalWindow, EvalWindow], ...], ...], *,
               point_fc: Metric, point_mae: Metric, draws: int, seed: int) -> tuple[Interval, Interval]:
    # Both statistics use the SAME people in each paired draw. A repeated person
    # contributes every one of their paired scheduled windows each time drawn.
    rng = Random(seed)
    fc_values: list[float] = []
    mae_values: list[float] = []
    undefined_fc = undefined_mae = 0
    for _ in range(draws):
        draw = tuple(pair for _ in range(len(groups))
                     for pair in groups[rng.randrange(len(groups))])
        fc, mae, _ = _point(draw)
        if fc.value is None:
            undefined_fc += 1
        else:
            fc_values.append(fc.value)
        if mae.value is None:
            undefined_mae += 1
        else:
            mae_values.append(mae.value)
    return (_interval(fc_values, estimate=point_fc, draws=draws, seed=seed, undefined=undefined_fc),
            _interval(mae_values, estimate=point_mae, draws=draws, seed=seed, undefined=undefined_mae))


def _fraction_fc(group: tuple[tuple[EvalWindow, EvalWindow], ...]) -> Fraction | None:
    negatives = [(a0, a2) for a0, a2 in group if not a2.positive]
    if not negatives:
        return None
    # validate_windows fixes each scored window to exactly 27s. Integer counts
    # permit exact rational sign-flip comparisons, without floating tie tolerance.
    emitted0 = sum(event.emitted for a0, _ in negatives for event in a0.events)
    emitted2 = sum(event.emitted for _, a2 in negatives for event in a2.events)
    return Fraction((emitted0 - emitted2) * 60, 27 * len(negatives))


def _sign_flip(groups: tuple[tuple[tuple[EvalWindow, EvalWindow], ...], ...]) -> Metric:
    if not groups or len(groups) > 16:
        return Metric(None, "exact_sign_flip_support_out_of_bounds", None, None)
    deltas = tuple(_fraction_fc(group) for group in groups)
    if any(delta is None for delta in deltas):
        return Metric(None, "person_negative_exposure_unavailable", None, None)
    observed = abs(sum(deltas, Fraction()))
    tail = 0
    for signs in product((-1, 1), repeat=len(deltas)):
        permuted = abs(sum((sign * delta for sign, delta in zip(signs, deltas)), Fraction()))
        tail += permuted >= observed
    return _metric_ratio(tail, 2 ** len(deltas), "sign_flip_support_unavailable")


def _macro(values: tuple[Metric, ...], reason: str) -> Metric:
    if not values or any(value.value is None for value in values):
        return Metric(None, reason, None, None)
    return _metric_ratio(sum(value.value for value in values), len(values), reason)


def paired_comparison(a0rows: Iterable[EvalWindow], a2rows: Iterable[EvalWindow]) -> Comparison:
    """Future measured A0/A2 comparison; fixed bootstrap runs occur only on call.

    This function is source-only during construction: no 10,000/2,000 draws have
    been executed. It must receive one complete scheduled corpus/edition/split.
    """
    pairs = _paired(a0rows, a2rows)
    people = tuple(sorted({a2.person_id for _, a2 in pairs}))
    groups = tuple(tuple(pair for pair in pairs if pair[1].person_id == person)
                   for person in people)
    point_fc, point_mae, subset_available = _point(pairs)
    person_points = tuple(_point(group) for group in groups)
    primary_fc, primary_mae = _bootstrap(groups, point_fc=point_fc, point_mae=point_mae,
                                         draws=10000, seed=1702)
    sensitivity_fc, sensitivity_mae = _bootstrap(groups, point_fc=point_fc, point_mae=point_mae,
                                                 draws=2000, seed=17017)
    first = pairs[0][0]
    a0_mae, a2_mae = _subset_maes(pairs)
    complete_census = (len(people) == 8 and len(pairs) == 96
                       and all(len(group) == 12 and sum(a2.positive for _, a2 in group) == 6 for group in groups))
    return Comparison(first.corpus, first.split, first.edition, len(people), point_fc, point_mae,
                      _macro(tuple(point[0] for point in person_points), "person_FC_unavailable"),
                      _macro(tuple(point[1] for point in person_points), "person_MAE_unavailable"),
                      primary_fc, primary_mae, sensitivity_fc, sensitivity_mae,
                      _sign_flip(groups), subset_available,
                      not any(row.status in {"not_run", "calibration_unavailable"}
                              for _, row in pairs), a0_mae, a2_mae, complete_census)


def _visibility_auc(rows: tuple[EvalWindow, ...]) -> Metric:
    eligible = [row for row in rows if row.scoreable and not row.hard_gate
                and row.status in {"answered", "abstain"} and row.filtered_count is not None]
    if not eligible or any(row.visibility_score is None for row in eligible):
        return Metric(None, "visibility_ranking_unavailable")
    # Same numeric helper and exact eligibility/orientation as metrics.summarize.
    return _auroc([1 - row.visibility_score for row in eligible],
                  [row.filtered_count != row.truth_count for row in eligible])


def visibility_wrong_auc_interval(rows: Iterable[EvalWindow]) -> Interval:
    """Descriptive A1 person-bootstrap percentile95 CI, 2,000 draws/seed17017.

    This routine method choice is an explicit construction assumption, not a
    newly claimed preregistered headline test. It reuses the metric's AUROC
    helper. Repeated whole-person windows are not revalidated as unique data.
    Any undefined draw blocks the main interval; optional conditional bounds
    remain descriptive. No draw was executed to author this source.
    """
    windows = validate_windows(rows)
    if {row.arm for row in windows} != {"A1"}:
        raise ValueError("visibility_wrong_auc_requires_A1")
    people = tuple(sorted({row.person_id for row in windows}))
    groups = tuple(tuple(row for row in windows if row.person_id == person) for person in people)
    point = _visibility_auc(windows)
    rng = Random(17017)
    values: list[float] = []
    undefined = 0
    for _ in range(2000):
        sample = tuple(row for _ in range(len(groups))
                       for row in groups[rng.randrange(len(groups))])
        metric = _visibility_auc(sample)
        if metric.value is None:
            undefined += 1
        else:
            values.append(metric.value)
    return _interval(values, estimate=point, draws=2000, seed=17017, undefined=undefined)


def _sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _finite(value: object) -> bool:
    try:
        return type(value) in (int, float) and isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def _valid_interval(interval: Interval, *, draws: int, seed: int,
                    estimate: float | None) -> bool:
    return (type(interval) is Interval and interval.status == "available"
            and interval.draws == draws and interval.seed == seed
            and interval.undefined_draws == 0 and _finite(estimate)
            and interval.estimate == estimate and _finite(interval.low)
            and _finite(interval.high) and interval.low <= interval.high)


def choose_claim(comparison: Comparison, coverage: Metric, *, gates: ClaimGates) -> Claim:
    """Closed wording from complete measured evidence; never called to fake data.

    Receipt commitments bind the claimed edition but remain a trusted operator
    audit convention, not cryptographic verification of independent humans.
    """
    if type(comparison) is not Comparison or type(coverage) is not Metric or type(gates) is not ClaimGates:
        raise ValueError("typed_claim_inputs_required")
    if (type(comparison.people) is not int or comparison.people < 1
            or type(comparison.same_subset_available) is not bool
            or type(comparison.a2_available) is not bool):
        raise ValueError("invalid_comparison_support")
    for metric in (comparison.delta_fc, comparison.delta_mae, comparison.sign_flip_p, coverage):
        if type(metric) is not Metric or (metric.value is not None and not _finite(metric.value)):
            raise ValueError("finite_or_null_claim_metrics_required")
    if any(metric.value is not None and not 0 <= metric.value <= 1
           for metric in (comparison.sign_flip_p, coverage)):
        raise ValueError("invalid_probability_or_coverage")
    if any(type(flag) is not bool for flag in (gates.admission, gates.freeze, gates.custody,
                                              gates.qualified_oof, gates.final_map,
                                              gates.a2h_calibration_evidence,
                                              gates.scheduled_manifest_verified)):
        raise ValueError("explicit_boolean_claim_gates_required")
    if type(gates.commitments) is not tuple or any(type(pin) is not tuple or len(pin) != 2
                                                  for pin in gates.commitments):
        raise ValueError("immutable_claim_commitments_required")
    pins = dict(gates.commitments)
    if len(pins) != len(gates.commitments):
        raise ValueError("duplicate_claim_commitment")
    prerequisites = {
        "real_held_out": comparison.corpus == "real" and comparison.split == "held_out",
        "edition_matches_receipts": gates.edition == comparison.edition,
        "at_least_eight_people": comparison.people >= 8,
        "complete_scheduled_census": comparison.complete_census is True,
        "scheduled_manifest_verified": (gates.scheduled_manifest_verified
                                         and _sha256(gates.schedule_commitment)
                                         and pins.get("schedule") == gates.schedule_commitment),
        "calibrated_A2_available": comparison.a2_available,
    }
    for name in ("admission", "freeze", "custody", "qualified_oof", "final_map"):
        prerequisites[name] = getattr(gates, name) and _sha256(pins.get(name))
    fc_intervals = (_valid_interval(comparison.primary_fc, draws=10000, seed=1702,
                                    estimate=comparison.delta_fc.value)
                    and _valid_interval(comparison.sensitivity_fc, draws=2000, seed=17017,
                                         estimate=comparison.delta_fc.value))
    mae_intervals = (_valid_interval(comparison.primary_mae, draws=10000, seed=1702,
                                     estimate=comparison.delta_mae.value)
                     and _valid_interval(comparison.sensitivity_mae, draws=2000, seed=17017,
                                          estimate=comparison.delta_mae.value))
    fc_conditions = {
        "positive_deltaFC": comparison.delta_fc.value is not None and comparison.delta_fc.value > 0,
        "sign_flip_p_below_0_05": comparison.sign_flip_p.value is not None
                                      and comparison.sign_flip_p.value < 0.05,
        "both_FC_intervals_available": fc_intervals,
        "both_FC_lower_bounds_positive": fc_intervals and comparison.primary_fc.low > 0
                                               and comparison.sensitivity_fc.low > 0,
    }
    counting_conditions = {
        "exercise_coverage_at_least_0_60": coverage.value is not None and coverage.value >= 0.60,
        "same_answered_subset_available": comparison.same_subset_available
                                             and comparison.delta_mae.value is not None,
        "both_MAE_intervals_available": mae_intervals,
        "both_MAE_upper_bounds_nonpositive": mae_intervals and comparison.primary_mae.high <= 0
                                                    and comparison.sensitivity_mae.high <= 0,
    }
    all_gates = {**prerequisites, **fc_conditions, **counting_conditions}
    failed = tuple(name for name, passed in all_gates.items() if not passed)
    lower_error = (not failed and comparison.primary_mae.high < 0
                   and comparison.sensitivity_mae.high < 0)
    attribution = ("whole_gated_counter_with_A2-H_calibration_ablation"
                   if gates.a2h_calibration_evidence and _sha256(pins.get("a2h_ablation"))
                   else "whole_gated_counter")
    if not failed:
        statement = "fewer displayed non-exercise false counts without worse matched-subset counting in this pilot"
        if lower_error:
            statement += "; lower matched-subset count error in this pilot"
        return Claim("useful_counter", statement, (), lower_error, attribution)
    if all(prerequisites.values()) and all(fc_conditions.values()):
        return Claim("false_counts_only",
                     "fewer displayed false counts but no demonstrated useful counting advantage in this pilot",
                     failed, False, attribution)
    if comparison.delta_fc.value is None and comparison.delta_mae.value is None:
        return Claim("unavailable", "no demonstrated advantage in this pilot; required comparison unavailable",
                     failed, False, "whole_gated_counter")
    return Claim("no_demonstrated_advantage", "no demonstrated advantage in this pilot",
                 failed, False, "whole_gated_counter")

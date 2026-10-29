"""Typed private evaluation rows and aggregate-only metrics construction.

No data acquisition, detector execution or statistical experiment occurs at
import. Missing support is explicit null, not zero or silently removed rows.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from posecount.schema import Event
from .matching import EventStamp, match_events, validate_stamps


STATUSES = ("answered", "abstain", "error", "unscoreable", "calibration_unavailable", "not_run")
ARMS = ("Z", "A0", "A0v", "A1", "A2-H", "A2")


@dataclass(frozen=True)
class Metric:
    value: float | None
    reason: str | None
    numerator: float | None = None
    denominator: float | None = None


@dataclass(frozen=True)
class EvalWindow:
    corpus: str
    split: str
    edition: str
    person_id: str
    window_id: str
    arm: str
    positive: bool
    scoreable: bool
    truth_count: int | None
    status: str
    final_count: int | None
    filtered_count: int | None
    events: tuple[Event, ...]
    hard_gate: bool = False
    p_exact: float | None = None
    prior: float | None = None
    visibility_score: float | None = None
    scheduled_seconds: float = 27.0
    truth_events: tuple[EventStamp, ...] | None = None
    failure_codes: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return self.person_id, self.window_id


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    support: int
    mean_probability: Metric
    observed_exact: Metric


@dataclass(frozen=True)
class RiskPoint:
    coverage: float
    risk: float
    support: int


@dataclass(frozen=True)
class ArmMetrics:
    corpus: str
    split: str
    edition: str
    arm: str
    support: tuple[tuple[str, int], ...]
    metrics: tuple[tuple[str, Metric], ...]
    calibration_bins: tuple[CalibrationBin, ...] = ()
    risk_points: tuple[RiskPoint, ...] = ()
    failure_counts: tuple[tuple[str, int], ...] = ()

    def metric(self, name: str) -> Metric:
        for key, value in self.metrics:
            if key == name:
                return value
        raise KeyError(name)

    def support_count(self, name: str) -> int:
        for key, value in self.support:
            if key == name:
                return value
        raise KeyError(name)


def _number(value: object) -> bool:
    try:
        return type(value) in (int, float) and isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _bounded(value: object) -> bool:
    return _number(value) and 0 <= value <= 1


def _count(value: object) -> bool:
    return type(value) is int and 0 <= value <= 7201


def _event(event: Event) -> None:
    if type(event) is not Event or not _count(event.event_id) or event.event_id == 0:
        raise ValueError("immutable_valid_event_required")
    times = (event.t_start_media, event.t_event_media, event.t_confirm_media, event.t_display)
    if not all(_number(value) for value in times):
        raise ValueError("invalid_event_time")
    if not (3 <= event.t_start_media <= event.t_event_media < 30
            and event.t_event_media <= event.t_confirm_media <= event.t_event_media + 1.5 + 1e-9):
        raise ValueError("event_outside_scored_or_confirmation_boundary")
    if (not isinstance(event.clock_scope, str) or not event.clock_scope
            or event.display_clock_domain not in {"media_seconds", "process_monotonic_ns"}):
        raise ValueError("invalid_event_clock")
    if event.display_clock_domain == "media_seconds" and event.t_display < event.t_confirm_media:
        raise ValueError("display_precedes_confirmation")
    if not _number(event.excursion_deg) or not 0 <= event.excursion_deg <= 180:
        raise ValueError("invalid_event_excursion")
    if not _number(event.duration_s) or event.duration_s < 0:
        raise ValueError("invalid_event_duration")
    if not all(_bounded(value) for value in (event.amp, event.intv, event.vis, event.gapfree, event.q)):
        raise ValueError("invalid_event_evidence")
    if any(type(value) is not bool for value in (event.cold_start, event.emitted, event.retained)):
        raise ValueError("invalid_event_flags")


def validate_windows(rows: Iterable[EvalWindow]) -> tuple[EvalWindow, ...]:
    windows = tuple(rows)
    if not windows or len(windows) > 600:
        raise ValueError("missing_or_oversized_window_support")
    for row in windows:
        if type(row) is not EvalWindow:
            raise ValueError("immutable_EvalWindow_required")
        if row.corpus not in {"synthetic", "real"} or row.split not in {"dev", "held_out", "regression"}:
            raise ValueError("invalid_corpus_or_split")
        if any(not isinstance(value, str) or not value or len(value) > 256
               for value in (row.edition, row.person_id, row.window_id)):
            raise ValueError("invalid_private_row_identifier")
        if row.arm not in ARMS or row.status not in STATUSES:
            raise ValueError("invalid_arm_or_status")
        if any(type(value) is not bool for value in (row.positive, row.scoreable, row.hard_gate)):
            raise ValueError("invalid_support_flag")
        if (row.scoreable and not _count(row.truth_count)) or (not row.scoreable and row.truth_count is not None):
            raise ValueError("invalid_or_missing_truth_count")
        if row.final_count is not None and not _count(row.final_count):
            raise ValueError("invalid_final_count")
        if row.filtered_count is not None and not _count(row.filtered_count):
            raise ValueError("invalid_filtered_count")
        if row.status == "answered":
            if row.final_count is None or row.filtered_count is None or row.hard_gate:
                raise ValueError("invalid_answered_window")
            if row.final_count != row.filtered_count:
                raise ValueError("final_filtered_count_mismatch")
        elif row.final_count is not None:
            raise ValueError("nonanswer_final_count_must_be_null")
        if not _number(row.scheduled_seconds) or row.scheduled_seconds != 27:
            raise ValueError("full_scheduled_exposure_required")
        if any(value is not None and not _bounded(value)
               for value in (row.p_exact, row.prior, row.visibility_score)):
            raise ValueError("invalid_score")
        if row.arm != "A2" and row.p_exact is not None:
            raise ValueError("probability_not_defined_for_arm")
        if row.arm == "A0v" and row.prior is not None:
            raise ValueError("prior_not_defined_for_visibility_rank")
        if type(row.events) is not tuple or len(row.events) > 7201:
            raise ValueError("immutable_bounded_events_required")
        for event in row.events:
            _event(event)
        if len({event.event_id for event in row.events}) != len(row.events):
            raise ValueError("duplicate_window_event_id")
        if row.truth_events is not None:
            if type(row.truth_events) is not tuple or not row.scoreable:
                raise ValueError("invalid_truth_event_support")
            stamps = validate_stamps(row.truth_events)
            if len(stamps) != row.truth_count or any(not 3 <= e.t_event_media < 30 for e in stamps):
                raise ValueError("truth_event_count_or_window_mismatch")
        if (type(row.failure_codes) is not tuple
                or len(set(row.failure_codes)) != len(row.failure_codes)
                or any(code not in {f"F{i}" for i in range(1, 19)} for code in row.failure_codes)):
            raise ValueError("invalid_failure_taxonomy")
    if len({row.key for row in windows}) != len(windows) or len({row.window_id for row in windows}) != len(windows):
        raise ValueError("duplicate_person_or_window_key")
    if len({(row.corpus, row.split, row.edition, row.arm) for row in windows}) != 1:
        raise ValueError("mixed_corpus_split_edition_or_arm")
    if windows[0].corpus == "real" and len(windows) > 192:
        raise ValueError("real_pilot_support_limit")
    return windows


def _ratio(numerator: float, denominator: float, reason: str = "zero_denominator") -> Metric:
    if denominator <= 0:
        return Metric(None, reason, numerator, denominator)
    value = numerator / denominator
    if not isfinite(value):
        return Metric(None, "nonfinite_result", numerator, denominator)
    return Metric(value, None, numerator, denominator)


def _mean(values: list[float], reason: str) -> Metric:
    return _ratio(sum(values), len(values), reason)


def _risk(scores: list[float], targets: list[bool]) -> tuple[Metric, tuple[RiskPoint, ...]]:
    if not scores:
        return Metric(None, "no_ranking_support"), ()
    groups: dict[float, list[bool]] = {}
    for score, target in zip(scores, targets):
        groups.setdefault(score, []).append(target)
    points = []
    kept = wrong = 0
    previous = area = 0.0
    for score in sorted(groups, reverse=True):
        group = groups[score]
        kept += len(group)
        wrong += sum(not target for target in group)
        coverage = kept / len(scores)
        risk = wrong / kept
        area += risk * (coverage - previous)
        previous = coverage
        points.append(RiskPoint(coverage, risk, kept))
    return Metric(area, None, None, len(scores)), tuple(points)


def _auroc(scores: list[float], positives: list[bool]) -> Metric:
    yes = [score for score, target in zip(scores, positives) if target]
    no = [score for score, target in zip(scores, positives) if not target]
    if not yes or not no:
        return Metric(None, "degenerate_wrong_count_classes", len(yes), len(no))
    wins = sum(1 if a > b else 0.5 if a == b else 0 for a in yes for b in no)
    return _ratio(wins, len(yes) * len(no))


def summarize(rows: Iterable[EvalWindow]) -> ArmMetrics:
    windows = validate_windows(rows)
    first = windows[0]
    positives = [row for row in windows if row.positive]
    negatives = [row for row in windows if not row.positive]
    scoreable = [row for row in windows if row.scoreable]
    scoreable_positive = [row for row in positives if row.scoreable]
    answered = [row for row in scoreable if row.status == "answered"]
    answered_positive = [row for row in scoreable_positive if row.status == "answered"]
    errors = [abs(row.final_count - row.truth_count) for row in answered_positive]
    correct = sum(error == 0 for error in errors)
    people = {row.person_id for row in windows}
    support = {
        "people": len(people), "scheduled": len(windows), "scoreable": len(scoreable),
        "scheduled_positive": len(positives), "scheduled_negative": len(negatives),
        "scoreable_positive": len(scoreable_positive),
        "scoreable_negative": sum(row.scoreable for row in negatives),
        "answered_scoreable": len(answered), "answered_positive": len(answered_positive),
        "unscoreable": len(windows) - len(scoreable),
        "hard_invalid": sum(row.hard_gate for row in windows),
        "truth_event_windows": sum(row.truth_events is not None for row in scoreable),
    }
    for status in STATUSES:
        support["status_" + status] = sum(row.status == status for row in windows)
    negative_minutes = sum(row.scheduled_seconds for row in negatives) / 60
    emitted = sum(event.emitted for row in negatives for event in row.events)
    retained = sum(event.emitted and event.retained and row.status == "answered"
                   for row in negatives for event in row.events)
    filtered = [row.filtered_count for row in negatives]
    metrics = {
        "exercise_coverage": _ratio(len(answered_positive), len(scoreable_positive), "no_scoreable_positives"),
        "overall_coverage": _ratio(len(answered), len(scoreable), "no_scoreable_windows"),
        "answered_mae": _mean(errors, "no_answered_scoreable_positives"),
        "answered_exact": _ratio(correct, len(errors), "no_answered_scoreable_positives"),
        "answered_obo": _ratio(sum(error <= 1 for error in errors), len(errors), "no_answered_scoreable_positives"),
        "end_to_end_exact": _ratio(correct, len(positives), "no_scheduled_positives"),
        "exposed_fc_per_minute": _ratio(emitted, negative_minutes, "no_scheduled_negative_exposure"),
        "retained_fc_per_minute": _ratio(retained, negative_minutes, "no_scheduled_negative_exposure"),
        "filtered_negative_count": Metric(None, "no_scheduled_negative_exposure") if not negatives
            else Metric(None, "filtered_count_unavailable") if any(v is None for v in filtered)
            else Metric(float(sum(filtered)), None, float(sum(filtered)), len(negatives)),
        "negative_scheduled_minutes": Metric(negative_minutes, None),
        "emitted_negative_events": Metric(float(emitted), None),
        "retained_negative_events": Metric(float(retained), None),
        "answered_positive_predicted_count_sum": _ratio(sum(row.final_count for row in answered_positive),
                                                        1 if answered_positive else 0, "no_answered_positives"),
        "answered_positive_truth_count_sum": _ratio(sum(row.truth_count for row in answered_positive),
                                                    1 if answered_positive else 0, "no_answered_positives"),
    }
    person_rates = []
    for person in people:
        subset = [row for row in negatives if row.person_id == person]
        if not subset:
            person_rates = []
            break
        person_rates.append(sum(event.emitted for row in subset for event in row.events)
                            / (sum(row.scheduled_seconds for row in subset) / 60))
    metrics["worst_person_fc_per_minute"] = (Metric(max(person_rates), None) if person_rates
                                              else Metric(None, "person_negative_exposure_unavailable"))

    # Event metrics use every displayed event on scoreable windows. Nonanswers
    # with no displayed event still leave all unmatched truth returns as FN.
    tp = fp = fn = 0
    event_matches = {
        row.key: match_events((EventStamp(str(event.event_id), event.t_event_media)
                               for event in row.events if event.emitted), row.truth_events)
        for row in scoreable if row.truth_events is not None
    }
    if any(row.truth_events is None for row in scoreable) or not scoreable:
        for name in ("event_precision", "event_recall", "event_f1", "event_tp", "event_fp", "event_fn"):
            metrics[name] = Metric(None, "truth_event_support_unavailable")
    else:
        for row in scoreable:
            match = event_matches[row.key]
            tp += len(match.matches)
            fp += match.fp
            fn += match.fn
        metrics.update(event_precision=_ratio(tp, tp + fp), event_recall=_ratio(tp, tp + fn),
                       event_f1=_ratio(2 * tp, 2 * tp + fp + fn),
                       event_tp=Metric(float(tp), None), event_fp=Metric(float(fp), None),
                       event_fn=Metric(float(fn), None))
    lags = [event.t_confirm_media - event.t_event_media for row in windows for event in row.events if event.emitted]
    metrics["mean_confirmation_lag_seconds"] = _mean(lags, "no_emitted_events")
    displayed = [event for row in windows for event in row.events if event.emitted]
    metrics["mean_media_display_lag_seconds"] = (
        _mean([event.t_display - event.t_event_media for event in displayed], "no_emitted_events")
        if all(event.display_clock_domain == "media_seconds" for event in displayed)
        else Metric(None, "display_media_clock_domains_differ"))

    eligible = [row for row in scoreable if not row.hard_gate
                and row.status in {"answered", "abstain"} and row.filtered_count is not None]
    targets = [row.filtered_count == row.truth_count for row in eligible]
    support["calibration_eligible"] = len(eligible)
    support["calibration_ineligible"] = len(windows) - len(eligible)
    support["risk_coverage_eligible"] = len(eligible)
    bins: tuple[CalibrationBin, ...] = ()
    curve: tuple[RiskPoint, ...] = ()
    for name in ("brier", "prior_brier", "ece", "aurc"):
        metrics[name] = Metric(None, "probability_not_defined_for_arm")
    metrics["visibility_wrong_auroc"] = Metric(None, "ranking_diagnostic_not_defined_for_arm")
    metrics["visibility_wrong_auroc_interval_low"] = Metric(None, "interval_not_computed")
    metrics["visibility_wrong_auroc_interval_high"] = Metric(None, "interval_not_computed")
    if first.arm == "A2":
        if not eligible or any(row.p_exact is None for row in eligible):
            reason = "no_calibration_eligible_rows" if not eligible else "probability_unavailable"
            for name in ("brier", "ece", "aurc"):
                metrics[name] = Metric(None, reason)
        else:
            probabilities = [row.p_exact for row in eligible]
            metrics["brier"] = _mean([(p - target) ** 2 for p, target in zip(probabilities, targets)], "no_calibration_support")
            metrics["aurc"], curve = _risk(probabilities, targets)
            bin_rows = []
            ece = 0.0
            for index in range(5):
                positions = [i for i, p in enumerate(probabilities) if min(4, int(p * 5)) == index]
                mean_p = _mean([probabilities[i] for i in positions], "empty_calibration_bin")
                exact = _mean([float(targets[i]) for i in positions], "empty_calibration_bin")
                if positions:
                    ece += len(positions) / len(eligible) * abs(mean_p.value - exact.value)
                bin_rows.append(CalibrationBin(index / 5, (index + 1) / 5, len(positions), mean_p, exact))
            bins = tuple(bin_rows)
            metrics["ece"] = Metric(ece, None, None, len(eligible))
        metrics["prior_brier"] = (Metric(None, "same_training_prior_unavailable")
                                  if not eligible or any(row.prior is None for row in eligible)
                                  else _mean([(row.prior - target) ** 2 for row, target in zip(eligible, targets)], "no_prior_support"))
    elif first.arm == "A0v":
        if not eligible or any(row.visibility_score is None for row in eligible):
            metrics["aurc"] = Metric(None, "visibility_ranking_unavailable")
        else:
            metrics["aurc"], curve = _risk([row.visibility_score for row in eligible], targets)
    elif first.arm == "A1":
        if not eligible or any(row.visibility_score is None for row in eligible):
            metrics["visibility_wrong_auroc"] = Metric(None, "visibility_ranking_unavailable")
        else:
            # Higher score predicts wrong count; visibility itself ranks support.
            metrics["visibility_wrong_auroc"] = _auroc([1 - row.visibility_score for row in eligible],
                                                       [not target for target in targets])
    confident = [row for row in answered if row.p_exact is not None and row.p_exact >= 0.9]
    support["confident_answers"] = len(confident)
    if first.arm == "A2" and any(row.p_exact is None for row in answered):
        metrics["confident_wrong"] = Metric(None, "answered_probability_unavailable")
        metrics["confident_wrong_rate"] = Metric(None, "answered_probability_unavailable")
    elif first.arm == "A2":
        wrong = sum(row.final_count != row.truth_count for row in confident)
        metrics["confident_wrong"] = Metric(float(wrong), None, float(wrong), len(confident))
        metrics["confident_wrong_rate"] = _ratio(wrong, len(confident), "no_confident_answers")
    else:
        metrics["confident_wrong"] = Metric(None, "probability_not_defined_for_arm")
        metrics["confident_wrong_rate"] = Metric(None, "probability_not_defined_for_arm")
    failures = tuple((f"F{i}", sum(f"F{i}" in row.failure_codes for row in windows)) for i in range(1, 19))
    support["failure_taxonomy_tagged_windows"] = sum(bool(row.failure_codes) for row in windows)
    known_failures = [row for row in windows if not row.scoreable
                      or row.status in {"abstain", "error", "unscoreable", "calibration_unavailable", "not_run"}
                      or (row.status == "answered" and row.final_count != row.truth_count)
                      or (row.key in event_matches and (event_matches[row.key].fp or event_matches[row.key].fn))]
    support["unclassified_failure_windows"] = sum(not row.failure_codes for row in known_failures)
    support["failure_event_truth_unavailable_windows"] = sum(row.truth_events is None for row in scoreable)
    metrics["failure_annotation_coverage"] = _ratio(sum(bool(row.failure_codes) for row in known_failures),
                                                   len(known_failures), "no_classifiable_failure_support")
    return ArmMetrics(first.corpus, first.split, first.edition, first.arm,
                      tuple(support.items()), tuple(metrics.items()), bins, curve, failures)

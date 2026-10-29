"""Frozen real-dev inputs, guarded label access and deterministic tuning source.

This is a trusted-operator audit boundary, not a Python sandbox. No fit runs at
module import. Synthetic rows cannot select a detector or operating point.
"""

from dataclasses import dataclass, replace as field_replace
from itertools import product
from math import isfinite
from typing import Callable, Iterable


def require_sha256(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("missing_or_invalid_commitment")


@dataclass(frozen=True)
class FitAuthorization:
    g0_commitment: str
    g1_commitment: str
    rights_commitment: str
    roster_commitment: str
    approved_by: str
    approved_at: str
    people: tuple[str, ...]
    status: str
    corpus: str

    def require_people(self, people: Iterable[str]) -> None:
        # Required external receipts are commitments, not inferred signed approval.
        if self.status != "approved" or self.corpus != "real_dev":
            raise PermissionError("real_dev_G0_G1_authorization_required")
        if (not isinstance(self.approved_by, str) or not self.approved_by.strip()
                or not isinstance(self.approved_at, str) or not self.approved_at.strip()):
            raise PermissionError("operator_approval_receipt_required")
        for value in (self.g0_commitment, self.g1_commitment,
                      self.rights_commitment, self.roster_commitment):
            require_sha256(value)
        if (type(self.people) is not tuple or len(self.people) != 8
                or any(not isinstance(p, str) or not p for p in self.people)
                or len(set(self.people)) != 8):
            raise PermissionError("exact_eight_dev_people_required")
        selected = tuple(people)
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(self.people):
            raise PermissionError("unapproved_training_people")


@dataclass(frozen=True)
class WindowInput:
    person_id: str
    window_id: str
    trace_hash: str
    positive: bool  # Preassigned capture class, not detector-selected movement.
    corpus: str = "real_dev"
    scored_seconds: float = 27.0

    @property
    def key(self) -> tuple[str, str, str]:
        return self.person_id, self.window_id, self.trace_hash


@dataclass(frozen=True)
class CountLabel:
    person_id: str
    window_id: str
    trace_hash: str
    truth: int | None
    scoreable: bool

    @property
    def key(self) -> tuple[str, str, str]:
        return self.person_id, self.window_id, self.trace_hash


@dataclass(frozen=True)
class CounterRow:
    window: WindowInput
    arm: str
    status: str
    filtered_count: int | None
    emitted_events: int
    hard_gate: bool
    features: tuple[float, ...] | None = None
    visibility_score: float | None = None

    @property
    def usable(self) -> bool:
        return self.status == "answered" and not self.hard_gate and self.filtered_count is not None


@dataclass(frozen=True)
class ParameterConfig:
    config_id: str
    arm: str
    values: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class LabelRead:
    key: tuple[str, str, str]
    stage: str
    allowed_people: tuple[str, ...]
    allowed: bool


class GuardedLabels:
    """Instrument every supervised read; scopes only narrow during upstream work."""

    def __init__(self, labels: Iterable[CountLabel], allowed_people: Iterable[str]) -> None:
        rows = tuple(labels)
        if any(type(row) is not CountLabel for row in rows):
            raise ValueError("immutable_CountLabel_required")
        self._labels = {row.key: row for row in rows}
        if len(self._labels) != len(rows):
            raise ValueError("duplicate_label_key")
        for row in rows:
            require_sha256(row.trace_hash)
            if type(row.scoreable) is not bool or (row.scoreable and (
                type(row.truth) is not int or row.truth < 0
            )) or (not row.scoreable and row.truth is not None):
                raise ValueError("invalid_label")
        self._allowed = frozenset(allowed_people)
        self._reads: list[LabelRead] = []
        self._seal: str | None = None

    @property
    def reads(self) -> tuple[LabelRead, ...]:
        return tuple(self._reads)

    def restrict(self, people: Iterable[str]) -> "GuardedLabels":
        selected = frozenset(people)
        if not selected or not selected <= self._allowed:
            raise PermissionError("label_scope_cannot_expand")
        child = object.__new__(GuardedLabels)
        child._labels = self._labels
        child._allowed = selected
        child._reads = self._reads
        child._seal = None
        return child

    def seal_oof(self, prediction_hash: str) -> None:
        require_sha256(prediction_hash)
        if self._seal is not None:
            raise PermissionError("OOF_predictions_already_sealed")
        self._seal = prediction_hash

    def read(self, window: WindowInput, *, stage: str) -> CountLabel:
        allowed = window.person_id in self._allowed and stage in {"tune", "fit", "threshold"}
        allowed = allowed and (stage != "threshold" or self._seal is not None)
        self._reads.append(LabelRead(window.key, stage, tuple(sorted(self._allowed)), allowed))
        if not allowed:
            raise PermissionError("label_access_denied")
        try:
            return self._labels[window.key]
        except KeyError as exc:
            raise ValueError("label_trace_or_window_mismatch") from exc


def validate_windows(windows: Iterable[WindowInput], authorization: FitAuthorization) -> tuple[WindowInput, ...]:
    rows = tuple(windows)
    if type(authorization) is not FitAuthorization:
        raise PermissionError("fit_authorization_required")
    if any(type(row) is not WindowInput or not isinstance(row.person_id, str)
           or not isinstance(row.window_id, str) for row in rows):
        raise ValueError("immutable_WindowInput_required")
    people = tuple(sorted({row.person_id for row in rows}))
    authorization.require_people(people)
    if len({row.key for row in rows}) != len(rows):
        raise ValueError("duplicate_window")
    if len({row.window_id for row in rows}) != len(rows) or len({row.trace_hash for row in rows}) != len(rows):
        raise ValueError("person_window_trace_overlap")
    for row in rows:
        require_sha256(row.trace_hash)
        if (not row.person_id or not row.window_id or row.corpus != "real_dev"
                or type(row.positive) is not bool or row.scored_seconds != 27):
            raise ValueError("invalid_or_non_real_dev_window")
    for person in people:
        scheduled = [row for row in rows if row.person_id == person]
        if len(scheduled) != 12 or sum(row.positive for row in scheduled) != 6:
            raise ValueError("complete_scheduled_person_windows_required")
    return rows


def validate_rows(windows: tuple[WindowInput, ...], rows: Iterable[CounterRow], arm: str) -> tuple[CounterRow, ...]:
    result = tuple(rows)
    if any(type(row) is not CounterRow or type(row.window) is not WindowInput for row in result):
        raise ValueError("immutable_CounterRow_required")
    expected = {window.key: window for window in windows}
    if len(result) != len(windows) or {row.window.key for row in result} != set(expected):
        raise ValueError("counter_callback_dropped_or_added_windows")
    if len({row.window.key for row in result}) != len(result):
        raise ValueError("duplicate_counter_row")
    for row in result:
        if row.window != expected[row.window.key] or row.arm != arm:
            raise ValueError("counter_callback_scope_mismatch")
        if row.status not in {"answered", "abstain", "error", "not_run", "calibration_unavailable"}:
            raise ValueError("unknown_counter_status")
        if type(row.hard_gate) is not bool or type(row.emitted_events) is not int or row.emitted_events < 0:
            raise ValueError("invalid_exposure_or_gate")
        if row.filtered_count is not None and (type(row.filtered_count) is not int or row.filtered_count < 0):
            raise ValueError("invalid_count")
        if row.status == "answered" and (row.filtered_count is None or row.hard_gate):
            raise ValueError("invalid_answered_row")
        if row.visibility_score is not None and (not isfinite(row.visibility_score) or not 0 <= row.visibility_score <= 1):
            raise ValueError("invalid_visibility_rank")
        # Validate ALL retained callback rows, including outer/nonanswer rows.
        # A frozen dataclass containing a mutable list would not seal its bytes.
        if row.features is not None:
            if (type(row.features) is not tuple or len(row.features) != 6
                    or any(type(v) not in (int, float) or not isfinite(v) or not 0 <= v <= 1
                           for v in row.features)
                    or row.features[5] not in (0, 1)
                    or (row.features[5] == 1 and (row.features[2] != 0 or row.features[3] != 0))):
                raise ValueError("invalid_or_mutable_feature_vector")
    return result


Evaluate = Callable[[ParameterConfig, tuple[WindowInput, ...]], Iterable[CounterRow]]


def parameter_grid(arm: str) -> tuple[ParameterConfig, ...]:
    if arm in {"A0", "A0v"}:
        grid = {"down_deg": (80, 95, 110), "up_deg": (145, 160, 170), "dwell_s": (0.1, 0.2)}
        if arm == "A0v":
            # Rank unrefused windows during counter tuning; OOF selection later
            # supplies the actual visibility policy, never a probability.
            grid["visibility_threshold"] = (0.0,)
    elif arm in {"A1", "A2-H"}:
        grid = {"tau_s": (0.1, 0.2), "margin_deg": (25, 40), "min_cycle_s": (0.6, 1.0)}
        if arm == "A2-H":
            grid.update(q_threshold=(0.25, 0.5, 0.75), movement_threshold=(0.4, 0.6))
    elif arm == "Z":
        return (ParameterConfig("Z", "Z", ()),)
    else:
        raise ValueError("no_counter_grid_for_arm")
    names = tuple(sorted(grid))
    return tuple(ParameterConfig(arm + ":" + ",".join(f"{k}={v:g}" for k, v in zip(names, values)),
                                 arm, tuple(zip(names, values)))
                 for values in product(*(grid[name] for name in names)))


@dataclass(frozen=True)
class TuningResult:
    status: str
    config: ParameterConfig | None
    loss: float | None
    exposed_fc_per_minute: float | None
    excluded_unscoreable_positives: int
    reason: str | None = None


def tune(arm: str, windows: Iterable[WindowInput], *, labels: GuardedLabels,
         authorization: FitAuthorization, evaluate: Evaluate) -> TuningResult:
    inputs = validate_windows(windows, authorization)
    people = tuple(sorted({w.person_id for w in inputs}))
    scoped = labels.restrict(people)
    gold = {w.key: scoped.read(w, stage="tune") for w in inputs}
    negatives = [w for w in inputs if not w.positive]
    excluded = sum(w.positive and not gold[w.key].scoreable for w in inputs)
    if not negatives:
        return TuningResult("unavailable", None, None, None, excluded, "negative_exposure_unavailable")
    candidates: list[tuple[float, float, str, ParameterConfig]] = []
    for config in parameter_grid(arm):
        rows = validate_rows(inputs, evaluate(config, inputs), arm)
        costs: dict[str, list[float]] = {person: [] for person in people}
        for row in rows:
            label = gold[row.window.key]
            if not row.window.positive or not label.scoreable:
                continue
            assert label.truth is not None
            cost = abs(row.filtered_count - label.truth) if row.usable else label.truth + 1
            costs[row.window.person_id].append(float(cost))
        if any(not values for values in costs.values()):
            return TuningResult("unavailable", None, None, None, excluded, "person_positive_support_unavailable")
        loss = sum(sum(values) / len(values) for values in costs.values()) / len(people)
        # Every emitted event counts, including later refusals/errors. Denominator
        # is all scheduled negative exposure, not source-observed minutes.
        exposed = sum(row.emitted_events for row in rows if not row.window.positive)
        rate = exposed / (sum(w.scored_seconds for w in negatives) / 60)
        candidates.append((loss, rate, config.config_id, config))
    loss, rate, _, selected = min(candidates, key=lambda value: value[:3])
    return TuningResult("available", selected, loss, rate, excluded)


@dataclass(frozen=True)
class SelectionRow:
    prediction: CounterRow
    baseline: CounterRow
    label: CountLabel
    probability: float | None


@dataclass(frozen=True)
class OperatingPoint:
    status: str
    threshold: float | None
    coverage: float | None
    wrong_rate: float | None
    mae: float | None
    baseline_mae: float | None
    exposed_fc_per_minute: float | None
    baseline_fc_per_minute: float | None
    reason: str | None = None
    comparison_status: str | None = None
    comparison_reason: str | None = None


def _point(rows: tuple[SelectionRow, ...], threshold: float, score: str) -> OperatingPoint:
    positives = [r for r in rows if r.prediction.window.positive and r.label.scoreable]
    negatives = [r for r in rows if not r.prediction.window.positive]
    if not positives or not negatives:
        return OperatingPoint("unavailable", threshold, None, None, None, None, None, None, "missing_support")
    answered = []
    for row in positives:
        value = row.probability if score == "probability" else row.prediction.visibility_score
        if row.prediction.usable and value is not None and value >= threshold:
            answered.append(row)
    coverage = len(answered) / len(positives)
    minutes = sum(r.prediction.window.scored_seconds for r in negatives) / 60
    rate = sum(r.prediction.emitted_events for r in negatives) / minutes
    base_rate = sum(r.baseline.emitted_events for r in negatives) / minutes
    if not answered:
        return OperatingPoint("unavailable", threshold, coverage, None, None, None, rate, base_rate, "no_answers")
    if any(not row.baseline.usable for row in answered):
        return OperatingPoint("unavailable", threshold, coverage, None, None, None, rate, base_rate, "A0_subset_nonanswer")
    errors = [abs(row.prediction.filtered_count - row.label.truth) for row in answered]
    baseline_errors = [abs(row.baseline.filtered_count - row.label.truth) for row in answered]
    return OperatingPoint("available", threshold, coverage, sum(e != 0 for e in errors) / len(errors),
                          sum(errors) / len(errors), sum(baseline_errors) / len(baseline_errors), rate, base_rate)


def _selection_rows(rows: Iterable[SelectionRow], authorization: FitAuthorization, score: str) -> tuple[SelectionRow, ...]:
    if score not in {"probability", "visibility"}:
        raise ValueError("unknown_selection_score")
    result = tuple(rows)
    windows = validate_windows((r.prediction.window for r in result), authorization)
    if {w.person_id for w in windows} != set(authorization.people):
        raise ValueError("full_eight_person_OOF_selection_required")
    arms = {r.prediction.arm for r in result}
    if len(arms) != 1 or (score == "probability" and arms != {"A2-H"}) or (
        score == "visibility" and not arms <= {"A0", "A0v"}
    ):
        raise ValueError("operating_point_arm_mismatch")
    validate_rows(windows, (r.prediction for r in result), next(iter(arms)))
    validate_rows(windows, (r.baseline for r in result), "A0")
    for row in result:
        if row.label.key != row.prediction.window.key:
            raise ValueError("selection_label_mismatch")
        if type(row.label.scoreable) is not bool or (row.label.scoreable and (
            type(row.label.truth) is not int or row.label.truth < 0
        )) or (not row.label.scoreable and row.label.truth is not None):
            raise ValueError("invalid_selection_label")
        if row.probability is not None and (not isfinite(row.probability) or not 0 <= row.probability <= 1):
            raise ValueError("invalid_probability")
    return result


def select_operating_point(rows: Iterable[SelectionRow], *, authorization: FitAuthorization,
                           score: str = "probability", maps_available: bool = True) -> OperatingPoint:
    inputs = _selection_rows(rows, authorization, score)
    missing = any(r.prediction.usable and (
        r.probability is None if score == "probability" else r.prediction.visibility_score is None
    ) for r in inputs)
    if (score == "probability" and not maps_available) or missing:
        return OperatingPoint("not_run", None, None, None, None, None, None, None, "score_or_calibration_unavailable")
    points = tuple(_point(inputs, k / 20, score) for k in range(21))
    qualified = [p for p in points if p.status == "available" and p.coverage >= 0.60
                 and p.wrong_rate <= 0.10 and p.mae <= p.baseline_mae
                 and p.exposed_fc_per_minute <= p.baseline_fc_per_minute]
    if not qualified:
        return field_replace(points[0], status="failed_dev_operating_point", reason="no_qualifying_threshold")
    return min(qualified, key=lambda p: (-p.coverage, p.mae, -p.threshold))


def nearest_visibility_policy(rows: Iterable[SelectionRow], target_coverage: float | None, *,
                              authorization: FitAuthorization) -> OperatingPoint:
    inputs = _selection_rows(rows, authorization, "visibility")
    if target_coverage is None:
        return OperatingPoint("not_run", None, None, None, None, None, None, None, "A2_dev_coverage_unavailable")
    if not isfinite(target_coverage) or not 0 <= target_coverage <= 1:
        raise ValueError("invalid_target_coverage")
    if any(r.prediction.usable and r.prediction.visibility_score is None for r in inputs):
        return OperatingPoint("not_run", None, None, None, None, None, None, None, "visibility_score_unavailable")
    points = [_point(inputs, k / 20, "visibility") for k in range(21)]
    usable = [p for p in points if p.coverage is not None]
    if not usable:
        return OperatingPoint("not_run", None, None, None, None, None, None, None, "missing_support")
    selected = min(usable, key=lambda p: (abs(p.coverage - target_coverage), -p.coverage, p.threshold))
    return field_replace(selected, status="nearest_dev_coverage",
                         reason=selected.reason or "descriptive_policy_not_qualification",
                         comparison_status=selected.status, comparison_reason=selected.reason)

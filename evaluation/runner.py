"""Permission/schedule/seal boundary for future evaluator-only callback work.

No detector, model, private-data loader or not-built custody module is imported.
Rendering accepts the final sealed aggregate bundle and never invokes this runner.
"""

from dataclasses import asdict, dataclass
from typing import Callable, Iterable

from posecount.report import ResultBundle
from posecount.schema import Prediction
from posecount.tuning import CountLabel, WindowInput, require_sha256
from .lopo import digest
from .matching import EventStamp
from .metrics import ARMS, EvalWindow, summarize, validate_windows
from .results_writer import build_bundle, with_auc_interval
from .stats import Claim, ClaimGates, choose_claim, paired_comparison, visibility_wrong_auc_interval


@dataclass(frozen=True)
class ScheduledWindow:
    person_id: str
    window_id: str
    positive: bool
    scored_seconds: float = 27.0

    @property
    def key(self) -> tuple[str, str]:
        return self.person_id, self.window_id


@dataclass(frozen=True)
class FrozenSchedule:
    corpus: str
    split: str
    edition: str
    windows: tuple[ScheduledWindow, ...]
    commitment: str

    def validate(self) -> None:
        if (self.corpus not in {"synthetic", "real"} or self.split not in {"dev", "held_out", "regression"}
                or not isinstance(self.edition, str) or not self.edition or type(self.windows) is not tuple
                or not 0 < len(self.windows) <= 600):
            raise ValueError("invalid_frozen_schedule")
        require_sha256(self.commitment)
        if any(type(w) is not ScheduledWindow or not isinstance(w.person_id, str) or not w.person_id
               or not isinstance(w.window_id, str) or not w.window_id or type(w.positive) is not bool
               or w.scored_seconds != 27 for w in self.windows):
            raise ValueError("invalid_scheduled_window")
        if len({w.key for w in self.windows}) != len(self.windows):
            raise ValueError("duplicate_schedule_window")
        if digest([asdict(w) for w in self.windows]) != self.commitment:
            raise ValueError("scheduled_manifest_commitment_mismatch")
        if self.corpus == "real":
            people = {w.person_id for w in self.windows}
            if len(people) != 8 or len(self.windows) != 96:
                raise ValueError("complete_real_split_requires_eight_people_96_windows")
            for person in people:
                group = [w for w in self.windows if w.person_id == person]
                if len(group) != 12 or sum(w.positive for w in group) != 6:
                    raise ValueError("complete_person_positive_negative_schedule_required")


@dataclass(frozen=True)
class EvaluationPermission:
    status: str
    corpus: str
    split: str
    edition: str
    operator_receipt: str
    admission_receipt: str
    rights_receipt: str
    custody_receipt: str
    prediction_seal: str
    gold_seal: str
    independent_operator: bool

    def require(self, schedule: FrozenSchedule) -> None:
        if type(schedule) is not FrozenSchedule:
            raise PermissionError("frozen_schedule_required")
        schedule.validate()
        if self.status != "approved" or (self.corpus, self.split, self.edition) != (
            schedule.corpus, schedule.split, schedule.edition
        ):
            raise PermissionError("evaluation_permission_required")
        for value in (self.operator_receipt, self.admission_receipt, self.rights_receipt,
                      self.custody_receipt, self.prediction_seal, self.gold_seal):
            require_sha256(value)
        if type(self.independent_operator) is not bool or (
            self.split in {"held_out", "regression"} and not self.independent_operator
        ):
            raise PermissionError("independent_custodian_receipt_required")
        # External trusted operator verifies actual receipts and consumed all-arm
        # reservation BEFORE providing the callback. Hashes cannot attest consent.


def from_prediction(window: WindowInput, prediction: Prediction, label: CountLabel, *,
                    corpus: str, split: str, edition: str, expected_config_hash: str,
                    probability: float | None = None, prior: float | None = None,
                    visibility_score: float | None = None,
                    truth_events: tuple[EventStamp, ...] | None = None,
                    failure_codes: tuple[str, ...] = ()) -> EvalWindow:
    """Explicit trusted scorer join; no label accessor/geometry/counter copy.

    Future custody owner supplies already-authorized gold only AFTER predictions
    are sealed. P6 supplies probability/prior separately; current counter A2 map
    activation is an INT reconciliation item, not invented in this adapter.
    """
    if (type(window) is not WindowInput or type(prediction) is not Prediction or type(label) is not CountLabel
            or not isinstance(prediction.window_id, str) or not prediction.window_id.strip()
            or window.key != label.key or prediction.window_id != window.window_id):
        raise ValueError("prediction_label_window_identity_mismatch")
    for commitment in (window.trace_hash, prediction.trace_hash, prediction.config_hash, expected_config_hash):
        require_sha256(commitment)
    if prediction.trace_hash != window.trace_hash or prediction.config_hash != expected_config_hash:
        raise ValueError("prediction_trace_or_frozen_config_mismatch")
    row = EvalWindow(corpus, split, edition, window.person_id, window.window_id,
                     prediction.arm, window.positive, label.scoreable, label.truth,
                     prediction.status, prediction.final_count, prediction.filtered_count,
                     prediction.events, prediction.hard_gate, probability, prior,
                     visibility_score, window.scored_seconds, truth_events, failure_codes)
    validate_windows((row,))
    return row


def prediction_seal(rows: Iterable[EvalWindow]) -> str:
    """Canonical all-arm PREDICTION commitment, explicitly excludes gold fields."""
    values = []
    for row in sorted(rows, key=lambda r: (r.arm, r.person_id, r.window_id)):
        values.append({name: asdict(row)[name] for name in (
            "corpus", "split", "edition", "person_id", "window_id", "arm", "positive",
            "status", "final_count", "filtered_count", "events", "hard_gate", "p_exact",
            "prior", "visibility_score", "scheduled_seconds",
        )})
    return digest(values)


def gold_seal(rows: tuple[EvalWindow, ...]) -> str:
    # Caller first verifies all arms share these exact gold values.
    selected = [row for row in rows if row.arm == "A0"]
    return digest([{"key": row.key, "truth_count": row.truth_count, "scoreable": row.scoreable,
                    "truth_events": None if row.truth_events is None else [asdict(event) for event in row.truth_events]}
                   for row in sorted(selected, key=lambda r: r.key)])


def run_evaluation(callback: Callable[[], Iterable[EvalWindow]], *, schedule: FrozenSchedule,
                   permission: EvaluationPermission, gates: ClaimGates | None = None) -> ResultBundle:
    """Future measured path only. Caller supplies no missing-window shortcuts."""
    if type(permission) is not EvaluationPermission:
        raise PermissionError("typed_evaluation_permission_required")
    permission.require(schedule)  # BEFORE any callback/data access.
    rows = tuple(callback())
    if any(type(row) is not EvalWindow for row in rows):
        raise ValueError("immutable_evaluation_rows_required")
    groups = {arm: validate_windows(row for row in rows if row.arm == arm) for arm in ARMS}
    if len(rows) != len(schedule.windows) * len(ARMS):
        raise ValueError("complete_all_arm_schedule_required")
    by_schedule = {w.key: w for w in schedule.windows}
    baseline = {row.key: row for row in groups["A0"]}
    for arm in ARMS:
        if len(groups[arm]) != len(by_schedule) or {row.key for row in groups[arm]} != set(by_schedule):
            raise ValueError("scheduled_windows_dropped_or_added")
        for row in groups[arm]:
            scheduled = by_schedule[row.key]
            other = baseline[row.key]
            if (row.corpus, row.split, row.edition, row.positive, row.scheduled_seconds) != (
                schedule.corpus, schedule.split, schedule.edition, scheduled.positive, scheduled.scored_seconds
            ) or (row.scoreable, row.truth_count, row.truth_events) != (
                other.scoreable, other.truth_count, other.truth_events
            ):
                raise ValueError("arm_schedule_or_gold_mismatch")
    actual_seal = prediction_seal(rows)
    if actual_seal != permission.prediction_seal or gold_seal(rows) != permission.gold_seal:
        raise PermissionError("sealed_predictions_or_gold_mismatch")
    aggregates = []
    for arm in ARMS:
        aggregate = summarize(groups[arm])
        if arm == "A1":
            aggregate = with_auc_interval(aggregate, visibility_wrong_auc_interval(groups[arm]))
        aggregates.append(aggregate)
    comparison = paired_comparison(groups["A0"], groups["A2"])
    if gates is None:
        claim = Claim("unavailable", "required claim receipts unavailable",
                      ("admission", "freeze", "custody", "qualified_oof", "final_map"), False, "whole_gated_counter")
    else:
        if (type(gates) is not ClaimGates or not gates.scheduled_manifest_verified
                or gates.schedule_commitment != schedule.commitment):
            raise PermissionError("claim_schedule_receipt_mismatch")
        claim = choose_claim(comparison, next(a for a in aggregates if a.arm == "A2").metric("exercise_coverage"), gates=gates)
    return build_bundle(aggregates, comparison=comparison, claim=claim, source_seal=actual_seal)

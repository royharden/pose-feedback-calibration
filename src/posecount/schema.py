"""Immutable scalar seam for a future aspect-corrected landmark adapter."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class Reason(StrEnum):
    INVALID_INPUT = "invalid_input"
    NONMONOTONIC_TIME = "nonmonotonic_time"
    INPUT_LIMIT = "input_limit"
    SOURCE_GAP = "source_gap"
    MISSING_JOINTS = "missing_joints"
    POSE_COUNT = "pose_count"
    STANDING_REFERENCE = "standing_reference_unavailable"
    NO_SCORED_FRAMES = "no_scored_frames"
    SHORT_CYCLE = "short_cycle"
    CONFIRMATION_EXPIRED = "confirmation_expired"
    UNCONFIRMED_RETURN = "unconfirmed_return"
    PARTIAL_CYCLE = "partial_cycle"
    INCOMPLETE_WINDOW = "incomplete_window"
    SOURCE_ERROR = "source_error"
    REQUIRED_VISIBILITY = "required_joint_visibility"
    SECOND_PERSON = "second_person"
    MOVEMENT_INPUTS = "movement_inputs_missing"
    MOVEMENT_LOW = "movement_below_threshold"
    INVALID_REFERENCE = "invalid_reference_scale"
    QUALITY_LOW = "quality_below_threshold"
    EXPECTED_FRAMES = "invalid_expected_frames"
    CALIBRATION_UNAVAILABLE = "calibration_unavailable"
    POLICY_UNAVAILABLE = "visibility_policy_unavailable"
    VISIBILITY_POLICY = "visibility_below_threshold"


def reason_message(reason: Reason) -> str:
    """Only closed enum values enter public gate messages."""
    return f"not counting: {Reason(reason).value}"


@dataclass(frozen=True)
class FrameEvidence:
    """Optional scalar producer metadata; not a second FrameBatch schema.

    Hip coordinates use one fixed valid warm-up torso scale. Slot IDs refer to a
    fixed nominal media grid anchored at zero; missing/late reports are causal.
    """

    elbow_left: float
    elbow_right: float
    hip_x: float
    hip_y: float
    torso_scale: float
    nominal_interval_s: float
    slot_index: int
    missing_slots: tuple[int, ...] = ()
    late_slots: tuple[int, ...] = ()

    def validate(self, t_media: float) -> None:
        if not all(isfinite(v) for v in (self.elbow_left, self.elbow_right,
                                         self.hip_x, self.hip_y, self.torso_scale,
                                         self.nominal_interval_s)):
            raise ValueError(Reason.INVALID_INPUT)
        if self.torso_scale <= 0:
            raise ValueError(Reason.INVALID_REFERENCE)
        if not 0 <= self.elbow_left <= 180 or not 0 <= self.elbow_right <= 180:
            raise ValueError(Reason.INVALID_INPUT)
        if not 1 / 120 <= self.nominal_interval_s <= 0.5:
            raise ValueError(Reason.EXPECTED_FRAMES)
        if type(self.slot_index) is not int or not 0 <= self.slot_index <= 7200:
            raise ValueError(Reason.EXPECTED_FRAMES)
        if abs(self.slot_index * self.nominal_interval_s - t_media) > self.nominal_interval_s / 2 + 1e-9:
            raise ValueError(Reason.EXPECTED_FRAMES)
        if not isinstance(self.missing_slots, tuple) or not isinstance(self.late_slots, tuple):
            raise ValueError(Reason.INVALID_INPUT)
        if len(self.missing_slots) + len(self.late_slots) > 14402:
            raise ValueError(Reason.INPUT_LIMIT)
        if any(type(s) is not int or not 0 <= s <= self.slot_index
               for s in (*self.missing_slots, *self.late_slots)):
            raise ValueError(Reason.EXPECTED_FRAMES)


@dataclass(frozen=True)
class AngleFrame:
    t_media: float
    theta: float | None
    visibility: tuple[float, float, float] = (1.0, 1.0, 1.0)
    poses: int = 1
    evidence: FrameEvidence | None = None

    def validate(self) -> None:
        if not isfinite(self.t_media) or self.t_media < 0:
            raise ValueError(Reason.INVALID_INPUT)
        if self.theta is not None and (not isfinite(self.theta) or not 0 <= self.theta <= 180):
            raise ValueError(Reason.INVALID_INPUT)
        if len(self.visibility) != 3 or any(
            not isfinite(v) or not 0 <= v <= 1 for v in self.visibility
        ):
            raise ValueError(Reason.INVALID_INPUT)
        if type(self.poses) is not int or not 0 <= self.poses <= 2:
            raise ValueError(Reason.INVALID_INPUT)
        if self.evidence is not None:
            if not isinstance(self.evidence, FrameEvidence):
                raise ValueError(Reason.INVALID_INPUT)
            self.evidence.validate(self.t_media)


@dataclass(frozen=True)
class CounterConfig:
    tau_s: float = 0.1
    margin_deg: float = 40.0
    min_cycle_s: float = 0.6
    down_deg: float = 95.0
    up_deg: float = 160.0
    dwell_s: float = 0.1
    q_threshold: float = 0.5
    movement_threshold: float = 0.4
    visibility_threshold: float | None = None

    def __post_init__(self) -> None:
        if self.tau_s not in (0.1, 0.2):
            raise ValueError("tau_s must be 0.1 or 0.2")
        if self.margin_deg not in (25.0, 40.0):
            raise ValueError("margin_deg must be 25 or 40")
        if self.min_cycle_s not in (0.6, 1.0):
            raise ValueError("min_cycle_s must be 0.6 or 1.0")
        if self.down_deg not in (80, 95, 110) or self.up_deg not in (145, 160, 170):
            raise ValueError("invalid A0 hysteresis grid")
        if self.dwell_s not in (0.1, 0.2):
            raise ValueError("invalid A0 dwell grid")
        if self.q_threshold not in (0.25, 0.5, 0.75):
            raise ValueError("invalid quality threshold grid")
        if self.movement_threshold not in (0.4, 0.6):
            raise ValueError("invalid movement threshold grid")
        if self.visibility_threshold is not None and (
            not isfinite(self.visibility_threshold) or not 0 <= self.visibility_threshold <= 1
        ):
            raise ValueError("visibility policy must be an injected bounded ranking threshold")


@dataclass(frozen=True)
class Event:
    event_id: int
    t_start_media: float
    t_event_media: float
    t_confirm_media: float
    t_display: float
    excursion_deg: float
    duration_s: float
    amp: float
    intv: float
    cold_start: bool
    emitted: bool = True
    retained: bool = True
    display_clock_domain: str = "media_seconds"
    clock_scope: str = "input_stream"
    vis: float = 1.0
    gapfree: float = 1.0
    q: float = 1.0


@dataclass(frozen=True)
class Prediction:
    arm: str
    status: str
    candidate_count: int
    filtered_count: int
    final_count: int | None
    events: tuple[Event, ...]
    reasons: tuple[Reason, ...]
    p_exact: None = None
    window_id: str = ""
    hard_gate: bool = False
    config_hash: str | None = None
    trace_hash: str | None = None
    features: tuple[float, ...] | None = None

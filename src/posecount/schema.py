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


@dataclass(frozen=True)
class AngleFrame:
    t_media: float
    theta: float | None
    visibility: tuple[float, float, float] = (1.0, 1.0, 1.0)
    poses: int = 1

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


@dataclass(frozen=True)
class CounterConfig:
    tau_s: float = 0.1
    margin_deg: float = 40.0
    min_cycle_s: float = 0.6

    def __post_init__(self) -> None:
        if self.tau_s not in (0.1, 0.2):
            raise ValueError("tau_s must be 0.1 or 0.2")
        if self.margin_deg not in (25.0, 40.0):
            raise ValueError("margin_deg must be 25 or 40")
        if self.min_cycle_s not in (0.6, 1.0):
            raise ValueError("min_cycle_s must be 0.6 or 1.0")


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

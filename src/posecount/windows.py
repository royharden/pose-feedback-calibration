"""Fixed scoring exposure and explicit nominal missing/late slot accounting."""
from dataclasses import dataclass
from math import floor
from .landmarks import SourceError, finite

@dataclass(frozen=True)
class Window:
    start: float = 3.0
    end: float = 30.0
    source_end: float = 60.0

    def __post_init__(self) -> None:
        if not all(finite(v) for v in (self.start, self.end, self.source_end)) or not 0 <= self.start < self.end <= self.source_end <= 60:
            raise SourceError("invalid_window")

    def phase(self, t_media: float) -> str:
        if not finite(t_media) or not 0 <= t_media <= self.source_end:
            raise SourceError("invalid_media_time")
        return "warmup" if t_media < self.start else "scored" if t_media < self.end else "tail"

    def eligible_return(self, start_media: float, return_media: float) -> bool:
        if not finite(start_media) or not finite(return_media) or return_media < start_media:
            raise SourceError("invalid_event_time")
        return self.start <= start_media <= return_media < self.end

def nominal_slot(t_media: float, fps: float) -> int:
    if not finite(t_media) or not 0 <= t_media <= 60 or not finite(fps) or not 0 < fps <= 120:
        raise SourceError("invalid_slot_time")
    return floor(t_media * fps + 1e-9)

def missing_between(previous: float | None, current: float, fps: float) -> tuple[int, ...]:
    now = nominal_slot(current, fps)
    if previous is None:
        return tuple(range(now))
    if current <= previous:
        raise SourceError("nonmonotonic_media_time")
    return tuple(range(nominal_slot(previous, fps) + 1, now))

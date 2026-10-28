"""Immutable source contracts; no device/runtime imports or label fields."""
from dataclasses import dataclass
from math import floor, isfinite
from typing import Protocol

LANDMARK_NAMES = (
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner",
    "right_eye", "right_eye_outer", "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist",
    "right_wrist", "left_pinky", "right_pinky", "left_index", "right_index",
    "left_thumb", "right_thumb", "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel", "left_foot_index", "right_foot_index",
)

class SourceError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

def finite(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False

def identifier(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 256 and all(ord(c) >= 32 for c in value)

@dataclass(frozen=True)
class Landmark:
    name: str
    x: float
    y: float
    z: float
    visibility: float
    presence: float | None = None

    def __post_init__(self) -> None:
        if self.name not in LANDMARK_NAMES or not all(finite(v) for v in (self.x, self.y, self.z)):
            raise SourceError("invalid_landmark")
        if not finite(self.visibility) or not 0 <= self.visibility <= 1:
            raise SourceError("invalid_visibility")
        if self.presence is not None and (not finite(self.presence) or not 0 <= self.presence <= 1):
            raise SourceError("invalid_presence")

Pose = tuple[Landmark, ...]

@dataclass(frozen=True)
class FrameBatch:
    """Slot declarations cover observed time; unavailable frames declare their own slot."""

    t_media: float
    poses: tuple[Pose, ...]
    width: int
    height: int
    pixel_aspect: float = 1.0
    nominal_fps: float = 30.0
    source_id: str = "fixture"
    source_kind: str = "synthetic"
    status: str = "ok"
    missing_slots: tuple[int, ...] = ()
    late_slots: tuple[int, ...] = ()
    receive_ns: int | None = None
    clock_domain: str | None = None
    clock_scope: str | None = None
    model_id: str | None = None
    runtime_id: str | None = None

    def __post_init__(self) -> None:
        if not finite(self.t_media) or not 0 <= self.t_media <= 60:
            raise SourceError("invalid_media_time")
        if type(self.width) is not int or type(self.height) is not int or not (0 < self.width <= 16384 and 0 < self.height <= 16384):
            raise SourceError("invalid_dimensions")
        if not finite(self.pixel_aspect) or not 0 < self.pixel_aspect <= 100:
            raise SourceError("invalid_pixel_aspect")
        if not finite(self.nominal_fps) or not 0 < self.nominal_fps <= 120:
            raise SourceError("source_rate_limit")
        if type(self.poses) is not tuple or len(self.poses) > 2:
            raise SourceError("pose_limit")
        for pose in self.poses:
            if type(pose) is not tuple or len(pose) != 33 or any(type(p) is not Landmark for p in pose):
                raise SourceError("invalid_pose_dimensions")
            if tuple(p.name for p in pose) != LANDMARK_NAMES:
                raise SourceError("invalid_landmark_order")
        if self.source_kind not in ("synthetic", "fixture", "video", "camera") or self.status not in ("ok", "missing", "late"):
            raise SourceError("invalid_source_status")
        if not identifier(self.source_id):
            raise SourceError("invalid_source_id")
        if any(v is not None and not identifier(v) for v in (self.model_id, self.runtime_id)):
            raise SourceError("invalid_model_runtime_id")
        current_slot = floor(self.t_media * self.nominal_fps + 1e-9)
        for slots in (self.missing_slots, self.late_slots):
            if type(slots) is not tuple or len(slots) > 7201 or any(type(s) is not int or not 0 <= s <= current_slot for s in slots) or len(set(slots)) != len(slots):
                raise SourceError("invalid_frame_slots")
        if self.status == "late" and current_slot not in self.late_slots:
            raise SourceError("invalid_frame_slots")
        if self.status == "missing" and current_slot not in self.missing_slots:
            raise SourceError("invalid_frame_slots")
        if self.status == "missing" and self.poses:
            raise SourceError("missing_frame_has_poses")
        if self.receive_ns is None:
            if self.clock_domain is not None or self.clock_scope is not None:
                raise SourceError("incomplete_receive_clock")
        elif type(self.receive_ns) is not int or self.receive_ns < 0 or self.clock_domain != "process_monotonic_ns" or not identifier(self.clock_scope):
            raise SourceError("invalid_receive_clock")

    @property
    def unavailable_slots(self) -> tuple[int, ...]:
        return tuple(sorted(set(self.missing_slots) | set(self.late_slots)))

class LandmarkSource(Protocol):
    def read(self) -> FrameBatch | None: ...
    def close(self) -> None: ...

class StreamValidator:
    """One instance per stream. A failed stream cannot resume as successful."""
    def __init__(self) -> None:
        self._last: FrameBatch | None = None
        self._bytes = 0
        self._frames = 0
        self._failed = False

    def accept(self, batch: FrameBatch, decoded_bytes: int = 0) -> FrameBatch:
        if self._failed:
            raise SourceError("stream_failed")
        try:
            if type(batch) is not FrameBatch or type(decoded_bytes) is not int or decoded_bytes < 0:
                raise SourceError("invalid_stream_input")
            # Conservative decoded-object allowance, in addition to parser/device byte counts.
            cost = decoded_bytes + 1024 + len(batch.poses) * 33 * 256 + 64 * (len(batch.missing_slots) + len(batch.late_slots))
            if self._bytes + cost > 128 * 1024 * 1024 or self._frames >= 7201:
                raise SourceError("decoded_trace_limit")
            old = self._last
            if old is not None:
                if batch.t_media <= old.t_media:
                    raise SourceError("nonmonotonic_media_time")
                if batch.t_media - old.t_media < 1 / 120 - 1e-9:
                    raise SourceError("source_rate_limit")
                stable = ("source_id", "source_kind", "width", "height", "pixel_aspect", "nominal_fps", "model_id", "runtime_id", "clock_domain", "clock_scope")
                if any(getattr(batch, key) != getattr(old, key) for key in stable):
                    raise SourceError("source_discontinuity")
                if old.receive_ns is not None and (batch.receive_ns is None or batch.receive_ns < old.receive_ns):
                    raise SourceError("nonmonotonic_receive_clock")
                if (old.receive_ns is None) != (batch.receive_ns is None):
                    raise SourceError("receive_clock_changed")
            self._last = batch
            self._bytes += cost
            self._frames += 1
            return batch
        except (SourceError, OverflowError):
            self._failed = True
            raise

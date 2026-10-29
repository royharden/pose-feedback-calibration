"""Causal warm-up geometry adapter to the existing scalar seam."""
from dataclasses import dataclass
from math import acos, degrees, hypot
from statistics import median
from .landmarks import FrameBatch, Landmark, SourceError, StreamValidator, finite
from .schema import AngleFrame
from .windows import Window, nominal_slot

LEFT = (23, 25, 27)
RIGHT = (24, 26, 28)

def _point(batch: FrameBatch, joint: Landmark) -> tuple[float, float]:
    # Convert before multiplying: accepted integer coordinates may be finite,
    # while their intermediate integer pixel product cannot become a float.
    try:
        point = (float(joint.x) * float(batch.width) * float(batch.pixel_aspect),
                 float(joint.y) * float(batch.height))
    except OverflowError as exc:
        raise SourceError("geometry_overflow") from exc
    if not all(finite(v) for v in point):
        raise SourceError("geometry_overflow")
    return point

def _usable(joint: Landmark) -> bool:
    return joint.visibility >= 0.5 and (joint.presence is None or joint.presence > 0)

def _joint_angle(batch: FrameBatch, indices: tuple[int, int, int]) -> float | None:
    if len(batch.poses) != 1 or batch.status == "missing":
        return None
    joints = tuple(batch.poses[0][i] for i in indices)
    if not all(_usable(j) for j in joints):
        return None
    hip, knee, ankle = (_point(batch, j) for j in joints)
    a = (hip[0] - knee[0], hip[1] - knee[1])
    b = (ankle[0] - knee[0], ankle[1] - knee[1])
    la, lb = hypot(*a), hypot(*b)
    if not finite(la) or not finite(lb):
        raise SourceError("geometry_overflow")
    if la <= 1e-12 or lb <= 1e-12:
        return None
    dot = (a[0] / la) * (b[0] / lb) + (a[1] / la) * (b[1] / lb)
    return degrees(acos(max(-1.0, min(1.0, dot))))

def knee_angle(batch: FrameBatch, side: str) -> float | None:
    if side not in ("left", "right"):
        raise SourceError("invalid_side")
    return _joint_angle(batch, LEFT if side == "left" else RIGHT)

def _torso(batch: FrameBatch) -> tuple[tuple[float, float], float] | None:
    if len(batch.poses) != 1:
        return None
    joints = [batch.poses[0][i] for i in (11, 12, 23, 24)]
    if not all(_usable(j) for j in joints):
        return None
    ls, rs, lh, rh = (_point(batch, j) for j in joints)
    shoulder = (ls[0] / 2 + rs[0] / 2, ls[1] / 2 + rs[1] / 2)
    hip = (lh[0] / 2 + rh[0] / 2, lh[1] / 2 + rh[1] / 2)
    length = hypot(shoulder[0] - hip[0], shoulder[1] - hip[1])
    if not finite(length):
        raise SourceError("geometry_overflow")
    return (hip, length) if length > 1e-12 else None

@dataclass(frozen=True)
class GeometryFrame:
    angle_frame: AngleFrame
    side: str
    hip_xy: tuple[float, float] | None
    torso_length_px: float
    missing_slots: tuple[int, ...]
    late_slots: tuple[int, ...]
    elbow_left: float | None
    elbow_right: float | None
    nominal_interval_s: float | None
    slot_index: int | None
    phase: str
    evidence_reason: str | None
    source_status: str
    receive_ns: int | None
    clock_domain: str | None
    clock_scope: str | None

    def evidence_kwargs(self) -> dict[str, object] | None:
        """Neutral constructor fields for the future consumer-owned FrameEvidence.

        Warm-up replay never becomes post-reset movement history. A bridge must
        pass None through rather than fabricate support when metadata is absent.
        """
        if self.evidence_reason is not None or self.hip_xy is None:
            return None
        return dict(elbow_left=self.elbow_left, elbow_right=self.elbow_right,
            hip_x=self.hip_xy[0], hip_y=self.hip_xy[1], torso_scale=self.torso_length_px,
            nominal_interval_s=self.nominal_interval_s, slot_index=self.slot_index,
            missing_slots=self.missing_slots, late_slots=self.late_slots)

    def bridge_kwargs(self) -> dict[str, object] | None:
        """Neutral attach_evidence fields, including unavailable input values.

        Warm-up replay never enters movement history. The consumer assigns its
        named evidence reason from the remaining frames' actual inputs.
        """
        if self.phase == "warmup":
            return None
        return dict(elbow_left=self.elbow_left, elbow_right=self.elbow_right,
            hip_xy=self.hip_xy, torso_scale=self.torso_length_px,
            nominal_interval_s=self.nominal_interval_s, slot_index=self.slot_index,
            missing_slots=self.missing_slots, late_slots=self.late_slots)

class GeometryAdapter:
    """Buffer only [0,3) warm-up; never choose a side using scored frames.

    update returns zero outputs during warm-up, then releases warm-up AngleFrames
    in media order followed by the current frame. Feed every angle_frame to Counter.
    hip_xy is a separate provisional movement seam, not part of AngleFrame.
    """
    def __init__(self) -> None:
        self._validator = StreamValidator()
        self._warmup: list[FrameBatch] = []
        self.side: str | None = None
        self.standing_reference: float | None = None
        self.torso_length_px: float | None = None
        self._closed = False
        self._failed = False

    def _freeze(self) -> None:
        if not self._warmup:
            raise SourceError("standing_reference_unavailable")
        def mean(indices: tuple[int, int, int]) -> float:
            return sum(sum(b.poses[0][i].visibility for i in indices) / 3 if len(b.poses) == 1 else 0.0 for b in self._warmup) / len(self._warmup)
        self.side = "right" if mean(RIGHT) > mean(LEFT) else "left"
        angles = [v for b in self._warmup if (v := knee_angle(b, self.side)) is not None]
        torsos = [t[1] for b in self._warmup if (t := _torso(b)) is not None]
        if not angles or not torsos:
            raise SourceError("standing_reference_unavailable")
        torsos.sort()
        middle = len(torsos) // 2
        scale = torsos[middle]
        if len(torsos) % 2 == 0:
            lower = torsos[middle - 1]
            # Positive sorted values keep both the difference and midpoint
            # bounded, unlike median's potentially overflowing (lower + upper).
            scale = lower + (scale - lower) / 2
        if not finite(scale) or scale <= 0:
            raise SourceError("geometry_overflow")
        self.standing_reference = median(angles)
        self.torso_length_px = scale

    def _convert(self, batch: FrameBatch) -> GeometryFrame:
        assert self.side is not None and self.torso_length_px is not None
        if not finite(self.torso_length_px) or self.torso_length_px <= 0:
            raise SourceError("geometry_overflow")
        count = len(batch.poses)
        idx = LEFT if self.side == "left" else RIGHT
        visibility = tuple(batch.poses[0][i].visibility for i in idx) if count == 1 else (0.0, 0.0, 0.0)
        angle = knee_angle(batch, self.side)
        torso = _torso(batch)
        hip = None if torso is None else tuple(v / self.torso_length_px for v in torso[0])
        if hip is not None and not all(finite(v) for v in hip):
            raise SourceError("geometry_overflow")
        scalar = AngleFrame(batch.t_media, angle, visibility, count)
        scalar.validate()
        elbows = (_joint_angle(batch, (11, 13, 15)), _joint_angle(batch, (12, 14, 16)))
        interval = 1 / batch.nominal_fps
        slot = nominal_slot(batch.t_media, batch.nominal_fps)
        phase = Window().phase(batch.t_media)
        # Preserve floor-grid source slot semantics and real media times. An
        # irregular sample outside the consumer's half-interval tolerance has no
        # valid movement metadata; do not round time or relabel it as a future slot.
        grid_ok = 1 / 120 <= interval <= .5 and slot <= 7200 and abs(slot * interval - batch.t_media) <= interval / 2 + 1e-9
        reason = ("warmup_not_scored" if phase == "warmup" else
                  "nominal_grid_unavailable" if not grid_ok else
                  "movement_inputs_missing" if hip is None or any(v is None for v in elbows) else None)
        return GeometryFrame(scalar, self.side, hip, self.torso_length_px,
            batch.missing_slots, batch.late_slots, elbows[0], elbows[1],
            interval if grid_ok else None, slot if grid_ok else None, phase,
            reason, batch.status, batch.receive_ns, batch.clock_domain, batch.clock_scope)

    def update(self, batch: FrameBatch) -> tuple[GeometryFrame, ...]:
        if self._closed or self._failed:
            raise SourceError("geometry_closed")
        try:
            self._validator.accept(batch)
            if self.side is None:
                if batch.t_media < 3:
                    self._warmup.append(batch)
                    return ()
                self._freeze()
                outputs = tuple(self._convert(b) for b in self._warmup)
                self._warmup.clear()
                return outputs + (self._convert(batch),)
            return (self._convert(batch),)
        except OverflowError as exc:
            self._failed = True
            raise SourceError("geometry_overflow") from exc
        except ValueError:
            self._failed = True
            raise

    def finish(self) -> None:
        self._closed = True
        if self._failed or self.side is None:
            raise SourceError("standing_reference_unavailable")

"""Closed numeric primitives; no fitted probability or label access."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, isfinite
from statistics import pvariance
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .schema import AngleFrame, Event


def bounded(value: float) -> float:
    if not isfinite(value):
        raise ValueError("nonfinite feature")
    return min(1.0, max(0.0, value))


def consistency(value: float, reference: float, floor: float) -> float:
    if not all(isfinite(x) for x in (value, reference, floor)) or floor <= 0:
        raise ValueError("invalid consistency input")
    return bounded(1.0 - abs(value - reference) / max(reference, floor))


def gapfree(expected_frames: int, missing_slots: Iterable[int], late_slots: Iterable[int]) -> float:
    """Slot IDs refer to one nominal interval grid; overlap counts once."""
    if type(expected_frames) is not int or expected_frames <= 0:
        raise ValueError("invalid expected frame count")
    slots = set(missing_slots) | set(late_slots)
    if any(type(s) is not int or not 0 <= s < expected_frames for s in slots):
        raise ValueError("invalid missing/late slot")
    return bounded(1.0 - len(slots) / expected_frames)


@dataclass(frozen=True)
class MotionSample:
    """Hip coordinates already normalized by a valid warm-up torso scale."""

    t_media: float
    theta: float
    elbow_left: float
    elbow_right: float
    hip_x: float
    hip_y: float


def movement(history: Iterable[MotionSample], now: float, torso_scale: float) -> float:
    """Available post-reset trailing 6 s only. Missing features raise, never open."""
    if not isfinite(now) or not isfinite(torso_scale) or torso_scale <= 0:
        raise ValueError("invalid movement reference")
    rows = list(history)
    previous = None
    for row in rows:
        if not all(isfinite(x) for x in (
            row.t_media, row.theta, row.elbow_left, row.elbow_right, row.hip_x, row.hip_y
        )) or row.t_media > now or row.t_media < 3:
            raise ValueError("invalid or noncausal movement input")
        if previous is not None and row.t_media <= previous:
            raise ValueError("nonmonotonic movement input")
        previous = row.t_media
    rows = [r for r in rows if now - 6 <= r.t_media <= now]
    if not rows:
        raise ValueError("movement_inputs_missing")
    leg = pvariance(r.theta for r in rows)
    arms = pvariance(r.elbow_left for r in rows) + pvariance(r.elbow_right for r in rows)
    xs, ys = [r.hip_x for r in rows], [r.hip_y for r in rows]
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    return bounded(leg / (leg + arms + 1e-6) * (1 - dx / (dx + dy + 1e-6)))


@dataclass(frozen=True)
class WindowFeatures:
    """Exact order for the future six-input logistic map; not a probability."""

    vis: float
    gapfree: float
    amp: float
    intv: float
    mean_g: float
    no_cycle: int

    def vector(self) -> tuple[float, ...]:
        values = (self.vis, self.gapfree, self.amp, self.intv, self.mean_g)
        if any(not isfinite(v) or not 0 <= v <= 1 for v in values):
            raise ValueError("unbounded window feature")
        if type(self.no_cycle) is not int or self.no_cycle not in (0, 1):
            raise ValueError("invalid no_cycle")
        if self.no_cycle and (self.amp != 0 or self.intv != 0):
            raise ValueError("no-cycle amp/intv must be zero")
        return (*values, float(self.no_cycle))


def quality(vis: float, gapfree_score: float, amp: float, intv: float) -> float:
    values = (vis, gapfree_score, amp, intv)
    if any(not isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError("unbounded quality input")
    return min(values)


@dataclass(frozen=True)
class _Observation:
    t_media: float
    visible: bool
    slot: int | None
    missing: tuple[int, ...]
    late: tuple[int, ...]
    g: float | None


class EvidenceTracker:
    """Bounded causal evidence; one instance per media window.

    Slot IDs belong to a fixed nominal grid with media origin zero. The caller
    resets motion at source discontinuities and counter boundaries, but never
    clears window observations or earlier exposed-event support. No labels enter.
    """

    def __init__(self) -> None:
        self._rows: list[_Observation] = []
        self._motion: list[MotionSample] = []
        self._interval: float | None = None
        self._torso: float | None = None
        self._last: float | None = None
        self._observations = 0
        self._summary_unavailable = False

    def reset_motion(self) -> None:
        """Discard partial movement history, never whole-window support."""
        self._motion.clear()

    def observe(self, frame: AngleFrame) -> float | None:
        """Record one source frame and return available causal movement score.

        Missing evidence/angle/single-pose support closes movement and makes the
        six-feature summary unavailable. Such frames still enter visibility
        support. An ordinary below-threshold score does not clear history.
        """
        t = frame.t_media
        if not isfinite(t) or t < 0 or t > 60:
            raise ValueError("invalid evidence time")
        if self._last is not None and t <= self._last:
            raise ValueError("nonmonotonic evidence time")
        if self._observations >= 7201:
            raise ValueError("evidence input limit")
        evidence = frame.evidence
        if evidence is not None:
            try:
                evidence.validate(t)
            except (ValueError, TypeError, OverflowError):
                self._summary_unavailable = True
                self.reset_motion()
                raise
            if self._interval is not None and abs(
                evidence.nominal_interval_s - self._interval
            ) > 1e-12:
                self._summary_unavailable = True
                self.reset_motion()
                raise ValueError("nominal interval changed")
            if self._torso is not None and abs(evidence.torso_scale - self._torso) > 1e-12:
                self._summary_unavailable = True
                self.reset_motion()
                raise ValueError("standing torso reference changed")
            self._interval = evidence.nominal_interval_s
            self._torso = evidence.torso_scale
        if self._last is not None and t - self._last > 0.5:
            self.reset_motion()
        self._last = t
        self._observations += 1
        if t < 3:
            # No pre-scoring state enters the movement window.
            self.reset_motion()
            return None

        visible = (
            frame.poses == 1
            and frame.theta is not None
            and len(frame.visibility) == 3
            and all(isfinite(v) and v >= 0.5 for v in frame.visibility)
        )
        g = None
        if evidence is None or frame.theta is None or frame.poses != 1:
            self.reset_motion()
        else:
            self._motion = [row for row in self._motion if row.t_media >= t - 6]
            self._motion.append(MotionSample(
                t, frame.theta, evidence.elbow_left, evidence.elbow_right,
                evidence.hip_x, evidence.hip_y,
            ))
            try:
                g = movement(self._motion, t, evidence.torso_scale)
            except (ValueError, TypeError, OverflowError):
                self._summary_unavailable = True
                self.reset_motion()
                raise
        if t < 30 and g is None:
            self._summary_unavailable = True
        self._rows.append(_Observation(
            t, visible, None if evidence is None else evidence.slot_index,
            () if evidence is None else tuple(evidence.missing_slots),
            () if evidence is None else tuple(evidence.late_slots), g,
        ))
        return g

    def low_visibility(self, now: float) -> bool:
        """Hard gate: more than 20% low-support frames in trailing two seconds."""
        if not isfinite(now) or (self._last is not None and now > self._last):
            raise ValueError("noncausal visibility time")
        rows = [row for row in self._rows if now - 2 <= row.t_media <= now]
        return not rows or sum(not row.visible for row in rows) / len(rows) > 0.2

    def _support(self, start: float, end: float, *, end_exclusive: bool) -> tuple[float, float]:
        if not all(isfinite(x) for x in (start, end)) or start < 3 or end < start:
            raise ValueError("invalid evidence interval")
        if self._interval is None:
            raise ValueError("nominal evidence missing")
        # Whole-window support may include scheduled future/missing slots at
        # finish; cycle support never reads observations after its endpoint.
        rows = [row for row in self._rows if start <= row.t_media and (
            row.t_media < end if end_exclusive else row.t_media <= end
        )]
        if not rows:
            raise ValueError("evidence frames missing")
        dt = self._interval
        first = ceil(start / dt - 1e-9)
        last = (ceil(end / dt - 1e-9) - 1) if end_exclusive else floor(end / dt + 1e-9)
        if first < 0 or last > 7200 or last < first:
            raise ValueError("invalid expected frame count")
        expected = set(range(first, last + 1))
        seen = {row.slot for row in rows if row.slot is not None}
        reported_missing = {slot for row in rows for slot in row.missing}
        reported_late = {slot for row in rows for slot in row.late}
        unavailable = (expected - seen) | ((reported_missing | reported_late) & expected)
        # Rebase global slots only at the numeric helper boundary.
        gap = gapfree(len(expected), (slot - first for slot in unavailable), ())
        return sum(row.visible for row in rows) / len(rows), gap

    def support(self, start: float, end: float) -> tuple[float, float]:
        """Observed cycle support through an inclusive, already observed end."""
        if self._last is None or end > self._last:
            raise ValueError("noncausal cycle support")
        return self._support(start, end, end_exclusive=False)

    def summary(self, events: Iterable[Event]) -> WindowFeatures | None:
        """Six inputs from scored observations and final retained cycles only."""
        rows = [row for row in self._rows if 3 <= row.t_media < 30]
        if self._summary_unavailable or not rows or any(row.g is None for row in rows):
            return None
        try:
            vis, gap = self._support(3, 30, end_exclusive=True)
        except ValueError:
            return None
        retained = [event for event in events if event.retained]
        result = WindowFeatures(
            min([vis, *(event.vis for event in retained)]),
            min([gap, *(event.gapfree for event in retained)]),
            min((event.amp for event in retained), default=0.0),
            min((event.intv for event in retained), default=0.0),
            sum(row.g for row in rows if row.g is not None) / len(rows),
            int(not retained),
        )
        result.vector()
        return result

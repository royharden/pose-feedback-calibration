"""Closed numeric primitives; no fitted probability or label access."""

from dataclasses import dataclass
from math import isfinite
from statistics import pvariance
from typing import Iterable


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

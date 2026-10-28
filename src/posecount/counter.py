"""Causal scalar counter arms with immutable exposure and delayed confirmation.

The adapter owns side selection, standing visibility, and aspect-corrected angles.
Every instance consumes one stream/window. Never reuse it for another window.
"""

from collections import deque
from dataclasses import asdict, replace
from hashlib import sha256
import json
from math import exp
from statistics import median

from .features import EvidenceTracker, consistency, quality
from .schema import AngleFrame, CounterConfig, Event, Prediction, Reason


class A1Counter:
    def __init__(self, config: CounterConfig = CounterConfig()) -> None:
        self.config = config
        self._warmup: list[float] = []
        self._stand: float | None = None
        self._last: float | None = None
        self._ema: float | None = None
        self._start: float | None = None
        self._minimum = 180.0
        self._pending: tuple[float, float, float, float, float, bool] | None = None
        self._above_since: float | None = None
        self._amps: deque[float] = deque(maxlen=5)
        self._durations: deque[float] = deque(maxlen=5)
        self._events: list[Event] = []
        self._reasons: list[Reason] = []
        self._error = False
        self._scored = 0
        self._frames = 0
        self._candidates = 0
        self._finished: Prediction | None = None

    def _reason(self, reason: Reason, error: bool = False) -> None:
        if reason not in self._reasons:
            self._reasons.append(reason)
        self._error |= error

    def _reset(self) -> None:
        self._start = None
        self._pending = None
        self._above_since = None
        self._minimum = 180.0

    def source_error(self, reason: Reason = Reason.SOURCE_ERROR) -> None:
        """Adapter failure invalidates the answer, never deletes emitted events."""
        if self._finished is not None:
            raise RuntimeError("counter already finished")
        self._reason(reason, True)
        self._reset()
        self._ema = None

    def _observe(self, frame: AngleFrame, gap: bool) -> None:
        pass

    def _may_process(self, frame: AngleFrame) -> bool:
        return True

    def _filter_event(self, event: Event, frame: AngleFrame) -> Event | None:
        return event

    def update(self, frame: AngleFrame) -> tuple[Event, ...]:
        if self._finished is not None:
            raise RuntimeError("counter already finished")
        try:
            frame.validate()
        except (ValueError, TypeError, OverflowError) as exc:
            try:
                reason = Reason(exc.args[0])
            except (ValueError, TypeError, IndexError):
                reason = Reason.INVALID_INPUT
            self._reason(reason, True)
            self._reset()
            self._ema = None
            return ()
        t = frame.t_media
        previous = self._last
        if previous is not None and t <= previous:
            self._reason(Reason.NONMONOTONIC_TIME, True)
            self._reset()
            self._ema = None
            return ()
        self._frames += 1
        self._last = t
        if t > 60 or self._frames > 7201 or (previous is not None and t - previous < 1 / 120 - 1e-9):
            self._reason(Reason.INPUT_LIMIT, True)
            self._reset()
            self._ema = None
            return ()
        gap = previous is not None and t - previous > 0.5
        self._observe(frame, gap)
        if gap:
            self._reason(Reason.SOURCE_GAP, True)
            self._reset()
            self._ema = None
        if frame.poses != 1 or frame.theta is None:
            self._reason(Reason.POSE_COUNT if frame.poses != 1 else Reason.MISSING_JOINTS, True)
            self._reset()
            self._ema = None
            return ()
        if t < 3:
            if min(frame.visibility) >= 0.5:
                self._warmup.append(frame.theta)
            return ()
        if self._stand is None:
            if not self._warmup:
                self._reason(Reason.STANDING_REFERENCE, True)
                return ()
            reference = median(self._warmup)
            if reference <= self.config.margin_deg:
                self._reason(Reason.STANDING_REFERENCE, True)
                return ()
            self._stand = reference
            self._reset()
            self._ema = None  # No warm-up partial state enters scoring.
        if t < 30:
            self._scored += 1
        if not self._may_process(frame):
            self._reset()
            self._ema = None
            return ()
        if self._ema is None or previous is None:
            self._ema = frame.theta
        else:
            alpha = 1 - exp(-(t - previous) / self.config.tau_s)
            self._ema += alpha * (frame.theta - self._ema)
        theta = self._ema
        up = self._stand - self.config.margin_deg / 3
        if self._pending is not None:
            returned, excursion, duration, amp, intv, cold = self._pending
            if t - returned > 1.5 + 1e-9:
                self._reason(Reason.CONFIRMATION_EXPIRED)
                self._reset()
            else:
                if theta > up:
                    if self._above_since is None:
                        self._above_since = t
                    if t - self._above_since >= 0.3 - 1e-9:
                        assert self._start is not None
                        event = Event(len(self._events) + 1, self._start, returned, t, t,
                                      excursion, duration, amp, intv, cold)
                        event = self._filter_event(event, frame)
                        if event is not None:
                            self._events.append(event)
                        self._reset()
                        return () if event is None else (event,)
                else:
                    self._above_since = None
                return ()
        if t >= 30:
            # Tail confirms a pending return only; it cannot create one.
            return ()
        if self._start is None:
            if theta < self._stand - self.config.margin_deg:
                self._start = t
                self._minimum = theta
            return ()
        self._minimum = min(self._minimum, theta)
        if theta > up:
            duration = t - self._start
            excursion = self._stand - self._minimum
            if duration < self.config.min_cycle_s:
                self._reason(Reason.SHORT_CYCLE)
                self._reset()
                return ()
            self._candidates += 1
            cold = not self._amps
            amp = consistency(excursion, median(self._amps) if self._amps else 40.0, 1.0)
            intv = consistency(duration, median(self._durations) if self._durations else 2.0, 0.001)
            # A completed geometric candidate ends at observed standing return.
            # It enters history even when later filtering/confirmation rejects it.
            self._amps.append(excursion)
            self._durations.append(duration)
            self._pending = (t, excursion, duration, amp, intv, cold)
            self._above_since = t
        return ()

    def finish(self) -> Prediction:
        if self._finished is not None:
            return self._finished
        if self._pending is not None:
            self._reason(Reason.UNCONFIRMED_RETURN)
        elif self._start is not None:
            self._reason(Reason.PARTIAL_CYCLE)
        if self._stand is None:
            self._reason(Reason.STANDING_REFERENCE, True)
        if not self._scored:
            self._reason(Reason.NO_SCORED_FRAMES, True)
        if self._last is None or self._last < 30:
            self._reason(Reason.INCOMPLETE_WINDOW, True)
        count = len(self._events)
        self._finished = Prediction("A1", "error" if self._error else "answered",
                                    self._candidates, count, None if self._error else count,
                                    tuple(self._events), tuple(self._reasons))
        return self._finished


class HardGatedCounter(A1Counter):
    """A2-H candidate pipeline; raw A1 candidates are tracked by the facade."""

    def __init__(self, config: CounterConfig) -> None:
        super().__init__(config)
        self.evidence = EvidenceTracker()
        self.hard_gate = False
        self._g: float | None = None
        self._poses = 1

    def _reason(self, reason: Reason, error: bool = False) -> None:
        if reason == Reason.SOURCE_GAP:
            self.hard_gate = True
            error = False
        if reason == Reason.POSE_COUNT and self._poses == 2:
            reason = Reason.SECOND_PERSON
            self.hard_gate = True
            error = False
        super()._reason(reason, error)

    def source_error(self, reason: Reason = Reason.SOURCE_ERROR) -> None:
        super().source_error(reason)
        self.evidence.reset_motion()

    def _observe(self, frame: AngleFrame, gap: bool) -> None:
        self._poses = frame.poses
        if gap:
            self.evidence.reset_motion()
        try:
            self._g = self.evidence.observe(frame)
        except (ValueError, TypeError, OverflowError):
            self.source_error(Reason.INVALID_INPUT)
            self._g = None
            return
        if frame.poses == 2:
            self.hard_gate = True
            self._reason(Reason.SECOND_PERSON)
        if frame.t_media >= 3 and self.evidence.low_visibility(frame.t_media):
            self.hard_gate = True
            self._reason(Reason.REQUIRED_VISIBILITY)

    def _may_process(self, frame: AngleFrame) -> bool:
        if self.hard_gate or self._error:
            return False
        if self._g is None:
            self._reason(Reason.MOVEMENT_INPUTS)
            return False
        if self._g < self.config.movement_threshold:
            self._reason(Reason.MOVEMENT_LOW)
            return False
        return True

    def _filter_event(self, event: Event, frame: AngleFrame) -> Event | None:
        try:
            vis, gap = self.evidence.support(event.t_start_media, frame.t_media)
            q = quality(vis, gap, event.amp, event.intv)
        except (ValueError, TypeError, OverflowError):
            self.source_error(Reason.EXPECTED_FRAMES)
            return None
        if q < self.config.q_threshold:
            self._reason(Reason.QUALITY_LOW)
            return None
        return replace(event, vis=vis, gapfree=gap, q=q)


class HysteresisCounter:
    """A0 fixed-angle hysteresis with down dwell and observed standing return.

    A0 return confirmation honors both the configured up dwell and the shared
    0.3-second continuous-standing rule (the stricter duration controls).
    """

    def __init__(self, config: CounterConfig) -> None:
        self.config = config
        self._last: float | None = None
        self._frames = 0
        self._scored = 0
        self._down_since: float | None = None
        self._start: float | None = None
        self._minimum = 180.0
        self._return: float | None = None
        self._above: float | None = None
        self._events: list[Event] = []
        self._reasons: list[Reason] = []
        self._error = False
        self._visibility: list[float] = []
        self._finished: Prediction | None = None

    def _reset(self) -> None:
        self._down_since = self._start = self._return = self._above = None
        self._minimum = 180.0

    def source_error(self, reason: Reason = Reason.SOURCE_ERROR) -> None:
        if self._finished is not None:
            raise RuntimeError("counter already finished")
        if reason not in self._reasons:
            self._reasons.append(reason)
        self._error = True
        self._reset()

    def update(self, frame: AngleFrame) -> tuple[Event, ...]:
        if self._finished is not None:
            raise RuntimeError("counter already finished")
        try:
            frame.validate()
        except (ValueError, TypeError, OverflowError):
            self.source_error(Reason.INVALID_INPUT)
            return ()
        t = frame.t_media
        previous = self._last
        if previous is not None and t <= previous:
            self.source_error(Reason.NONMONOTONIC_TIME)
            return ()
        self._last = t
        self._frames += 1
        if t > 60 or self._frames > 7201 or (previous is not None and t - previous < 1 / 120 - 1e-9):
            self.source_error(Reason.INPUT_LIMIT)
            return ()
        if previous is not None and t - previous > 0.5:
            self.source_error(Reason.SOURCE_GAP)
        if frame.poses != 1 or frame.theta is None:
            self.source_error(Reason.POSE_COUNT if frame.poses != 1 else Reason.MISSING_JOINTS)
            return ()
        if t < 3:
            self._reset()
            return ()
        if t < 30:
            self._scored += 1
            # A0v ranking score: window mean chosen-joint visibility, not a probability.
            self._visibility.append(sum(frame.visibility) / 3)
        theta = frame.theta
        if self._return is not None:
            if t - self._return > 1.5 + 1e-9:
                if Reason.CONFIRMATION_EXPIRED not in self._reasons:
                    self._reasons.append(Reason.CONFIRMATION_EXPIRED)
                self._reset()
            else:
                if theta > self.config.up_deg:
                    if self._above is None:
                        self._above = t
                    if t - self._above >= max(0.3, self.config.dwell_s) - 1e-9:
                        assert self._start is not None
                        event = Event(len(self._events) + 1, self._start, self._return, t, t,
                                      max(0.0, 180 - self._minimum), self._return - self._start,
                                      0.0, 0.0, False)
                        self._events.append(event)
                        self._reset()
                        return (event,)
                else:
                    self._above = None
                return ()
        if t >= 30:
            return ()
        if self._start is None:
            if theta < self.config.down_deg:
                if self._down_since is None:
                    self._down_since = t
                self._minimum = min(self._minimum, theta)
                if t - self._down_since >= self.config.dwell_s - 1e-9:
                    self._start = self._down_since
            else:
                self._down_since = None
                self._minimum = 180.0
            return ()
        self._minimum = min(self._minimum, theta)
        if theta > self.config.up_deg:
            self._return = self._above = t
        return ()

    def finish(self) -> Prediction:
        if self._finished is not None:
            return self._finished
        if self._return is not None:
            self._reasons.append(Reason.UNCONFIRMED_RETURN)
        elif self._start is not None or self._down_since is not None:
            self._reasons.append(Reason.PARTIAL_CYCLE)
        if not self._scored:
            self.source_error(Reason.NO_SCORED_FRAMES)
        if self._last is None or self._last < 30:
            self.source_error(Reason.INCOMPLETE_WINDOW)
        count = len(self._events)
        self._finished = Prediction("A0", "error" if self._error else "answered",
                                    count, count, None if self._error else count,
                                    tuple(self._events), tuple(dict.fromkeys(self._reasons)))
        return self._finished

    def mean_visibility(self) -> float | None:
        return sum(self._visibility) / len(self._visibility) if self._visibility else None


class Counter:
    """One causal window, default A1; explicit arm policy with null probability.

    Existing Counter(config), update(AngleFrame), finish() calls remain valid.
    Pins are identifiers, never study admission or a verified data receipt.
    """

    def __init__(self, config: CounterConfig = CounterConfig(), *, arm: str = "A1",
                 window_id: str = "", trace_hash: str | None = None) -> None:
        if arm not in {"Z", "A0", "A0v", "A1", "A2-H", "A2"}:
            raise ValueError("unsupported arm")
        if not isinstance(window_id, str) or len(window_id) > 256:
            raise ValueError("invalid window identifier")
        if trace_hash is not None and (not isinstance(trace_hash, str)
                or len(trace_hash) != 64 or any(c not in "0123456789abcdef" for c in trace_hash)):
            raise ValueError("trace hash must be a lowercase SHA256 or None")
        self.config = config
        self.arm = arm
        self.window_id = window_id
        self.trace_hash = trace_hash
        payload = {"arm": arm, "config": asdict(config)}
        self.config_hash = sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                                            separators=(",", ":")).encode()).hexdigest()
        self._raw = A1Counter(config)
        if arm == "A2-H":
            self._core: A1Counter | HysteresisCounter = HardGatedCounter(config)
        elif arm in {"Z", "A0", "A0v"}:
            # Z uses only this core's source/window validity, never A1's standing
            # reference. Its geometric events are neither returned nor retained.
            self._core = HysteresisCounter(config)
        else:
            self._core = self._raw
        self._finished: Prediction | None = None

    def source_error(self, reason: Reason = Reason.SOURCE_ERROR) -> None:
        if self._finished is not None:
            raise RuntimeError("counter already finished")
        reason = Reason(reason)
        self._raw.source_error(reason)
        if self._core is not self._raw:
            self._core.source_error(reason)

    def update(self, frame: AngleFrame) -> tuple[Event, ...]:
        if self._finished is not None:
            raise RuntimeError("counter already finished")
        if not isinstance(frame, AngleFrame):
            self.source_error(Reason.INVALID_INPUT)
            return ()
        # Freeze prior raw candidates when a gated candidate can START. Its
        # return can lag the raw return: copying each frame would leak the raw
        # version of this same physical cycle into its own gated references.
        if (isinstance(self._core, HardGatedCounter)
                and self._core._start is None and self._core._pending is None):
            self._core._amps = deque(self._raw._amps, maxlen=5)
            self._core._durations = deque(self._raw._durations, maxlen=5)
        raw_events = self._raw.update(frame)
        events = raw_events if self._core is self._raw else self._core.update(frame)
        if self.arm in {"Z", "A2"} or (
            self.arm == "A0v" and self.config.visibility_threshold is None
        ):
            return ()
        return events

    def finish(self) -> Prediction:
        if self._finished is not None:
            return self._finished
        raw = self._raw.finish()
        result = raw if self._core is self._raw else self._core.finish()
        result = replace(result, arm=self.arm, candidate_count=raw.candidate_count,
                         window_id=self.window_id, config_hash=self.config_hash,
                         trace_hash=self.trace_hash)
        if self.arm == "Z":
            # Source errors are still errors; the zero control never emits events.
            result = replace(result, events=(), filtered_count=0,
                             final_count=0 if result.status == "answered" else None,
                             reasons=tuple(r for r in result.reasons if r not in {
                                 Reason.PARTIAL_CYCLE, Reason.UNCONFIRMED_RETURN,
                                 Reason.CONFIRMATION_EXPIRED,
                             }))
        elif self.arm == "A2":
            result = replace(result, status="not_run", events=(), filtered_count=0,
                             final_count=None, reasons=(*result.reasons, Reason.CALIBRATION_UNAVAILABLE))
        elif self.arm == "A0v":
            assert isinstance(self._core, HysteresisCounter)
            threshold = self.config.visibility_threshold
            if threshold is None:
                result = replace(result, status="not_run", events=(), filtered_count=0,
                                 final_count=None, reasons=(*result.reasons, Reason.POLICY_UNAVAILABLE))
            elif result.status != "error":
                score = self._core.mean_visibility()
                if score is None or score < threshold:
                    result = replace(result, status="abstain", final_count=None,
                                     reasons=(*result.reasons, Reason.VISIBILITY_POLICY))
        elif self.arm == "A2-H":
            assert isinstance(self._core, HardGatedCounter)
            summary = self._core.evidence.summary(result.events)
            hard = self._core.hard_gate
            if result.status != "error" and (hard or summary is None):
                reasons = result.reasons
                if summary is None and Reason.MOVEMENT_INPUTS not in reasons:
                    reasons = (*reasons, Reason.MOVEMENT_INPUTS)
                result = replace(result, status="abstain", final_count=None, reasons=reasons)
            result = replace(result, hard_gate=hard,
                             features=None if summary is None else summary.vector())
        self._finished = result
        return result

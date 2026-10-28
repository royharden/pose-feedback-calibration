"""A1 only: causal EMA/hysteresis with observed return and delayed confirmation.

The adapter owns side selection, standing visibility, and aspect-corrected angles.
Every instance consumes one stream/window. Never reuse it for another window.
"""

from collections import deque
from math import exp
from statistics import median

from .features import consistency
from .schema import AngleFrame, CounterConfig, Event, Prediction, Reason


class Counter:
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

    def update(self, frame: AngleFrame) -> tuple[Event, ...]:
        if self._finished is not None:
            raise RuntimeError("counter already finished")
        try:
            frame.validate()
        except (ValueError, TypeError, OverflowError):
            self._reason(Reason.INVALID_INPUT, True)
            self._reset()
            return ()
        t = frame.t_media
        previous = self._last
        if previous is not None and t <= previous:
            self._reason(Reason.NONMONOTONIC_TIME, True)
            self._reset()
            return ()
        self._frames += 1
        self._last = t
        if t > 60 or self._frames > 7201 or (previous is not None and t - previous < 1 / 120 - 1e-9):
            self._reason(Reason.INPUT_LIMIT, True)
            self._reset()
            return ()
        gap = previous is not None and t - previous > 0.5
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
                        self._events.append(event)
                        self._reset()
                        return (event,)
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
            # References exclude this candidate; append even if confirmation later fails.
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

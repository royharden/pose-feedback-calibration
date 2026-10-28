"""Bounded synchronous orchestration. No device/optional dependency opens on import.

Factories and receipt assertions are trusted operator boundaries, not a sandbox.
The existing source retains its own rights, pin, offline and private-root checks.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Callable, Protocol

from .counter import Counter
from .geometry import GeometryAdapter
from .landmarks import FrameBatch, LandmarkSource, SourceError
from .latency import ClockAnchor, Span, SpanWriter, anchor_now
from .schema import AngleFrame, Event, Prediction, Reason, attach_evidence


def _digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


@dataclass(frozen=True)
class SessionAuthorization:
    processing_authorized: bool = False
    rights_admitted: bool = False
    offline_receipt_sha256: str | None = None
    private_boundary_receipt_sha256: str | None = None

    def validate(self, input_kind: str) -> None:
        if self.processing_authorized is not True:
            raise SourceError("session_not_authorized")
        if input_kind not in {"synthetic", "fixture", "video", "camera"}:
            raise SourceError("invalid_session_source_kind")
        if input_kind in {"video", "camera"} and (
            self.rights_admitted is not True
            or not _digest(self.offline_receipt_sha256)
            or not _digest(self.private_boundary_receipt_sha256)
        ):
            raise SourceError("real_processing_receipts_missing")


@dataclass(frozen=True)
class ReadReceipt:
    """Optional genuine source instrumentation; never rebased to another scope.

    The current LandmarkSource has no preprocess/inference instrumentation. Its
    receive_ns is monotonic_ns in a source scope, not this perf_counter_ns scope.
    Do not turn source.read() completion (after inference) into capture_return.
    """
    batch: FrameBatch
    capture_return: ClockAnchor | None = None
    preprocess: ClockAnchor | None = None
    inference: ClockAnchor | None = None
    dropped_since_read: int | None = None
    overwritten_since_read: int | None = None


@dataclass(frozen=True)
class DisplayState:
    provisional_count: int
    newly_emitted: tuple[Event, ...]
    gate_message: str
    provisional: bool = True


@dataclass(frozen=True)
class RenderReceipt:
    render_return: ClockAnchor | None = None
    stop_requested: bool = False


class Renderer(Protocol):
    def render(self, batch: FrameBatch, state: DisplayState) -> RenderReceipt: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class HostPresentation:
    """Private per-frame audit; never rewrite media-domain Event timestamps."""
    event_ids: tuple[int, ...]
    render_return: ClockAnchor | None


class LatestOneFrame:
    """Single slot only; no worker, read-ahead or claimed backend buffering.

    Replacing a pending receipt increments overwritten once. The synchronous
    controller offers once and takes immediately, so its overwrites are zero.
    Backend omissions remain unknown unless explicitly reported by a reader.
    """
    def __init__(self) -> None:
        self._pending: ReadReceipt | None = None
        self.offered = 0
        self.taken = 0
        self.overwritten = 0

    def offer(self, value: ReadReceipt) -> None:
        if not isinstance(value, ReadReceipt):
            raise SourceError("invalid_read_receipt")
        self.offered += 1
        if self._pending is not None:
            self.overwritten += 1
        self._pending = value

    def take(self) -> ReadReceipt | None:
        result, self._pending = self._pending, None
        if result is not None:
            self.taken += 1
        return result


@dataclass(frozen=True)
class SessionResult:
    status: str
    stop_reason: str
    prediction: Prediction
    emitted_events: tuple[Event, ...]
    presentations: tuple[HostPresentation, ...]
    source_frames: int
    processed_frames: int
    source_unavailable_slots: int
    backend_dropped: int | None
    backend_overwritten: int | None
    slot_overwritten: int
    controller_dropped: int
    cleanup_errors: tuple[str, ...]
    timing: dict[str, object]
    initialization_ms: float | None
    initialization_reason: str | None

    def aggregate(self) -> dict[str, object]:
        """No source paths/names, machine serials or individual event traces."""
        return {
            "status": self.status, "stop_reason": self.stop_reason,
            "prediction_status": self.prediction.status,
            "final_count": self.prediction.final_count,
            "provisional_count": len(self.emitted_events),
            "presentation_receipts": len(self.presentations),
            "source_frames": self.source_frames, "processed_frames": self.processed_frames,
            "source_unavailable_slots": self.source_unavailable_slots,
            "backend_dropped": self.backend_dropped,
            "backend_overwritten": self.backend_overwritten,
            "backend_counts_reason": "source_backend_uninstrumented" if (
                self.backend_dropped is None or self.backend_overwritten is None) else None,
            "slot_overwritten": self.slot_overwritten,
            "controller_dropped": self.controller_dropped,
            "cleanup_errors": self.cleanup_errors, "timing": self.timing,
            "initialization_ms": self.initialization_ms,
            "initialization_reason": self.initialization_reason,
            "timing_boundary": "capture-return to imshow return/render enqueue only",
            "sensor_exposure_ms": None, "display_photon_ms": None,
            "live_stream_parity": None,
        }


def _elapsed(start: ClockAnchor, end: ClockAnchor) -> float:
    if (type(start.ns) is not int or type(end.ns) is not int
            or start.domain != "process_monotonic_ns" or end.domain != start.domain
            or not start.scope or end.scope != start.scope or end.ns < start.ns):
        raise SourceError("session_clock_invalid")
    return (end.ns - start.ns) / 1e9


def _count(value: int | None) -> int | None:
    if value is not None and (type(value) is not int or not 0 <= value <= 7201):
        raise SourceError("invalid_backend_frame_count")
    return value


def run_session(
    source_factory: Callable[[], LandmarkSource],
    renderer_factory: Callable[[], Renderer],
    *,
    authorization: SessionAuthorization = SessionAuthorization(),
    input_kind: str,
    counter: Counter | None = None,
    read_instrumented: Callable[[LandmarkSource], ReadReceipt | None] | None = None,
    gate_reason: Callable[[Counter, AngleFrame], Reason | None] | None = None,
    stop_requested: Callable[[], bool] = lambda: False,
    max_seconds: float = 60.0,
    max_frames: int = 7201,
) -> SessionResult:
    """Run only under a future authorized operator; never invoked at construction.

    One source read at a time; no retry on failure. Deadline is cooperative:
    callbacks must themselves return/timeout, including blocking device reads.
    Factories must release partial opens before raising. `gate_reason` is a
    trusted producer callback for the current causal gate (None means open).
    Without it the renderer states live_gate_unavailable, not an inferred pass.
    """
    if (type(max_seconds) not in (int, float) or not 0 < max_seconds <= 60
            or type(max_frames) is not int or not 1 <= max_frames <= 7201):
        raise SourceError("invalid_session_bound")
    detector = Counter() if counter is None else counter
    geometry = GeometryAdapter()
    timing = SpanWriter(max_samples=max_frames)
    slot = LatestOneFrame()
    source: LandmarkSource | None = None
    renderer: Renderer | None = None
    emitted: list[Event] = []
    presentations: list[HostPresentation] = []
    unavailable: set[int] = set()
    source_frames = processed = 0
    controller_dropped = 0
    backend_drops = backend_overwrites = 0
    drop_known = overwrite_known = True
    cleanup_errors: list[str] = []
    status, reason = "completed", "end_of_stream"
    initialization_ms: float | None = None
    initialization_reason: str | None = "initialization_incomplete"
    initialization_start = anchor_now()
    try:
        authorization.validate(input_kind)
        source = source_factory()
        renderer = renderer_factory()
        active_start = anchor_now()
        initialization_ms = _elapsed(initialization_start, active_start) * 1000
        initialization_reason = None
        for frame_index in range(max_frames):
            if stop_requested():
                status, reason = "stopped", "operator_stop"
                break
            if _elapsed(active_start, anchor_now()) >= max_seconds:
                status, reason = "timeout", "session_deadline"
                break
            if read_instrumented is None:
                batch = source.read()
                receipt = None if batch is None else ReadReceipt(batch)
            else:
                receipt = read_instrumented(source)
            if receipt is None:
                break
            if not isinstance(receipt, ReadReceipt) or not isinstance(receipt.batch, FrameBatch):
                raise SourceError("invalid_read_receipt")
            source_frames += 1
            elapsed: float | None = None
            counter_return: ClockAnchor | None = None
            rendered: RenderReceipt | None = None
            frame_processed = False
            drops = overwrites = None
            try:
                elapsed = _elapsed(active_start, anchor_now())
                if receipt.batch.source_kind != input_kind:
                    raise SourceError("session_source_kind_mismatch")
                drops = _count(receipt.dropped_since_read)
                overwrites = _count(receipt.overwritten_since_read)
                unavailable.update(receipt.batch.unavailable_slots)
                slot.offer(receipt)
                current = slot.take()
                assert current is not None
                batch = current.batch
                if elapsed >= max_seconds:
                    status, reason = "timeout", "session_deadline_after_read"
                    break
                new_events: list[Event] = []
                latest_scalar: AngleFrame | None = None
                for converted in geometry.update(batch):
                    scalar = converted.angle_frame
                    kwargs = converted.bridge_kwargs()
                    if kwargs is not None:
                        scalar = attach_evidence(scalar, **kwargs)
                    latest_scalar = scalar
                    additions = detector.update(scalar)
                    # Preserve exposure before render/stop/error can occur.
                    visible = tuple(event for event in additions if event.emitted)
                    emitted.extend(visible)
                    new_events.extend(visible)
                counter_return = anchor_now()
                frame_processed = True
                processed += 1
                if latest_scalar is None:
                    message = "not counting: warmup"
                elif gate_reason is None:
                    message = "not counting: live_gate_unavailable"
                else:
                    gate = gate_reason(detector, latest_scalar)
                    message = "provisional count" if gate is None else f"not counting: {Reason(gate).value}"
                rendered = renderer.render(batch, DisplayState(len(emitted), tuple(new_events), message))
                if not isinstance(rendered, RenderReceipt):
                    rendered = None
                    raise SourceError("invalid_render_receipt")
                if type(rendered.stop_requested) is not bool:
                    raise SourceError("invalid_render_receipt")
            finally:
                if not frame_processed:
                    controller_dropped += 1
                drop_known = drop_known and drops is not None
                overwrite_known = overwrite_known and overwrites is not None
                backend_drops += drops or 0
                backend_overwrites += overwrites or 0
                timing.append(Span(frame_index=frame_index, elapsed_s=elapsed,
                    capture_return=receipt.capture_return, preprocess=receipt.preprocess,
                    inference=receipt.inference, counter_update=counter_return,
                    render_return=None if rendered is None else rendered.render_return))
            # A receipt is evidence of a renderer-return boundary, not photons.
            if new_events:
                presentations.append(HostPresentation(tuple(e.event_id for e in new_events), rendered.render_return))
            if rendered.stop_requested:
                status, reason = "stopped", "renderer_stop"
                break
            if _elapsed(active_start, anchor_now()) >= max_seconds:
                status, reason = "timeout", "session_deadline_after_render"
                break
        else:
            status, reason = "stopped", "frame_limit"
        if status == "completed":
            geometry.finish()
    except (KeyboardInterrupt, SystemExit):
        status, reason = "stopped", "interrupted"
        detector.source_error()
    except SourceError as exc:
        # Only known nonidentifying source reasons may enter aggregate output.
        allowed = {
            "session_not_authorized", "invalid_session_source_kind",
            "real_processing_receipts_missing", "camera_unavailable",
            "camera_read_failed", "device_open_unavailable", "device_read_failed",
            "session_source_kind_mismatch", "invalid_read_receipt",
            "invalid_render_receipt", "session_clock_invalid",
            "invalid_backend_frame_count", "standing_reference_unavailable",
        }
        status, reason = "error", exc.reason if exc.reason in allowed else "source_failed"
        detector.source_error()
    except Exception:
        # Exception text may contain private file paths; retain only closed reason.
        status, reason = "error", "session_failed"
        detector.source_error()
    finally:
        for resource, name in ((renderer, "renderer_close_failed"), (source, "source_close_failed")):
            if resource is not None:
                try:
                    resource.close()
                except BaseException:
                    cleanup_errors.append(name)
        if cleanup_errors:
            status, reason = "error", "cleanup_failed"
            detector.source_error()
    if status in {"stopped", "timeout"}:
        detector.source_error()
    prediction = detector.finish()
    reported_drops = backend_drops if drop_known and source_frames else None
    reported_overwrites = backend_overwrites if overwrite_known and source_frames else None
    timing_summary = timing.summary()
    # SpanWriter cannot infer whether zero means observed zero or no instrumentation.
    timing_summary["reported_dropped_frames"] = reported_drops
    timing_summary["reported_overwritten_frames"] = reported_overwrites
    if reported_drops is None or reported_overwrites is None:
        timing_summary["drop_accounting"] = "source_backend_uninstrumented"
    return SessionResult(status, reason, prediction, tuple(emitted), tuple(presentations),
        source_frames, processed, len(unavailable),
        reported_drops, reported_overwrites,
        slot.overwritten, controller_dropped, tuple(cleanup_errors), timing_summary,
        initialization_ms, initialization_reason)


class OpenCVRenderer:
    """Optional future renderer; image production is caller-owned and private.

    Construct via the guarded renderer factory. No raw frames are retained here.
    A caller must supply a compatible already-approved local runtime; no fetch.
    """
    def __init__(self, image_for: Callable[[FrameBatch, DisplayState], object]) -> None:
        self._image_for = image_for
        self._cv2 = None
        self._opened = False
        self._closed = False

    def render(self, batch: FrameBatch, state: DisplayState) -> RenderReceipt:
        if self._closed:
            raise SourceError("renderer_closed")
        if self._cv2 is None:
            self._cv2 = importlib.import_module("cv2")
        image = self._image_for(batch, state)
        self._opened = True  # close even if imshow partly opens then raises
        self._cv2.imshow("M17 provisional count", image)
        returned = anchor_now()
        key = self._cv2.waitKey(1)
        return RenderReceipt(returned, key in (27, ord("q")))

    def close(self) -> None:
        self._closed = True
        if self._opened and self._cv2 is not None:
            self._cv2.destroyWindow("M17 provisional count")
        self._opened = False

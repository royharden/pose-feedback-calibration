"""Host-stage timing contracts; no camera, inference, render or network effects.

Only explicit source instrumentation can provide preprocessing/inference anchors.
Clock scopes identify one process, not a machine or a media timeline. Aggregates
describe bounded retained samples, never sensor exposure or display photons.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil, isfinite
from time import perf_counter_ns
from typing import Literal
from uuid import UUID, uuid4


CLOCK_DOMAIN = "process_monotonic_ns"
PROCESS_SCOPE = str(uuid4())
STAGES = {
    "preprocess_ms": ("capture_return", "preprocess"),
    "inference_ms": ("preprocess", "inference"),
    "counter_update_ms": ("inference", "counter_update"),
    "render_ms": ("counter_update", "render_return"),
    "capture_to_render_ms": ("capture_return", "render_return"),
}


def _finite(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class ClockAnchor:
    ns: int | float | None
    domain: str | None
    scope: str | None


def anchor_now() -> ClockAnchor:
    """Explicit host observation, called only by a future authorized session."""
    return ClockAnchor(perf_counter_ns(), CLOCK_DOMAIN, PROCESS_SCOPE)


@dataclass(frozen=True)
class Duration:
    value_ms: float | None
    reason: str | None


def duration(start: ClockAnchor | None, end: ClockAnchor | None) -> Duration:
    """Return unknown rather than comparing incomplete or incompatible clocks."""
    if start is None or end is None:
        return Duration(None, "missing_anchor")
    if not isinstance(start, ClockAnchor) or not isinstance(end, ClockAnchor):
        return Duration(None, "invalid_anchor")
    if start.ns is None or end.ns is None:
        return Duration(None, "missing_time")
    if not _finite(start.ns) or not _finite(end.ns):
        return Duration(None, "nonfinite_time")
    if type(start.ns) is not int or type(end.ns) is not int or min(start.ns, end.ns) < 0:
        return Duration(None, "invalid_nanoseconds")
    if start.domain != CLOCK_DOMAIN or end.domain != CLOCK_DOMAIN:
        return Duration(None, "clock_domain_mismatch")
    if start.scope is None or end.scope is None:
        return Duration(None, "missing_clock_scope")
    try:
        UUID(start.scope)
        UUID(end.scope)
    except (ValueError, TypeError, AttributeError):
        return Duration(None, "invalid_clock_scope")
    if start.scope != end.scope:
        return Duration(None, "clock_scope_mismatch")
    if end.ns < start.ns:
        return Duration(None, "reversed_time")
    try:
        value = (end.ns - start.ns) / 1_000_000
    except OverflowError:
        return Duration(None, "nonfinite_duration")
    return Duration(value, None) if _finite(value) else Duration(None, "nonfinite_duration")


@dataclass(frozen=True)
class Span:
    frame_index: int
    elapsed_s: float | None
    capture_return: ClockAnchor | None = None
    preprocess: ClockAnchor | None = None
    inference: ClockAnchor | None = None
    counter_update: ClockAnchor | None = None
    render_return: ClockAnchor | None = None

    def __post_init__(self) -> None:
        if type(self.frame_index) is not int or self.frame_index < 0:
            raise ValueError("invalid_frame_index")

    @property
    def phase(self) -> str:
        if not _finite(self.elapsed_s) or self.elapsed_s < 0:
            return "unclassified"
        return "init_warmup" if self.elapsed_s < 5 else "steady_state"

    def durations(self) -> dict[str, Duration]:
        return {name: duration(getattr(self, start), getattr(self, end))
                for name, (start, end) in STAGES.items()}

    def to_dict(self) -> dict[str, object]:
        """Private per-frame record; use SpanWriter.summary for aggregate reports."""
        return {
            "frame_index": self.frame_index,
            "elapsed_s": self.elapsed_s if self.phase != "unclassified" else None,
            "phase": self.phase,
            "phase_reason": "invalid_elapsed_time" if self.phase == "unclassified" else None,
            "anchors": {name: asdict(getattr(self, name)) if isinstance(getattr(self, name), ClockAnchor) else None
                        for name in ("capture_return", "preprocess", "inference", "counter_update", "render_return")},
            "stages": {name: asdict(value) for name, value in self.durations().items()},
        }


def nearest_rank(values: list[float], percentile: float) -> float | None:
    """1-indexed x[ceil(p*n)], with empty support represented as null."""
    if not _finite(percentile) or not 0 < percentile <= 1:
        raise ValueError("invalid_percentile")
    if any(not _finite(v) or v < 0 for v in values):
        raise ValueError("invalid_duration_sample")
    if not values:
        return None
    ordered = sorted(values)
    return ordered[ceil(percentile * len(ordered)) - 1]


def _count(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid_count")
    return value


class SpanWriter:
    """In-memory bounded retention, not a file writer or device-drop detector.

    The first max_samples spans are retained. Overflow is counted and explicitly
    labels the quantile population as truncated; no unbounded trace is collected.
    Drop/overwrite counters are caller reports, never guessed from read latency.
    """

    def __init__(self, max_samples: int = 7201) -> None:
        if type(max_samples) is not int or not 1 <= max_samples <= 7201:
            raise ValueError("invalid_sample_limit")
        self.max_samples = max_samples
        self._spans: list[Span] = []
        self._received = 0
        self._overflow = 0
        self._dropped = 0
        self._overwritten = 0

    def append(self, span: Span) -> None:
        if not isinstance(span, Span):
            raise ValueError("invalid_span")
        self._received += 1
        if len(self._spans) >= self.max_samples:
            self._overflow += 1
        else:
            self._spans.append(span)

    def record_drop(self, count: int = 1) -> None:
        self._dropped += _count(count)

    def record_overwrite(self, count: int = 1) -> None:
        self._overwritten += _count(count)

    def summary(self) -> dict[str, object]:
        phases: dict[str, object] = {}
        for phase in ("init_warmup", "steady_state", "unclassified"):
            selected = [s for s in self._spans if s.phase == phase]
            stages: dict[str, object] = {}
            for stage in STAGES:
                samples: list[float] = []
                reasons: dict[str, int] = {}
                for span in selected:
                    result = span.durations()[stage]
                    if result.value_ms is None:
                        reason = result.reason or "unknown"
                        reasons[reason] = reasons.get(reason, 0) + 1
                    else:
                        samples.append(result.value_ms)
                stages[stage] = {
                    "unit": "ms", "valid_count": len(samples),
                    "unknown_count": len(selected) - len(samples),
                    "unknown_reasons": reasons,
                    "p50": nearest_rank(samples, .50), "p95": nearest_rank(samples, .95),
                    "p99": nearest_rank(samples, .99),
                    "reason": None if samples else "no_valid_samples",
                }
            phases[phase] = {"span_count": len(selected), "stages": stages}
        return {
            "clock_domain": CLOCK_DOMAIN,
            "measurement_boundary": "capture_return_to_render_return_or_enqueue",
            "photon_latency_ms": None, "photon_reason": "not_measured",
            "steady_state_excludes_first_s": 5,
            "sample_limit": self.max_samples, "received_spans": self._received,
            "retained_spans": len(self._spans), "sample_overflow": self._overflow,
            "quantile_population": "first_bounded_samples" if self._overflow else "retained_samples",
            "reported_dropped_frames": self._dropped,
            "reported_overwritten_frames": self._overwritten,
            "drop_accounting": "caller_reported_not_driver_verified",
            "phases": phases,
        }


@dataclass(frozen=True)
class SessionReceipt:
    """Future operator observations, not execution or admission authority.

    None means unobserved. These fields are never filled by a template factory.
    Boolean attestations do not prove network state, telemetry absence or rights.
    """

    session_number: Literal[1, 2, 3]
    requested_duration_s: int = 60
    actual_duration_s: float | None = None
    actual_width: int | None = None
    actual_height: int | None = None
    actual_source_fps: float | None = None
    actual_processed_fps: float | None = None
    source_frames: int | None = None
    processed_frames: int | None = None
    dropped_frames: int | None = None
    overwritten_frames: int | None = None
    initialization_ms: float | None = None
    offline_fps: float | None = None
    permission_denial_observed: bool | None = None
    invalid_index_observed: bool | None = None
    no_retry_spin_observed: bool | None = None
    stop_release_observed: bool | None = None
    second_app_open_observed: bool | None = None
    prior_settings_restored_observed: bool | None = None
    offline_verified_observed: bool | None = None
    offline_receipt_sha256: str | None = None
    supported: bool | None = None

    def __post_init__(self) -> None:
        if type(self.session_number) is not int or self.session_number not in (1, 2, 3):
            raise ValueError("invalid_session_number")
        if type(self.requested_duration_s) is not int or self.requested_duration_s != 60:
            raise ValueError("invalid_requested_duration")
        for name in ("actual_duration_s", "actual_source_fps", "actual_processed_fps",
                     "initialization_ms", "offline_fps"):
            value = getattr(self, name)
            if value is not None and (not _finite(value) or value < 0):
                raise ValueError("invalid_session_observation")
        for name in ("actual_width", "actual_height", "source_frames", "processed_frames",
                     "dropped_frames", "overwritten_frames"):
            value = getattr(self, name)
            if value is not None:
                _count(value)
                if name in ("actual_width", "actual_height") and value == 0:
                    raise ValueError("invalid_session_dimensions")
        for name in ("permission_denial_observed", "invalid_index_observed", "no_retry_spin_observed",
                     "stop_release_observed", "second_app_open_observed", "prior_settings_restored_observed",
                     "offline_verified_observed", "supported"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ValueError("invalid_operator_assertion")
        if self.offline_receipt_sha256 is not None:
            _digest(self.offline_receipt_sha256)


def _digest(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid_receipt_digest")


@dataclass(frozen=True)
class DeviceProfile:
    """Aggregate-safe machine slots; identifying operator receipts stay private.

    Hardware/runtime details are committed by digests here. A separate operator
    view may describe CPU/OS/version without passing names, paths or serials to
    the public aggregate or coding-model context. Digests are not verification.
    """

    machine_slot: Literal["device_1", "device_2"]
    requested_width: int = 640
    requested_height: int = 480
    physical_distinctness_verified: bool | None = None
    os_family: Literal["windows", "macos", "linux", "other"] | None = None
    cpu_description_sha256: str | None = None
    cpu_cores: int | None = None
    ram_gib: float | None = None
    python_version: tuple[int, int, int] | None = None
    runtime_sha256: str | None = None
    model_sha256: str | None = None
    configuration_sha256: str | None = None
    cpu_delegate_confirmed: bool | None = None
    python312_deviation: bool | None = None
    deviation_receipt_sha256: str | None = None
    rights_receipt_sha256: str | None = None
    supported: bool | None = None
    sessions: tuple[SessionReceipt, ...] = ()

    def __post_init__(self) -> None:
        if self.machine_slot not in ("device_1", "device_2"):
            raise ValueError("invalid_machine_slot")
        if (type(self.requested_width) is not int or type(self.requested_height) is not int
                or (self.requested_width, self.requested_height) != (640, 480)):
            raise ValueError("invalid_requested_resolution")
        if self.os_family not in (None, "windows", "macos", "linux", "other"):
            raise ValueError("invalid_os_family")
        for name in ("cpu_description_sha256", "runtime_sha256", "model_sha256", "configuration_sha256",
                     "deviation_receipt_sha256", "rights_receipt_sha256"):
            value = getattr(self, name)
            if value is not None:
                _digest(value)
        if self.cpu_cores is not None and (type(self.cpu_cores) is not int or self.cpu_cores <= 0):
            raise ValueError("invalid_cpu_cores")
        if self.ram_gib is not None and (not _finite(self.ram_gib) or self.ram_gib <= 0):
            raise ValueError("invalid_ram")
        if self.python_version is not None and (type(self.python_version) is not tuple or len(self.python_version) != 3
                or any(type(v) is not int or v < 0 for v in self.python_version)):
            raise ValueError("invalid_python_version")
        if type(self.sessions) is not tuple or len(self.sessions) > 3 or any(type(s) is not SessionReceipt for s in self.sessions):
            raise ValueError("invalid_session_receipts")
        if len({s.session_number for s in self.sessions}) != len(self.sessions):
            raise ValueError("duplicate_session_receipt")
        for name in ("physical_distinctness_verified", "cpu_delegate_confirmed", "python312_deviation", "supported"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ValueError("invalid_operator_assertion")

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "observation_status": "unverified_operator_receipts",
                "receipt_trust_limit": "assertions_and_digests_are_not_independent_verification"}


def device_profile_templates() -> dict[str, object]:
    """Unpopulated protocol parameters; not a claim of two available machines."""
    return {
        "heading": "2 devices, not a device survey",
        "status": "unverified_not_run",
        "physical_distinctness": None,
        "devices": [DeviceProfile(slot, sessions=tuple(SessionReceipt(n) for n in (1, 2, 3))).to_dict()
                    for slot in ("device_1", "device_2")],
    }

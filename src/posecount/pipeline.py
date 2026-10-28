"""Bounded source controller; inert until explicitly called by an operator.

No label access, fitting, model acquisition or custody orchestration lives here.
Receipt fields are trusted operator assertions, never cryptographic consent proof.
"""

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path, PureWindowsPath
from typing import Callable

from .counter import Counter
from .geometry import GeometryAdapter
from .landmarks import FrameBatch, LandmarkSource
from .schema import CounterConfig, Prediction, attach_evidence
from .tuning import FitAuthorization, WindowInput, require_sha256


@dataclass(frozen=True)
class SourceAdmission:
    corpus: str
    trace_hash: str | None = None
    window_key: tuple[str, str, str] | None = None
    provenance_receipt: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    native_offline_receipt: str | None = None
    private_boundary_receipt: str | None = None
    authorization: FitAuthorization | None = None

    def require(self, window: WindowInput | None) -> None:
        if self.corpus == "development":
            if window is not None or any(value is not None for value in (
                self.trace_hash, self.window_key, self.provenance_receipt,
                self.verified_by, self.verified_at, self.native_offline_receipt,
                self.private_boundary_receipt, self.authorization,
            )):
                raise PermissionError("development_cannot_use_study_receipts")
            return
        if (self.corpus != "real_dev" or type(window) is not WindowInput
                or window.corpus != "real_dev" or self.window_key != window.key
                or self.trace_hash != window.trace_hash
                or type(self.authorization) is not FitAuthorization):
            raise PermissionError("admitted_real_dev_source_required")
        self.authorization.require_people((window.person_id,))
        for value in (self.trace_hash, self.provenance_receipt, self.native_offline_receipt,
                      self.private_boundary_receipt):
            require_sha256(value)
        if not all(isinstance(v, str) and v.strip() for v in (self.verified_by, self.verified_at)):
            raise PermissionError("operator_source_verification_required")


@dataclass(frozen=True)
class CounterRequest:
    arm: str
    config: CounterConfig


@dataclass(frozen=True, repr=False)
class HeldoutSourceAdmission:
    """Separate consumed-attempt capability; never a real-dev FitAuthorization.

    The host callback must freshly validate the exact consumed attempt, pins,
    extracted state, window bytes, consent, offline and private boundaries.
    An attempt ID or hash without this required callback grants no access.
    """

    window: WindowInput
    attempt_pins_hash: str
    provenance_receipt: str
    native_offline_receipt: str
    private_boundary_receipt: str
    verify_current: Callable[[], bool]

    @property
    def corpus(self) -> str:
        return "real_heldout"

    @property
    def trace_hash(self) -> str:
        return self.window.trace_hash

    def require(self, window: WindowInput | None) -> None:
        if (type(window) is not WindowInput or window != self.window
                or window.corpus != "real_heldout" or not callable(self.verify_current)):
            raise PermissionError("bound_consumed_attempt_required")
        for value in (window.trace_hash, self.attempt_pins_hash, self.provenance_receipt,
                      self.native_offline_receipt, self.private_boundary_receipt):
            require_sha256(value)
        try:
            allowed = self.verify_current() is True
        except Exception:
            allowed = False
        if not allowed:
            raise PermissionError("current_consumed_attempt_verification_required")


@dataclass(frozen=True)
class SourceResult:
    predictions: tuple[Prediction, ...]
    source_class: str
    source_status: str
    source_reason: str | None
    cleanup_status: str
    frame_count: int
    visibility_score: float | None
    trace_hash: str | None
    provenance_receipt: str | None
    runtime_verified: bool = False


def run_source(source_factory: Callable[[], LandmarkSource], requests: tuple[CounterRequest, ...],
               *, admission: SourceAdmission | HeldoutSourceAdmission,
               window: WindowInput | None = None) -> SourceResult:
    """Open one fresh source once, dispatch identical geometry to every arm.

    The factory opens/prepares its returned source. Admission is checked BEFORE
    calling it; a provider must verify bytes/rights/offline/private boundaries before
    returning the admission assertion. Held-out access requires the separate
    consumed-attempt capability; a real-dev authorization cannot grant it.
    No frame, timestamp, clock anchor or hash is synthesized or verified by us.
    """
    if type(admission) not in (SourceAdmission, HeldoutSourceAdmission):
        raise PermissionError("typed_source_admission_required")
    admission.require(window)
    if (type(requests) is not tuple or not requests or len(requests) > 128
            or any(type(r) is not CounterRequest for r in requests)):
        raise ValueError("bounded_counter_requests_required")
    counters = tuple(Counter(r.config, arm=r.arm,
                             window_id="" if window is None else window.window_id,
                             trace_hash=admission.trace_hash) for r in requests)
    geometry = GeometryAdapter()
    source: LandmarkSource | None = None
    frames = 0
    visibility_sum = 0.0
    scored_frames = 0
    reason = None
    cleanup = "not_opened"
    try:
        source = source_factory()
        if source is None:
            raise ValueError("source_missing")
        cleanup = "pending"
        # One extra read detects a broken provider ignoring its own frame limit.
        for index in range(7202):
            batch = source.read()
            if batch is None:
                break
            if index >= 7201 or type(batch) is not FrameBatch:
                raise ValueError("source_limit_or_schema")
            if admission.corpus == "development":
                if (batch.source_kind not in {"synthetic", "fixture"}
                        or not batch.source_id.startswith("development-")):
                    raise PermissionError("development_source_required")
            elif batch.source_kind not in {"video", "camera"}:
                raise PermissionError("real_dev_source_provenance_mismatch")
            frames += 1
            for output in geometry.update(batch):
                values = output.bridge_kwargs()
                frame = output.angle_frame if values is None else attach_evidence(
                    output.angle_frame, **values)
                if output.phase == "scored":
                    visibility_sum += sum(frame.visibility) / 3
                    scored_frames += 1
                for counter in counters:
                    counter.update(frame)
        geometry.finish()
    except Exception:
        # Closed taxonomy: exception text may contain private paths/identities.
        reason = "source_error"
        for counter in counters:
            counter.source_error()
    finally:
        if source is not None:
            try:
                source.close()
                cleanup = "closed"
            except Exception:
                cleanup = "close_error"
                reason = "source_error"
                for counter in counters:
                    counter.source_error()
    predictions = tuple(counter.finish() for counter in counters)
    # Old/unconfigured arm facades must never mask a source failure as not_run.
    if reason is not None:
        predictions = tuple(replace(p, status="error", final_count=None) for p in predictions)
    return SourceResult(predictions, admission.corpus,
                        "error" if reason else "complete", reason, cleanup, frames,
                        visibility_sum / scored_frames if scored_frames else None,
                        admission.trace_hash, admission.provenance_receipt)


@dataclass(frozen=True)
class DevelopmentAggregate:
    """Public allowlist boundary; no identifiers, events, coordinates or paths."""

    source_class: str
    arm: str
    status: str
    emitted_events: int
    filtered_count: int | None
    runtime_verified: bool = False
    study_admitted: bool = False
    accuracy: None = None
    coverage: None = None
    calibration: None = None
    headline: None = None
    measurement_status: str = "not_run_no_independent_truth"

    def __post_init__(self) -> None:
        if (self.source_class not in {"development_landmarks", "development_scalar", "development_generated"}
                or self.arm not in {"Z", "A0", "A0v", "A1", "A2-H"}
                or self.status not in {"answered", "abstain", "error", "not_run", "calibration_unavailable"}
                or type(self.emitted_events) is not int or self.emitted_events < 0
                or (self.filtered_count is None and self.status != "error")
                or (self.status == "error" and self.filtered_count is not None)
                or (self.filtered_count is not None and (
                    type(self.filtered_count) is not int or self.filtered_count < 0))
                or self.runtime_verified is not False or self.study_admitted is not False
                or any(v is not None for v in (self.accuracy, self.coverage, self.calibration, self.headline))
                or self.measurement_status != "not_run_no_independent_truth"):
            raise ValueError("unverified_development_aggregate_required")


def development_aggregate(prediction: Prediction, *, source_class: str) -> DevelopmentAggregate:
    if source_class not in {"development_landmarks", "development_scalar", "development_generated"}:
        raise ValueError("development_aggregate_only")
    return DevelopmentAggregate(source_class, prediction.arm, prediction.status,
                                sum(event.emitted for event in prediction.events),
                                None if prediction.status == "error" else prediction.filtered_count)


def _plain_output_path(path: Path) -> Path:
    windows_path = PureWindowsPath(path)
    # A suffix alone admits NTFS alternate streams (file:stream.json). Device
    # names can bypass ordinary file semantics even with an apparent extension.
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved |= {f"{prefix}{n}" for prefix in ("COM", "LPT") for n in "123456789¹²³"}
    components = windows_path.parts[1:] if windows_path.anchor else windows_path.parts
    if ((windows_path.drive and (not windows_path.root or len(windows_path.drive) != 2
                                or windows_path.drive[1] != ":"
                                or not windows_path.drive[0].isascii()
                                or not windows_path.drive[0].isalpha()))
            or any(any(ord(c) < 32 or c in ':*?"<>|' for c in part)
                   or part.endswith((".", " "))
                   or part.split(".", 1)[0].rstrip(" ").upper() in reserved for part in components)):
        raise ValueError("plain_json_output_path_required")
    target = Path(path).absolute()
    if any(p.is_symlink() or p.is_junction() for p in (target, *target.parents)):
        raise ValueError("plain_output_path_required")
    if not target.parent.is_dir():
        raise ValueError("existing_output_directory_required")
    return target


def write_development_aggregate(path: Path, aggregate: DevelopmentAggregate) -> None:
    """Future exclusive JSON export; no labels, truth metrics or identifiers."""
    if type(aggregate) is not DevelopmentAggregate:
        raise ValueError("development_aggregate_required")
    target = _plain_output_path(path)
    if target.suffix.lower() != ".json":
        raise ValueError("plain_json_output_path_required")
    payload = json.dumps(asdict(aggregate), allow_nan=False, sort_keys=True, indent=2) + "\n"
    with target.open("x", encoding="utf-8") as stream:
        stream.write(payload)


def write_unmeasured_report(directory: Path) -> str:
    """Actual integrated aggregate-only API, kept lazy at the output boundary.

    Never converts development predictions into a measured bundle or calls the
    private evaluator. Partial artifacts on later failure stay for disposition.
    """
    target = _plain_output_path(directory)
    if target.exists():
        raise FileExistsError("fresh_report_directory_required")
    try:
        from .report import bundle_hash, unmeasured_bundle, write_artifacts
    except ImportError:
        return "report_source_unavailable"
    bundle = unmeasured_bundle()
    write_artifacts(target, bundle, expected_bundle_hash=bundle_hash(bundle))
    return "written_unmeasured_report"

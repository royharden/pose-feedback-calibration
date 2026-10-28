"""Aggregate-only sealed report source; rendering never evaluates detectors/data.

No reports, metrics, scans or file writes occur at import. Public fields use
closed vocabularies: arbitrary participant labels/paths/media cannot be injected.
"""

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
from html import escape
import json
from math import isfinite
from pathlib import Path
import re


ARMS = ("Z", "A0", "A0v", "A1", "A2-H", "A2")
METRICS = frozenset((
    "exercise_coverage overall_coverage answered_mae answered_exact answered_obo end_to_end_exact "
    "exposed_fc_per_minute retained_fc_per_minute filtered_negative_count negative_scheduled_minutes "
    "emitted_negative_events retained_negative_events answered_positive_predicted_count_sum "
    "answered_positive_truth_count_sum worst_person_fc_per_minute event_precision event_recall event_f1 "
    "event_tp event_fp event_fn mean_confirmation_lag_seconds mean_media_display_lag_seconds "
    "brier prior_brier ece aurc visibility_wrong_auroc visibility_wrong_auroc_interval_low "
    "visibility_wrong_auroc_interval_high confident_wrong confident_wrong_rate failure_annotation_coverage "
    "delta_fc delta_mae person_macro_fc person_macro_mae sign_flip_p a0_subset_mae a2_subset_mae "
    "bin_mean_probability bin_observed_exact cpu_seconds paid_cost"
).split())
SUPPORTS = frozenset((
    "people scheduled scoreable scheduled_positive scheduled_negative scoreable_positive scoreable_negative "
    "answered_scoreable answered_positive unscoreable hard_invalid truth_event_windows status_answered "
    "status_abstain status_error status_unscoreable status_calibration_unavailable status_not_run "
    "calibration_eligible calibration_ineligible risk_coverage_eligible confident_answers "
    "failure_taxonomy_tagged_windows unclassified_failure_windows failure_event_truth_unavailable_windows"
).split())
REASONS = frozenset((
    "unmeasured not_measured unavailable zero_denominator nonfinite_result no_scoreable_positives no_scoreable_windows "
    "no_answered_scoreable_positives no_scheduled_positives no_scheduled_negative_exposure "
    "filtered_count_unavailable no_answered_positives person_negative_exposure_unavailable "
    "truth_event_support_unavailable no_emitted_events display_media_clock_domains_differ "
    "probability_not_defined_for_arm ranking_diagnostic_not_defined_for_arm interval_not_computed "
    "no_calibration_eligible_rows probability_unavailable no_calibration_support no_ranking_support "
    "empty_calibration_bin same_training_prior_unavailable no_prior_support visibility_ranking_unavailable "
    "degenerate_wrong_count_classes answered_probability_unavailable no_confident_answers "
    "no_classifiable_failure_support nonfinite_ratio scheduled_negative_exposure_unavailable "
    "A2_answered_positive_subset_empty A0_subset_nonanswer subset_empty nonfinite_interval undefined_draws "
    "point_or_draw_support_unavailable exact_sign_flip_support_out_of_bounds sign_flip_support_unavailable "
    "person_FC_unavailable person_MAE_unavailable"
).split())
FAILED_GATES = frozenset((
    "unmeasured real_held_out edition_matches_receipts at_least_eight_people admission freeze custody "
    "qualified_oof final_map positive_deltaFC sign_flip_p_below_0_05 both_FC_intervals_available "
    "both_FC_lower_bounds_positive exercise_coverage_at_least_0_60 same_answered_subset_available "
    "both_MAE_intervals_available both_MAE_upper_bounds_nonpositive calibrated_A2_available"
    " complete_scheduled_census scheduled_manifest_verified"
).split())
CLAIM_TEXT = {
    "unmeasured": "Not yet measured; no outcome or advantage is claimed.",
    "useful_counter": "fewer displayed non-exercise false counts without worse matched-subset counting in this pilot",
    "false_counts_only": "fewer displayed false counts but no demonstrated useful counting advantage in this pilot",
    "unavailable": "no demonstrated advantage in this pilot; required comparison unavailable",
    "no_demonstrated_advantage": "no demonstrated advantage in this pilot",
}


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _finite(value: object) -> bool:
    return type(value) in (int, float) and isfinite(value)


def _count(value: object) -> bool:
    return type(value) is int and value >= 0


@dataclass(frozen=True)
class PublicMetric:
    name: str
    value: float | None
    reason: str | None
    numerator: float | None = None
    denominator: float | None = None


@dataclass(frozen=True)
class PublicBin:
    lower: float
    upper: float
    support: int
    mean_probability: PublicMetric
    observed_exact: PublicMetric


@dataclass(frozen=True)
class PublicRiskPoint:
    coverage: float
    risk: float
    support: int


@dataclass(frozen=True)
class PublicArm:
    corpus: str
    split: str
    edition_hash: str
    arm: str
    support: tuple[tuple[str, int], ...]
    metrics: tuple[PublicMetric, ...]
    calibration_bins: tuple[PublicBin, ...] = ()
    risk_points: tuple[PublicRiskPoint, ...] = ()
    failure_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class PublicInterval:
    name: str
    estimate: float | None
    low: float | None
    high: float | None
    draws: int
    seed: int
    undefined_draws: int
    status: str
    reason: str | None
    conditional_low: float | None = None
    conditional_high: float | None = None


@dataclass(frozen=True)
class PublicComparison:
    corpus: str
    split: str
    edition_hash: str
    people: int
    metrics: tuple[PublicMetric, ...]
    intervals: tuple[PublicInterval, ...]
    same_subset_available: bool
    a2_available: bool


@dataclass(frozen=True)
class WordingDisposition:
    hit_hash: str
    decision: str
    nonbuilder_receipt: str | None


TIMING_STAGES = ("preprocess_ms", "inference_ms", "counter_update_ms", "render_ms", "capture_to_render_ms")
TIMING_PHASES = ("init_warmup", "steady_state", "unclassified")
TIMING_UNKNOWN_REASONS = frozenset((
    "missing_anchor invalid_anchor missing_time nonfinite_time invalid_nanoseconds clock_domain_mismatch "
    "missing_clock_scope invalid_clock_scope clock_scope_mismatch reversed_time nonfinite_duration unknown"
).split())
SESSION_STOP_REASONS = frozenset((
    "end_of_stream operator_stop session_deadline session_deadline_after_read session_deadline_after_render "
    "renderer_stop frame_limit interrupted session_not_authorized invalid_session_source_kind "
    "real_processing_receipts_missing camera_unavailable camera_read_failed device_open_unavailable "
    "device_read_failed session_source_kind_mismatch invalid_read_receipt invalid_render_receipt "
    "session_clock_invalid invalid_backend_frame_count standing_reference_unavailable source_failed "
    "session_failed cleanup_failed"
).split())
SESSION_COUNTS = frozenset((
    "final_count provisional_count presentation_receipts source_frames processed_frames source_unavailable_slots "
    "backend_dropped backend_overwritten slot_overwritten controller_dropped failed_source_reads"
).split())
DEVICE_COUNTS = frozenset(("cpu_cores",))
DEVICE_NUMBERS = frozenset(("ram_gib",))
DEVICE_ASSERTIONS = frozenset(("physical_distinctness_verified", "cpu_delegate_confirmed", "python312_deviation", "supported"))
DEVICE_DIGESTS = frozenset((
    "cpu_description_sha256 runtime_sha256 model_sha256 configuration_sha256 deviation_receipt_sha256 rights_receipt_sha256"
).split())
RECEIPT_COUNTS = frozenset(("actual_width", "actual_height", "source_frames", "processed_frames", "dropped_frames", "overwritten_frames"))
RECEIPT_NUMBERS = frozenset(("actual_duration_s", "actual_source_fps", "actual_processed_fps", "initialization_ms", "offline_fps"))
RECEIPT_ASSERTIONS = frozenset((
    "permission_denial_observed invalid_index_observed no_retry_spin_observed stop_release_observed "
    "second_app_open_observed prior_settings_restored_observed offline_verified_observed supported"
).split())


@dataclass(frozen=True)
class TimingObservation:
    source_kind: str
    source_sha256: str
    status: str
    operator_receipt_sha256: str | None = None


@dataclass(frozen=True)
class PublicTimingStage:
    name: str
    unit: str
    valid_count: int
    unknown_count: int
    unknown_reasons: tuple[tuple[str, int], ...]
    p50: float | None
    p95: float | None
    p99: float | None
    reason: str | None


@dataclass(frozen=True)
class PublicTimingPhase:
    name: str
    span_count: int
    stages: tuple[PublicTimingStage, ...]


@dataclass(frozen=True)
class PublicTimingSummary:
    clock_domain: str
    measurement_boundary: str
    photon_latency_ms: None
    photon_reason: str
    steady_state_excludes_first_s: int
    sample_limit: int
    received_spans: int
    retained_spans: int
    sample_overflow: int
    quantile_population: str
    reported_dropped_frames: int | None
    reported_overwritten_frames: int | None
    drop_accounting: str
    phases: tuple[PublicTimingPhase, ...]


@dataclass(frozen=True)
class PublicObservationValue:
    name: str
    value: float | int | None


@dataclass(frozen=True)
class PublicAssertion:
    name: str
    value: bool | None


@dataclass(frozen=True)
class PublicSessionTiming:
    status: str
    stop_reason: str
    prediction_status: str
    counts: tuple[PublicObservationValue, ...]
    backend_counts_reason: str | None
    cleanup_errors: tuple[str, ...]
    initialization_ms: float | None
    initialization_reason: str | None
    timing_boundary: str
    sensor_exposure_ms: None = None
    display_photon_ms: None = None
    live_stream_parity: None = None


@dataclass(frozen=True)
class PublicDeviceSession:
    session_number: int
    requested_duration_s: int
    observations: tuple[PublicObservationValue, ...]
    assertions: tuple[PublicAssertion, ...]
    offline_receipt_sha256: str | None


@dataclass(frozen=True)
class PublicDeviceProfile:
    machine_slot: str
    requested_width: int
    requested_height: int
    os_family: str | None
    python_version: tuple[int, int, int] | None
    observations: tuple[PublicObservationValue, ...]
    assertions: tuple[PublicAssertion, ...]
    digests: tuple[tuple[str, str | None], ...]
    sessions: tuple[PublicDeviceSession, ...]
    observation_status: str
    receipt_trust_limit: str


@dataclass(frozen=True)
class PublicDeviceProtocol:
    heading: str
    status: str
    physical_distinctness: None
    devices: tuple[PublicDeviceProfile, ...]


@dataclass(frozen=True)
class PublicTimingReport:
    schema_version: int
    observation: TimingObservation
    summary: PublicTimingSummary
    session: PublicSessionTiming | None
    device_protocol: PublicDeviceProtocol


def _bounded_count(value: object, *, maximum: int = 1_000_000) -> bool:
    return _count(value) and value <= maximum


def _observations(values: tuple[PublicObservationValue, ...], counts: frozenset[str],
                  numbers: frozenset[str], *, nullable: frozenset[str] | None = None) -> dict[str, float | int | None]:
    if type(values) is not tuple or any(type(v) is not PublicObservationValue for v in values):
        raise ValueError("immutable_timing_observations_required")
    result = {v.name: v.value for v in values}
    if len(result) != len(values) or set(result) != counts | numbers:
        raise ValueError("unknown_or_missing_timing_observation")
    for name, value in result.items():
        if value is None:
            if nullable is not None and name not in nullable:
                raise ValueError("required_timing_count_missing")
        elif name in counts:
            if not _bounded_count(value):
                raise ValueError("invalid_timing_count")
        elif not _finite(value) or not 0 <= value <= 1_000_000_000:
            raise ValueError("invalid_timing_measurement")
    return result


def _assertions(values: tuple[PublicAssertion, ...], names: frozenset[str]) -> bool:
    if type(values) is not tuple or any(type(v) is not PublicAssertion for v in values):
        raise ValueError("immutable_operator_assertions_required")
    if len({v.name for v in values}) != len(values) or {v.name for v in values} != names:
        raise ValueError("unknown_or_missing_operator_assertion")
    if any(v.value is not None and type(v.value) is not bool for v in values):
        raise ValueError("invalid_operator_assertion")
    return any(v.value is not None for v in values)


def validate_timing_report(value: PublicTimingReport) -> None:
    if type(value) is not PublicTimingReport or type(value.schema_version) is not int or value.schema_version != 1:
        raise ValueError("typed_timing_schema_v1_required")
    observation = value.observation
    if (type(observation) is not TimingObservation
            or observation.source_kind not in {"span_writer_summary", "session_result_aggregate"}
            or not _sha(observation.source_sha256)
            or observation.status not in {"unmeasured", "incomplete", "operator_reported"}
            or (observation.operator_receipt_sha256 is not None and not _sha(observation.operator_receipt_sha256))):
        raise ValueError("invalid_timing_source_observation")
    if observation.status != "unmeasured" and observation.operator_receipt_sha256 is None:
        raise ValueError("timing_operator_receipt_required")
    summary = value.summary
    if (type(summary) is not PublicTimingSummary or summary.clock_domain != "process_monotonic_ns"
            or summary.measurement_boundary != "capture_return_to_render_return_or_enqueue"
            or summary.photon_latency_ms is not None or summary.photon_reason != "not_measured"
            or type(summary.steady_state_excludes_first_s) is not int or summary.steady_state_excludes_first_s != 5
            or not _bounded_count(summary.sample_limit, maximum=7201) or summary.sample_limit == 0):
        raise ValueError("invalid_timing_boundary")
    if (not all(_bounded_count(v) for v in (summary.received_spans, summary.retained_spans, summary.sample_overflow))
            or summary.retained_spans > summary.sample_limit
            or summary.received_spans != summary.retained_spans + summary.sample_overflow
            or summary.quantile_population != ("first_bounded_samples" if summary.sample_overflow else "retained_samples")):
        raise ValueError("invalid_timing_sample_accounting")
    for count in (summary.reported_dropped_frames, summary.reported_overwritten_frames):
        if count is not None and not _bounded_count(count):
            raise ValueError("invalid_backend_count")
    unknown_backend = summary.reported_dropped_frames is None or summary.reported_overwritten_frames is None
    if summary.drop_accounting != ("source_backend_uninstrumented" if unknown_backend else "caller_reported_not_driver_verified"):
        raise ValueError("invalid_backend_count_provenance")
    if (type(summary.phases) is not tuple or any(type(p) is not PublicTimingPhase for p in summary.phases)
            or tuple(p.name for p in summary.phases) != TIMING_PHASES
            or any(not _bounded_count(p.span_count, maximum=7201) for p in summary.phases)
            or sum(p.span_count for p in summary.phases) != summary.retained_spans):
        raise ValueError("invalid_timing_phases")
    for phase in summary.phases:
        if (not _bounded_count(phase.span_count, maximum=7201) or type(phase.stages) is not tuple
                or any(type(stage) is not PublicTimingStage for stage in phase.stages)
                or tuple(stage.name for stage in phase.stages) != TIMING_STAGES):
            raise ValueError("invalid_timing_phase_support")
        for stage in phase.stages:
            if (stage.unit != "ms" or not _bounded_count(stage.valid_count, maximum=7201)
                    or not _bounded_count(stage.unknown_count, maximum=7201)
                    or stage.valid_count + stage.unknown_count != phase.span_count
                    or type(stage.unknown_reasons) is not tuple
                    or any(type(pair) is not tuple or len(pair) != 2 for pair in stage.unknown_reasons)):
                raise ValueError("invalid_stage_support")
            reasons = dict(stage.unknown_reasons)
            if (len(reasons) != len(stage.unknown_reasons) or any(name not in TIMING_UNKNOWN_REASONS
                    or not _bounded_count(count, maximum=7201) or count == 0 for name, count in reasons.items())
                    or sum(reasons.values()) != stage.unknown_count):
                raise ValueError("invalid_stage_unknown_reasons")
            quantiles = (stage.p50, stage.p95, stage.p99)
            if stage.valid_count == 0:
                if quantiles != (None, None, None) or stage.reason != "no_valid_samples":
                    raise ValueError("empty_stage_requires_null_quantiles")
            elif (stage.reason is not None or any(not _finite(q) or not 0 <= q <= 1_000_000_000 for q in quantiles)
                  or not stage.p50 <= stage.p95 <= stage.p99):
                raise ValueError("invalid_stage_quantiles")
    has_observations = summary.received_spans != 0
    session = value.session
    if (observation.source_kind == "session_result_aggregate") != (session is not None):
        raise ValueError("timing_source_kind_mismatch")
    if session is not None:
        if (type(session) is not PublicSessionTiming or session.status not in {"completed", "stopped", "timeout", "error"}
                or session.stop_reason not in SESSION_STOP_REASONS
                or session.prediction_status not in {"answered", "abstain", "error", "not_run", "calibration_unavailable"}
                or session.backend_counts_reason not in {None, "source_backend_uninstrumented"}
                or type(session.cleanup_errors) is not tuple
                or len(session.cleanup_errors) > 2 or len(set(session.cleanup_errors)) != len(session.cleanup_errors)
                or any(code not in {"renderer_close_failed", "source_close_failed"} for code in session.cleanup_errors)
                or session.timing_boundary != "capture-return to imshow return/render enqueue only"
                or any(v is not None for v in (session.sensor_exposure_ms, session.display_photon_ms, session.live_stream_parity))):
            raise ValueError("invalid_session_aggregate")
        counts = _observations(session.counts, SESSION_COUNTS, frozenset(),
                               nullable=frozenset(("final_count", "backend_dropped", "backend_overwritten")))
        if (counts["source_frames"] != counts["processed_frames"] + counts["controller_dropped"]
                or summary.received_spans != counts["source_frames"] + counts["failed_source_reads"]
                or counts["backend_dropped"] != summary.reported_dropped_frames
                or counts["backend_overwritten"] != summary.reported_overwritten_frames
                or session.backend_counts_reason != ("source_backend_uninstrumented" if unknown_backend else None)):
            raise ValueError("session_frame_or_backend_accounting_mismatch")
        if any(v is not None and v > 7201 for v in counts.values()):
            raise ValueError("session_frame_count_limit")
        if session.prediction_status != "answered" and counts["final_count"] is not None:
            raise ValueError("nonanswer_session_count_must_be_null")
        if session.prediction_status == "answered" and (counts["final_count"] is None
                or counts["final_count"] > counts["provisional_count"]):
            raise ValueError("answered_session_count_requires_emitted_support")
        if session.initialization_ms is None:
            if session.initialization_reason != "initialization_incomplete":
                raise ValueError("missing_initialization_reason")
        elif (not _finite(session.initialization_ms) or not 0 <= session.initialization_ms <= 1_000_000_000
              or session.initialization_reason is not None):
            raise ValueError("invalid_initialization_observation")
        has_observations = True  # Even a failed session is not an unrun template.
    protocol = value.device_protocol
    if (type(protocol) is not PublicDeviceProtocol or protocol.heading != "2 devices, not a device survey"
            or protocol.status != "unverified_not_run" or protocol.physical_distinctness is not None
            or type(protocol.devices) is not tuple or len(protocol.devices) != 2
            or any(type(device) is not PublicDeviceProfile for device in protocol.devices)
            or tuple(device.machine_slot for device in protocol.devices) != ("device_1", "device_2")):
        raise ValueError("invalid_two_device_protocol")
    for device in protocol.devices:
        if ((type(device.requested_width), type(device.requested_height)) != (int, int)
                or (device.requested_width, device.requested_height) != (640, 480)
                or device.os_family not in {None, "windows", "macos", "linux", "other"}
                or device.observation_status != "unverified_operator_receipts"
                or device.receipt_trust_limit != "assertions_and_digests_are_not_independent_verification"
                or type(device.digests) is not tuple
                or any(type(pair) is not tuple or len(pair) != 2 for pair in device.digests)):
            raise ValueError("invalid_device_metadata")
        observations = _observations(device.observations, DEVICE_COUNTS, DEVICE_NUMBERS)
        if any(v is not None and v <= 0 for v in observations.values()):
            raise ValueError("invalid_positive_device_measurement")
        if device.python_version is not None and (type(device.python_version) is not tuple or len(device.python_version) != 3
                or any(not _bounded_count(part, maximum=10000) for part in device.python_version)):
            raise ValueError("invalid_python_version")
        digests = dict(device.digests)
        if len(digests) != len(device.digests) or set(digests) != DEVICE_DIGESTS or any(
            digest is not None and not _sha(digest) for digest in digests.values()
        ):
            raise ValueError("invalid_device_receipt_commitment")
        has_observations |= (_assertions(device.assertions, DEVICE_ASSERTIONS)
                             or device.os_family is not None or device.python_version is not None
                             or any(v is not None for v in (*observations.values(), *digests.values())))
        if (type(device.sessions) is not tuple or any(type(s) is not PublicDeviceSession for s in device.sessions)
                or any(type(s.session_number) is not int for s in device.sessions)
                or tuple(s.session_number for s in device.sessions) != (1, 2, 3)):
            raise ValueError("three_protocol_session_slots_required")
        for receipt in device.sessions:
            if type(receipt.requested_duration_s) is not int or receipt.requested_duration_s != 60:
                raise ValueError("invalid_requested_session_duration")
            values = _observations(receipt.observations, RECEIPT_COUNTS, RECEIPT_NUMBERS)
            if any(values[name] == 0 for name in ("actual_width", "actual_height") if values[name] is not None):
                raise ValueError("invalid_observed_dimensions")
            if receipt.offline_receipt_sha256 is not None and not _sha(receipt.offline_receipt_sha256):
                raise ValueError("invalid_offline_receipt")
            has_observations |= (_assertions(receipt.assertions, RECEIPT_ASSERTIONS)
                                 or any(v is not None for v in values.values()) or receipt.offline_receipt_sha256 is not None)
    if observation.status == "unmeasured" and (has_observations
            or summary.reported_dropped_frames not in (None, 0) or summary.reported_overwritten_frames not in (None, 0)):
        raise ValueError("unmeasured_timing_cannot_contain_observations")
    if timing_source_sha256(value) != observation.source_sha256:
        raise ValueError("exact_timing_aggregate_source_seal_mismatch")


def timing_source_sha256(value: PublicTimingReport) -> str:
    """Canonical producer packet from a structurally validated immutable DTO.

    Used by EVERY timing validation ingress, including JSON hydration/rendering;
    never import the evaluator/producer or invoke a timing/device operation.
    """
    summary, protocol, session = value.summary, value.device_protocol, value.session
    source_summary = asdict(summary)
    source_summary["phases"] = {
        phase.name: {"span_count": phase.span_count, "stages": {
            stage.name: {name: item for name, item in asdict(stage).items() if name != "name"}
            for stage in phase.stages
        }} for phase in summary.phases
    }
    for phase in source_summary["phases"].values():
        for stage in phase["stages"].values():
            stage["unknown_reasons"] = dict(stage["unknown_reasons"])
    source_devices = []
    for device in protocol.devices:
        raw = {name: getattr(device, name) for name in (
            "machine_slot", "requested_width", "requested_height", "os_family", "python_version",
            "observation_status", "receipt_trust_limit",
        )}
        raw.update((item.name, item.value) for item in (*device.observations, *device.assertions))
        raw.update(device.digests)
        raw["sessions"] = [{"session_number": receipt.session_number,
                            "requested_duration_s": receipt.requested_duration_s,
                            "offline_receipt_sha256": receipt.offline_receipt_sha256,
                            **{item.name: item.value for item in (*receipt.observations, *receipt.assertions)}}
                           for receipt in device.sessions]
        source_devices.append(raw)
    source_protocol = {"heading": protocol.heading, "status": protocol.status,
                       "physical_distinctness": protocol.physical_distinctness, "devices": source_devices}
    source_aggregate = source_summary
    if session is not None:
        source_aggregate = {name: item for name, item in asdict(session).items() if name != "counts"}
        source_aggregate.update((item.name, item.value) for item in session.counts)
        source_aggregate["timing"] = source_summary
    packet = {"source_kind": value.observation.source_kind, "aggregate": source_aggregate,
              "device_profiles": source_protocol}
    return sha256(json.dumps(packet, sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResultBundle:
    """Public aggregate DTO, containing no private row/label/path/name fields."""

    state: str
    source_seal: str | None
    arms: tuple[PublicArm, ...]
    comparison: PublicComparison | None
    claim_category: str
    failed_gates: tuple[str, ...]
    lower_error: bool = False
    calibration_attribution: bool = False
    device_state: str = "unmeasured"
    wording: tuple[WordingDisposition, ...] = ()
    timing: PublicTimingReport | None = None


def _metric(metric: PublicMetric) -> None:
    if type(metric) is not PublicMetric or metric.name not in METRICS:
        raise ValueError("unknown_public_metric")
    if metric.reason is not None and metric.reason not in REASONS:
        raise ValueError("unknown_public_reason")
    if metric.value is None and metric.reason is None:
        raise ValueError("null_requires_reason")
    for value in (metric.value, metric.numerator, metric.denominator):
        if value is not None and not _finite(value):
            raise ValueError("nonfinite_public_metric")
    if metric.denominator is not None and metric.denominator < 0:
        raise ValueError("negative_denominator")


def validate_bundle(bundle: ResultBundle) -> None:
    if type(bundle) is not ResultBundle or bundle.state not in {"unmeasured", "measured", "incomplete"}:
        raise ValueError("typed_aggregate_bundle_required")
    if bundle.source_seal is not None and not _sha(bundle.source_seal):
        raise ValueError("invalid_source_seal")
    if bundle.state != "unmeasured" and bundle.source_seal is None:
        raise ValueError("measured_source_seal_required")
    if bundle.timing is not None:
        validate_timing_report(bundle.timing)
        if bundle.timing.observation.status != "unmeasured" and (
            bundle.state == "unmeasured" or bundle.device_state != "incomplete"
        ):
            raise ValueError("reported_timing_requires_explicit_incomplete_observation_state")
    if bundle.claim_category not in CLAIM_TEXT or bundle.device_state not in {"unmeasured", "incomplete"}:
        raise ValueError("unsupported_claim_or_device_state")
    if type(bundle.lower_error) is not bool or type(bundle.calibration_attribution) is not bool:
        raise ValueError("explicit_claim_flags_required")
    if bundle.lower_error and bundle.claim_category != "useful_counter":
        raise ValueError("lower_error_requires_full_useful_counter_gate")
    if bundle.calibration_attribution and bundle.claim_category not in {"useful_counter", "false_counts_only"}:
        raise ValueError("calibration_benefit_requires_supported_benefit_category")
    if bundle.claim_category in {"useful_counter", "false_counts_only"} and (
        bundle.state != "measured" or bundle.comparison is None
        or bundle.comparison.corpus != "real" or bundle.comparison.split != "held_out"
        or not bundle.comparison.a2_available
    ):
        raise ValueError("benefit_requires_measured_real_held_out_comparison")
    if bundle.claim_category == "useful_counter" and bundle.failed_gates:
        raise ValueError("failed_gates_cannot_support_useful_counter_claim")
    if bundle.state == "unmeasured" and (bundle.arms or bundle.comparison is not None
            or bundle.claim_category != "unmeasured" or bundle.lower_error or bundle.calibration_attribution):
        raise ValueError("unmeasured_cannot_contain_measurements_or_claims")
    for field in (bundle.arms, bundle.failed_gates, bundle.wording):
        if type(field) is not tuple:
            raise ValueError("immutable_public_fields_required")
    if any(code not in FAILED_GATES for code in bundle.failed_gates):
        raise ValueError("unknown_public_gate")
    seen = set()
    for arm in bundle.arms:
        if (type(arm) is not PublicArm or arm.corpus not in {"synthetic", "real"}
                or arm.split not in {"dev", "held_out", "regression"} or arm.arm not in ARMS or not _sha(arm.edition_hash)):
            raise ValueError("invalid_public_arm_identity")
        key = (arm.corpus, arm.split, arm.edition_hash, arm.arm)
        if key in seen:
            raise ValueError("duplicate_public_arm")
        seen.add(key)
        if any(type(values) is not tuple for values in (
            arm.support, arm.metrics, arm.calibration_bins, arm.risk_points, arm.failure_counts
        )):
            raise ValueError("immutable_public_arm_required")
        if len(dict(arm.support)) != len(arm.support) or len({m.name for m in arm.metrics}) != len(arm.metrics):
            raise ValueError("duplicate_public_support_or_metric")
        for name, count in arm.support:
            if name not in SUPPORTS or not _count(count):
                raise ValueError("unknown_public_support")
        if any(type(pair) is not tuple or len(pair) != 2 for pair in (*arm.support, *arm.failure_counts)):
            raise ValueError("immutable_public_pairs_required")
        for metric in arm.metrics:
            _metric(metric)
        for bin_row in arm.calibration_bins:
            if (type(bin_row) is not PublicBin or not _finite(bin_row.lower) or not _finite(bin_row.upper)
                    or not 0 <= bin_row.lower < bin_row.upper <= 1 or not _count(bin_row.support)):
                raise ValueError("invalid_public_bin")
            _metric(bin_row.mean_probability)
            _metric(bin_row.observed_exact)
        for point in arm.risk_points:
            if (type(point) is not PublicRiskPoint or not _finite(point.coverage) or not _finite(point.risk)
                    or not 0 <= point.coverage <= 1 or not 0 <= point.risk <= 1 or not _count(point.support)):
                raise ValueError("invalid_public_risk_curve")
        for code, count in arm.failure_counts:
            if code not in {f"F{i}" for i in range(1, 19)} or not _count(count):
                raise ValueError("unknown_public_failure_code")
    if bundle.comparison is not None:
        comparison = bundle.comparison
        if (type(comparison) is not PublicComparison or not _count(comparison.people)
                or comparison.corpus not in {"synthetic", "real"} or comparison.split not in {"dev", "held_out", "regression"}
                or not _sha(comparison.edition_hash)
                or type(comparison.same_subset_available) is not bool or type(comparison.a2_available) is not bool
                or type(comparison.metrics) is not tuple or type(comparison.intervals) is not tuple):
            raise ValueError("invalid_public_comparison")
        if (len({m.name for m in comparison.metrics}) != len(comparison.metrics)
                or len({i.name for i in comparison.intervals}) != len(comparison.intervals)):
            raise ValueError("duplicate_public_comparison_field")
        if any((comparison.corpus, comparison.split, comparison.edition_hash, arm) not in seen
               for arm in ("A0", "A2")):
            raise ValueError("comparison_requires_matching_A0_A2_support")
        for metric in comparison.metrics:
            _metric(metric)
        for interval in comparison.intervals:
            if (type(interval) is not PublicInterval or interval.name not in {
                "primary_fc", "primary_mae", "sensitivity_fc", "sensitivity_mae"
            } or interval.status not in {"available", "unavailable"}
                    or not _count(interval.draws) or not _count(interval.seed)
                    or not _count(interval.undefined_draws) or interval.undefined_draws > interval.draws):
                raise ValueError("invalid_public_interval")
            if interval.reason is not None and interval.reason not in REASONS:
                raise ValueError("unknown_public_interval_reason")
            if interval.status == "unavailable" and interval.reason is None:
                raise ValueError("unavailable_interval_requires_reason")
            for value in (interval.estimate, interval.low, interval.high,
                          interval.conditional_low, interval.conditional_high):
                if value is not None and not _finite(value):
                    raise ValueError("nonfinite_public_interval")
            if interval.status == "available" and (
                interval.low is None or interval.high is None or interval.low > interval.high
                or interval.undefined_draws != 0
            ):
                raise ValueError("unsupported_available_interval")
    for disposition in bundle.wording:
        if (type(disposition) is not WordingDisposition or not _sha(disposition.hit_hash)
                or disposition.decision not in {"pending", "approved_disclaimer", "rejected_claim"}
                or (disposition.nonbuilder_receipt is not None and not _sha(disposition.nonbuilder_receipt))):
            raise ValueError("invalid_wording_disposition")
        if disposition.decision == "approved_disclaimer" and disposition.nonbuilder_receipt is None:
            raise ValueError("nonbuilder_wording_receipt_required")


def payload(bundle: ResultBundle) -> dict[str, object]:
    validate_bundle(bundle)
    result = asdict(bundle)
    # Absence is the original public schema/canonical identity. Merely upgrading
    # the source must not change existing no-timing bundle hashes.
    if bundle.timing is None:
        result.pop("timing")
    return result


def canonical_json(bundle: ResultBundle) -> str:
    return json.dumps(payload(bundle), sort_keys=True, allow_nan=False, separators=(",", ":"))


def bundle_hash(bundle: ResultBundle) -> str:
    return sha256(canonical_json(bundle).encode("utf-8")).hexdigest()


def unmeasured_bundle() -> ResultBundle:
    return ResultBundle("unmeasured", None, (), None, "unmeasured", ("unmeasured",))


def load_bundle_json(text: str, *, expected_bundle_hash: str) -> ResultBundle:
    """Hydrate ONLY the closed aggregate schema, then verify canonical identity.

    No private-row loader, evaluator or arbitrary class import is reachable here.
    A later report re-render can survive process restart without reevaluation.
    """
    if type(text) is not str or len(text.encode("utf-8")) > 4 * 1024 * 1024 or not _sha(expected_bundle_hash):
        raise ValueError("invalid_bounded_aggregate_json_input")

    def reject_constant(_value: str) -> None:
        raise ValueError("nonfinite_json_constant")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("duplicate_aggregate_json_field")
            result[name] = value
        return result

    def record(kind: type, value: object) -> dict[str, object]:
        names = {field.name for field in fields(kind)}
        if kind is ResultBundle and type(value) is dict and set(value) == names - {"timing"}:
            return {**value, "timing": None}  # Explicit original-schema compatibility.
        if type(value) is not dict or set(value) != names:
            raise ValueError("unknown_or_missing_aggregate_json_field")
        return dict(value)

    def array(value: object) -> list[object]:
        if type(value) is not list:
            raise ValueError("aggregate_json_array_required")
        return value

    def pairs(value: object) -> tuple[tuple[object, object], ...]:
        result = []
        for item in array(value):
            if type(item) is not list or len(item) != 2:
                raise ValueError("aggregate_json_pair_required")
            result.append(tuple(item))
        return tuple(result)

    def metric(value: object) -> PublicMetric:
        return PublicMetric(**record(PublicMetric, value))

    def observations(value: object) -> tuple[PublicObservationValue, ...]:
        return tuple(PublicObservationValue(**record(PublicObservationValue, item)) for item in array(value))

    def assertions(value: object) -> tuple[PublicAssertion, ...]:
        return tuple(PublicAssertion(**record(PublicAssertion, item)) for item in array(value))

    def timing_report(value: object) -> PublicTimingReport:
        data = record(PublicTimingReport, value)
        data["observation"] = TimingObservation(**record(TimingObservation, data["observation"]))
        summary = record(PublicTimingSummary, data["summary"])
        phases = []
        for value_phase in array(summary["phases"]):
            phase = record(PublicTimingPhase, value_phase)
            stages = []
            for value_stage in array(phase["stages"]):
                stage = record(PublicTimingStage, value_stage)
                stage["unknown_reasons"] = pairs(stage["unknown_reasons"])
                stages.append(PublicTimingStage(**stage))
            phase["stages"] = tuple(stages)
            phases.append(PublicTimingPhase(**phase))
        summary["phases"] = tuple(phases)
        data["summary"] = PublicTimingSummary(**summary)
        if data["session"] is not None:
            session = record(PublicSessionTiming, data["session"])
            session["counts"] = observations(session["counts"])
            session["cleanup_errors"] = tuple(array(session["cleanup_errors"]))
            data["session"] = PublicSessionTiming(**session)
        protocol = record(PublicDeviceProtocol, data["device_protocol"])
        devices = []
        for value_device in array(protocol["devices"]):
            device = record(PublicDeviceProfile, value_device)
            if device["python_version"] is not None:
                device["python_version"] = tuple(array(device["python_version"]))
            device["observations"] = observations(device["observations"])
            device["assertions"] = assertions(device["assertions"])
            device["digests"] = pairs(device["digests"])
            sessions = []
            for value_session in array(device["sessions"]):
                receipt = record(PublicDeviceSession, value_session)
                receipt["observations"] = observations(receipt["observations"])
                receipt["assertions"] = assertions(receipt["assertions"])
                sessions.append(PublicDeviceSession(**receipt))
            device["sessions"] = tuple(sessions)
            devices.append(PublicDeviceProfile(**device))
        protocol["devices"] = tuple(devices)
        data["device_protocol"] = PublicDeviceProtocol(**protocol)
        return PublicTimingReport(**data)

    try:
        data = record(ResultBundle, json.loads(text, parse_constant=reject_constant,
                                               object_pairs_hook=unique_object))
        arms = []
        for value in array(data["arms"]):
            arm = record(PublicArm, value)
            arm["support"] = pairs(arm["support"])
            arm["metrics"] = tuple(metric(item) for item in array(arm["metrics"]))
            bins = []
            for value_bin in array(arm["calibration_bins"]):
                bin_row = record(PublicBin, value_bin)
                bin_row["mean_probability"] = metric(bin_row["mean_probability"])
                bin_row["observed_exact"] = metric(bin_row["observed_exact"])
                bins.append(PublicBin(**bin_row))
            arm["calibration_bins"] = tuple(bins)
            arm["risk_points"] = tuple(PublicRiskPoint(**record(PublicRiskPoint, item))
                                         for item in array(arm["risk_points"]))
            arm["failure_counts"] = pairs(arm["failure_counts"])
            arms.append(PublicArm(**arm))
        data["arms"] = tuple(arms)
        if data["comparison"] is not None:
            comparison = record(PublicComparison, data["comparison"])
            comparison["metrics"] = tuple(metric(item) for item in array(comparison["metrics"]))
            comparison["intervals"] = tuple(PublicInterval(**record(PublicInterval, item))
                                               for item in array(comparison["intervals"]))
            data["comparison"] = PublicComparison(**comparison)
        data["failed_gates"] = tuple(array(data["failed_gates"]))
        data["wording"] = tuple(WordingDisposition(**record(WordingDisposition, item))
                                   for item in array(data["wording"]))
        if data["timing"] is not None:
            data["timing"] = timing_report(data["timing"])
        bundle = ResultBundle(**data)
        validate_bundle(bundle)
    except (ValueError, TypeError, OverflowError, RecursionError, KeyError) as exc:
        raise ValueError("invalid_aggregate_json") from exc
    if bundle_hash(bundle) != expected_bundle_hash:
        raise ValueError("sealed_bundle_mismatch")
    return bundle


def _value(metric: PublicMetric) -> str:
    text = json.dumps(metric.value, allow_nan=False)
    return escape(text + (" — " + metric.reason if metric.reason else ""), quote=True)


def render_svg(bundle: ResultBundle) -> str:
    validate_bundle(bundle)
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="760" height="' + str(60 + 36 * len(bundle.arms))
             + '" role="img"><title>Exercise coverage by corpus, split and arm</title>']
    for index, arm in enumerate(bundle.arms):
        label = f"{arm.corpus} / {arm.split} / {arm.arm}"
        metric = next((m for m in arm.metrics if m.name == "exercise_coverage"), None)
        value = None if metric is None else metric.value
        if value is not None and not 0 <= value <= 1:
            raise ValueError("coverage_out_of_bounds")
        y = 30 + 36 * index
        lines.append(f'<text x="8" y="{y}">{escape(label, quote=True)}</text>')
        if value is None:
            lines.append(f'<text x="300" y="{y}">unavailable</text>')
        else:
            lines.append(f'<rect x="300" y="{y - 16}" width="{360 * value}" height="20" fill="#3478aa"/>')
    lines.append('</svg>')
    return "".join(lines)


def render_timing_html(timing: PublicTimingReport) -> str:
    """Display copied aggregate values only; no stage/statistics reexecution."""
    validate_timing_report(timing)

    def number(value: float | int | bool | None) -> str:
        return escape(json.dumps(value, allow_nan=False), quote=True)

    summary = timing.summary
    html = ['<section><h2>Host timing aggregates</h2>',
            '<p>Observation state: ' + escape(timing.observation.status) + '. Source: ' +
            escape(timing.observation.source_kind) + '. Operator receipts are assertions, not independent verification.</p>',
            '<p>Capture-return to render-return/enqueue only. Sensor exposure and display photons: null (not measured).</p>',
            '<table><tr><th>Received spans</th><th>Retained</th><th>Overflow</th><th>Backend drops</th><th>Backend overwrites</th><th>Accounting</th></tr>',
            '<tr><td>' + number(summary.received_spans) + '</td><td>' + number(summary.retained_spans) +
            '</td><td>' + number(summary.sample_overflow) + '</td><td>' + number(summary.reported_dropped_frames) +
            '</td><td>' + number(summary.reported_overwritten_frames) + '</td><td>' + escape(summary.drop_accounting) + '</td></tr></table>',
            '<table><tr><th>Phase</th><th>Stage (ms)</th><th>Valid</th><th>Unknown</th><th>p50</th><th>p95</th><th>p99</th><th>Unavailable reasons</th></tr>']
    for phase in summary.phases:
        for stage in phase.stages:
            html.append('<tr><td>' + escape(phase.name) + '</td><td>' + escape(stage.name) + '</td><td>' +
                        number(stage.valid_count) + '</td><td>' + number(stage.unknown_count) + '</td><td>' +
                        number(stage.p50) + '</td><td>' + number(stage.p95) + '</td><td>' + number(stage.p99) +
                        '</td><td>' + escape(json.dumps(stage.unknown_reasons, allow_nan=False)) +
                        ('; ' + escape(stage.reason) if stage.reason else '') + '</td></tr>')
    html.append('</table>')
    if timing.session is not None:
        session = timing.session
        html.append('<h3>Session aggregate — ' + escape(session.status) + ' / ' + escape(session.stop_reason) + '</h3>')
        html.append('<table><tr><th>Count</th><th>Value</th></tr>')
        html.extend('<tr><td>' + escape(item.name) + '</td><td>' + number(item.value) + '</td></tr>' for item in session.counts)
        html.append('</table><p>Initialization ms: ' + number(session.initialization_ms) +
                    '; reason: ' + escape(session.initialization_reason or 'none') + '</p>')
    html.append('<h2>2 devices, not a device survey</h2><p>Two protocol slots and three requested sessions each do not establish two observed or physically distinct devices. Native/offline/human independence remains unverified.</p>')
    for device in timing.device_protocol.devices:
        html.append('<h3>' + escape(device.machine_slot) + ' — requested ' + str(device.requested_width) + '×' + str(device.requested_height) + '</h3>')
        html.append('<table><tr><th>Operator-reported device field</th><th>Value</th></tr>')
        html.extend('<tr><td>' + escape(item.name) + '</td><td>' + number(item.value) + '</td></tr>'
                    for item in (*device.observations, *device.assertions))
        html.append('</table>')
        for receipt in device.sessions:
            html.append('<h4>Session ' + str(receipt.session_number) + ' — requested60s; observations below are not inferred</h4>')
            html.append('<table><tr><th>Operator-reported observation/assertion</th><th>Value</th></tr>')
            html.extend('<tr><td>' + escape(item.name) + '</td><td>' + number(item.value) + '</td></tr>'
                        for item in (*receipt.observations, *receipt.assertions))
            html.append('</table>')
    html.append('</section>')
    return '\n'.join(html)


def render_html(bundle: ResultBundle) -> str:
    data = payload(bundle)  # Same validated values used by JSON; no metric recomputation.
    statement = CLAIM_TEXT[bundle.claim_category]
    if bundle.lower_error:
        statement += "; lower matched-subset count error in this pilot"
    html = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>M17 aggregate report</title>',
            '<body><h1>M17 aggregate report</h1><p>' + escape(bundle.state) + '</p>',
            '<p>' + escape(statement) + '</p><p>Attribution: ' +
            ('whole gated counter with separately evidenced A2-H calibration ablation'
             if bundle.calibration_attribution else 'whole gated counter') + '</p>',
            '<p>2 devices, not a device survey — ' + escape(bundle.device_state) + '</p>',
            '<p>Pretrained landmark inference; owned temporal/evaluation engineering. Pilot only.</p>',
            '<p>Conditional interval bounds are descriptive only. Any undefined draw makes its headline interval unavailable.</p>',
            '<!-- disclaimer:start -->',
            '<p>No coaching, form grading, medical, injury or exercise-safety advice. Sensor exposure and display photons unknown.</p>',
            '<!-- disclaimer:end -->']
    for arm in bundle.arms:
        html.append('<section><h2>' + escape(f"{arm.corpus} / {arm.split} / {arm.arm}") + '</h2>')
        html.append('<p>Edition commitment: ' + escape(arm.edition_hash) + '</p><table><tr><th>Support</th><th>Count</th></tr>')
        html.extend('<tr><td>' + escape(name) + '</td><td>' + str(count) + '</td></tr>' for name, count in arm.support)
        html.append('</table><table><tr><th>Metric</th><th>Value / unavailable reason</th></tr>')
        html.extend('<tr><td>' + escape(metric.name) + '</td><td>' + _value(metric) + '</td></tr>' for metric in arm.metrics)
        html.append('</table><p>Failure taxonomy counts represent supplied annotations; unclassified support remains visible.</p></section>')
    if bundle.timing is not None:
        html.append(render_timing_html(bundle.timing))
    html.append(render_svg(bundle))
    # JSON is rendered as escaped TEXT, never an executable script/template block.
    html.append('<h2>Complete aggregate values, supports, bins, intervals and failed gates</h2><pre>' +
                escape(json.dumps(data, sort_keys=True, allow_nan=False, indent=2), quote=True) + '</pre>')
    html.append('<p>Publication and independent verification require separate approval; this file is no sign-off.</p></body></html>')
    return "\n".join(html)


@dataclass(frozen=True)
class WordingHit:
    code: str
    content_hash: str
    disclaimer: bool


def scan_wording(text: str) -> tuple[WordingHit, ...]:
    """Private-source scanner only; a disclaimer hit still needs disposition."""
    hits = []
    in_disclaimer = False
    patterns = {
        "medical": r"\bmedical\w*\b|\binjur\w*\b",
        # Deliberately broad: wording order ("grade depth", "depth is rated")
        # must not bypass disposition. A human classifies claims vs non-goals.
        "form": r"\bform\b",
        "depth": r"\bdepth\b",
        "tempo": r"\btempo\b",
        "appearance": r"\bappearance\b",
        "safety": r"\bexercise[- ]safety\b|\bsafe to exercise\b",
        "coaching": r"\bcoach(?:ing|es|ed)?\b",
    }
    for line in text.splitlines():
        if "<!-- disclaimer:start -->" in line:
            in_disclaimer = True
        for code, pattern in patterns.items():
            if re.search(pattern, line, re.IGNORECASE):
                hits.append(WordingHit(code, sha256(line.encode()).hexdigest(),
                                       in_disclaimer or line.lstrip().startswith("Disclaimer:")))
        if "<!-- disclaimer:end -->" in line:
            in_disclaimer = False
    return tuple(hits)


def wording_release_ready(hits: tuple[WordingHit, ...], dispositions: tuple[WordingDisposition, ...]) -> bool:
    by_hash = {d.hit_hash: d for d in dispositions}
    if len(by_hash) != len(dispositions):
        return False
    return all(hit.disclaimer and hit.content_hash in by_hash
               and by_hash[hit.content_hash].decision == "approved_disclaimer"
               and _sha(by_hash[hit.content_hash].nonbuilder_receipt) for hit in hits)


def check_readme_metrics(text: str, expected: dict[str, float | None]) -> tuple[str, ...]:
    """Exact machine-readable metric:id markers; all other numbers are ignored.

    Marker grammar: <!-- metric:id --> JSON-number-or-null <!-- /metric:id -->.
    Returns closed mismatch codes, never raw lines/paths/participant strings.
    """
    if any(name not in METRICS or (value is not None and not _finite(value)) for name, value in expected.items()):
        raise ValueError("invalid_expected_metric")
    found = {}
    problems = []
    pattern = r"<!-- metric:([a-zA-Z0-9_]+) -->\s*(.*?)\s*<!-- /metric:\1 -->"
    matches = re.findall(pattern, text, re.DOTALL)
    if text.count("<!-- metric:") != len(matches):
        problems.append("malformed_metric_marker")
    for name, raw in matches:
        if name in found:
            problems.append("duplicate_metric_marker")
        try:
            value = json.loads(raw)
            if value is not None and not _finite(value):
                raise ValueError("invalid numeric marker")
            found[name] = value
        except (ValueError, TypeError, OverflowError):
            problems.append("invalid_metric_marker")
    if set(found) != set(expected):
        problems.append("missing_or_unexpected_metric_marker")
    if any(value != found.get(name) for name, value in expected.items()):
        problems.append("metric_marker_value_mismatch")
    return tuple(problems)


def write_artifacts(directory: Path, bundle: ResultBundle, *, expected_bundle_hash: str) -> tuple[Path, ...]:
    """Later explicit output step; new artifacts only, no overwrite/delete/publish."""
    if not _sha(expected_bundle_hash) or bundle_hash(bundle) != expected_bundle_hash:
        raise ValueError("sealed_bundle_mismatch")
    artifacts = (("report.json", canonical_json(bundle)), ("report.html", render_html(bundle)),
                 ("coverage.svg", render_svg(bundle)))
    directory.mkdir(parents=True, exist_ok=True)
    if any((directory / name).exists() for name, _ in artifacts):
        raise FileExistsError("report_artifacts_already_exist")
    paths = []
    for name, content in artifacts:
        path = directory / name
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        paths.append(path)
    return tuple(paths)

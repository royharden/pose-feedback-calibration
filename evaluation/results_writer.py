"""Private evaluator aggregates -> closed public report DTO; no data reexecution."""

from dataclasses import replace
from hashlib import sha256
from typing import Iterable

from posecount.report import (
    PublicArm, PublicBin, PublicComparison, PublicInterval, PublicMetric,
    PublicRiskPoint, ResultBundle, validate_bundle,
    TimingObservation, PublicTimingStage, PublicTimingPhase, PublicTimingSummary,
    PublicObservationValue, PublicAssertion, PublicSessionTiming, PublicDeviceSession,
    PublicDeviceProfile, PublicDeviceProtocol, PublicTimingReport, validate_timing_report,
    TIMING_PHASES, TIMING_STAGES, SESSION_COUNTS, DEVICE_COUNTS, DEVICE_NUMBERS,
    DEVICE_ASSERTIONS, DEVICE_DIGESTS, RECEIPT_COUNTS, RECEIPT_NUMBERS, RECEIPT_ASSERTIONS,
)
from .metrics import ArmMetrics, Metric
from .stats import Claim, Comparison, Interval


def edition_hash(edition: str) -> str:
    if not isinstance(edition, str) or not edition:
        raise ValueError("edition_commitment_input_required")
    # Public output never carries the possibly private human edition alias.
    return sha256(edition.encode("utf-8")).hexdigest()


def public_metric(name: str, metric: Metric) -> PublicMetric:
    if type(metric) is not Metric:
        raise ValueError("typed_metric_required")
    return PublicMetric(name, metric.value, metric.reason, metric.numerator, metric.denominator)


def public_arm(aggregate: ArmMetrics) -> PublicArm:
    if type(aggregate) is not ArmMetrics:
        raise ValueError("aggregate_metrics_required_not_private_rows")
    return PublicArm(aggregate.corpus, aggregate.split, edition_hash(aggregate.edition), aggregate.arm,
                     aggregate.support,
                     (*tuple(public_metric(name, metric) for name, metric in aggregate.metrics),
                      PublicMetric("cpu_seconds", None, "unmeasured"),
                      PublicMetric("paid_cost", None, "unmeasured")),
                     tuple(PublicBin(row.lower, row.upper, row.support,
                                     public_metric("bin_mean_probability", row.mean_probability),
                                     public_metric("bin_observed_exact", row.observed_exact))
                           for row in aggregate.calibration_bins),
                     tuple(PublicRiskPoint(row.coverage, row.risk, row.support) for row in aggregate.risk_points),
                     aggregate.failure_counts)


def public_interval(name: str, interval: Interval) -> PublicInterval:
    if type(interval) is not Interval:
        raise ValueError("typed_interval_required")
    return PublicInterval(name, interval.estimate, interval.low, interval.high, interval.draws,
                          interval.seed, interval.undefined_draws, interval.status, interval.reason,
                          interval.conditional_low, interval.conditional_high)


def public_comparison(comparison: Comparison) -> PublicComparison:
    if type(comparison) is not Comparison:
        raise ValueError("aggregate_comparison_required")
    names = ("delta_fc", "delta_mae", "person_macro_fc", "person_macro_mae", "sign_flip_p",
             "a0_subset_mae", "a2_subset_mae")
    intervals = ("primary_fc", "primary_mae", "sensitivity_fc", "sensitivity_mae")
    return PublicComparison(comparison.corpus, comparison.split, edition_hash(comparison.edition),
                            comparison.people, tuple(public_metric(name, getattr(comparison, name)) for name in names),
                            tuple(public_interval(name, getattr(comparison, name)) for name in intervals),
                            comparison.same_subset_available, comparison.a2_available)


def with_auc_interval(aggregate: ArmMetrics, interval: Interval) -> ArmMetrics:
    if aggregate.arm != "A1":
        raise ValueError("visibility_AUROC_diagnostic_is_A1_only")
    additions = {
        "visibility_wrong_auroc_interval_low": Metric(interval.low, interval.reason),
        "visibility_wrong_auroc_interval_high": Metric(interval.high, interval.reason),
    }
    return replace(aggregate, metrics=tuple((name, additions.get(name, metric)) for name, metric in aggregate.metrics))


def build_bundle(aggregates: Iterable[ArmMetrics], *, comparison: Comparison,
                 claim: Claim, source_seal: str, state: str = "measured") -> ResultBundle:
    rows = tuple(aggregates)
    if (type(claim) is not Claim or any(type(row) is not ArmMetrics for row in rows)
            or {(row.corpus, row.split, row.edition) for row in rows} != {
                (comparison.corpus, comparison.split, comparison.edition)
            }):
        raise ValueError("one_matching_aggregate_corpus_split_edition_required")
    # Claim wording comes from the selector's closed category, never arbitrary text.
    bundle = ResultBundle(state, source_seal, tuple(public_arm(row) for row in rows),
                          public_comparison(comparison), claim.category, claim.failed_gates,
                          claim.lower_error,
                          claim.attribution == "whole_gated_counter_with_A2-H_calibration_ablation")
    validate_bundle(bundle)
    return bundle


def _closed(value: object, names: set[str] | frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != names:
        raise ValueError("unknown_or_missing_aggregate_source_field")
    return value


def _sequence(value: object) -> tuple[object, ...]:
    if type(value) not in (tuple, list):
        raise ValueError("aggregate_source_sequence_required")
    return tuple(value)


def _observations(raw: dict[str, object], names: set[str] | frozenset[str]) -> tuple[PublicObservationValue, ...]:
    return tuple(PublicObservationValue(name, raw[name]) for name in sorted(names))


def _assertions(raw: dict[str, object], names: frozenset[str]) -> tuple[PublicAssertion, ...]:
    return tuple(PublicAssertion(name, raw[name]) for name in sorted(names))


def timing_report(*, span_summary: dict[str, object] | None = None,
                  session_aggregate: dict[str, object] | None = None,
                  device_profiles: dict[str, object], source_sha256: str,
                  observation_status: str, operator_receipt_sha256: str | None = None) -> PublicTimingReport:
    """Copy ONLY current producer aggregate schemas; no producer is called here.

    source_sha256 binds canonical JSON of {source_kind, aggregate, device_profiles}.
    Caller/operator verifies the real source and receipt; a hash cannot attest a
    camera run, native offline state, two machines, rights or independent humans.
    """
    if (span_summary is None) == (session_aggregate is None):
        raise ValueError("exactly_one_timing_aggregate_source_required")
    source_kind = "span_writer_summary" if span_summary is not None else "session_result_aggregate"
    session = None
    if session_aggregate is not None:
        raw_session = _closed(session_aggregate, SESSION_COUNTS | {
            "status", "stop_reason", "prediction_status", "backend_counts_reason", "cleanup_errors", "timing",
            "initialization_ms", "initialization_reason", "timing_boundary", "sensor_exposure_ms",
            "display_photon_ms", "live_stream_parity",
        })
        raw_summary = raw_session["timing"]
        session = PublicSessionTiming(raw_session["status"], raw_session["stop_reason"], raw_session["prediction_status"],
                                      _observations(raw_session, SESSION_COUNTS), raw_session["backend_counts_reason"],
                                      _sequence(raw_session["cleanup_errors"]), raw_session["initialization_ms"],
                                      raw_session["initialization_reason"], raw_session["timing_boundary"],
                                      raw_session["sensor_exposure_ms"], raw_session["display_photon_ms"],
                                      raw_session["live_stream_parity"])
    else:
        raw_summary = span_summary
    raw_summary = _closed(raw_summary, {
        "clock_domain", "measurement_boundary", "photon_latency_ms", "photon_reason", "steady_state_excludes_first_s",
        "sample_limit", "received_spans", "retained_spans", "sample_overflow", "quantile_population",
        "reported_dropped_frames", "reported_overwritten_frames", "drop_accounting", "phases",
    })
    raw_phases = _closed(raw_summary["phases"], set(TIMING_PHASES))
    phases = []
    for phase_name in TIMING_PHASES:
        phase = _closed(raw_phases[phase_name], {"span_count", "stages"})
        raw_stages = _closed(phase["stages"], set(TIMING_STAGES))
        stages = []
        for stage_name in TIMING_STAGES:
            stage = _closed(raw_stages[stage_name], {"unit", "valid_count", "unknown_count", "unknown_reasons",
                                                   "p50", "p95", "p99", "reason"})
            if type(stage["unknown_reasons"]) is not dict:
                raise ValueError("timing_unknown_reason_counts_required")
            stages.append(PublicTimingStage(stage_name, stage["unit"], stage["valid_count"], stage["unknown_count"],
                                            tuple(sorted(stage["unknown_reasons"].items())),
                                            stage["p50"], stage["p95"], stage["p99"], stage["reason"]))
        phases.append(PublicTimingPhase(phase_name, phase["span_count"], tuple(stages)))
    summary = PublicTimingSummary(**{**raw_summary, "phases": tuple(phases)})
    raw_protocol = _closed(device_profiles, {"heading", "status", "physical_distinctness", "devices"})
    devices = []
    for raw_device in _sequence(raw_protocol["devices"]):
        device = _closed(raw_device, DEVICE_COUNTS | DEVICE_NUMBERS | DEVICE_ASSERTIONS | DEVICE_DIGESTS | {
            "machine_slot", "requested_width", "requested_height", "os_family", "python_version", "sessions",
            "observation_status", "receipt_trust_limit",
        })
        sessions = []
        for raw_receipt in _sequence(device["sessions"]):
            receipt = _closed(raw_receipt, RECEIPT_COUNTS | RECEIPT_NUMBERS | RECEIPT_ASSERTIONS | {
                "session_number", "requested_duration_s", "offline_receipt_sha256",
            })
            sessions.append(PublicDeviceSession(receipt["session_number"], receipt["requested_duration_s"],
                                                 _observations(receipt, RECEIPT_COUNTS | RECEIPT_NUMBERS),
                                                 _assertions(receipt, RECEIPT_ASSERTIONS), receipt["offline_receipt_sha256"]))
        devices.append(PublicDeviceProfile(device["machine_slot"], device["requested_width"], device["requested_height"],
                                            device["os_family"], None if device["python_version"] is None else _sequence(device["python_version"]),
                                            _observations(device, DEVICE_COUNTS | DEVICE_NUMBERS),
                                            _assertions(device, DEVICE_ASSERTIONS),
                                            tuple((name, device[name]) for name in sorted(DEVICE_DIGESTS)), tuple(sessions),
                                            device["observation_status"], device["receipt_trust_limit"]))
    protocol = PublicDeviceProtocol(raw_protocol["heading"], raw_protocol["status"],
                                    raw_protocol["physical_distinctness"], tuple(devices))
    result = PublicTimingReport(1, TimingObservation(source_kind, source_sha256, observation_status,
                                                    operator_receipt_sha256), summary, session, protocol)
    validate_timing_report(result)
    # Core validation binds this immutable source snapshot at every ingress,
    # including direct DTO validation and later closed JSON hydration/rendering.
    return result


def attach_timing(bundle: ResultBundle, *, span_summary: dict[str, object] | None = None,
                  session_aggregate: dict[str, object] | None = None,
                  device_profiles: dict[str, object], source_sha256: str,
                  observation_status: str, operator_receipt_sha256: str | None = None) -> ResultBundle:
    """Return a new bundle; native/offline/device independence stays unverified."""
    validate_bundle(bundle)
    timing = timing_report(span_summary=span_summary, session_aggregate=session_aggregate,
                           device_profiles=device_profiles, source_sha256=source_sha256,
                           observation_status=observation_status,
                           operator_receipt_sha256=operator_receipt_sha256)
    reported = observation_status != "unmeasured"
    result = replace(bundle, timing=timing, device_state="incomplete" if reported else bundle.device_state,
                     state="incomplete" if reported and bundle.state == "unmeasured" else bundle.state,
                     source_seal=source_sha256 if reported and bundle.source_seal is None else bundle.source_seal)
    validate_bundle(result)
    return result

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
    return asdict(bundle)


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
        if type(value) is not dict or set(value) != {field.name for field in fields(kind)}:
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

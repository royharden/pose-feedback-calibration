"""Private evaluator aggregates -> closed public report DTO; no data reexecution."""

from dataclasses import replace
from hashlib import sha256
from typing import Iterable

from posecount.report import (
    PublicArm, PublicBin, PublicComparison, PublicInterval, PublicMetric,
    PublicRiskPoint, ResultBundle, validate_bundle,
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

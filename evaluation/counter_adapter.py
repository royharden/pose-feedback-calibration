"""Actual P6 Evaluate callback, with no labels or label accessor argument."""

from dataclasses import dataclass
from typing import Callable

from posecount.landmarks import LandmarkSource
from posecount.pipeline import CounterRequest, SourceAdmission, SourceResult, run_source
from posecount.schema import CounterConfig
from posecount.tuning import (
    CounterRow, FitAuthorization, ParameterConfig, WindowInput,
    parameter_grid, validate_rows, validate_windows,
)


SourceFactory = Callable[[WindowInput], LandmarkSource]
VerifySource = Callable[[WindowInput, FitAuthorization], SourceAdmission]


def counter_request(config: ParameterConfig) -> CounterRequest:
    """Exact frozen grid member, including ID/keys/values; no arbitrary defaults."""
    if (type(config) is not ParameterConfig or type(config.values) is not tuple
            or any(type(pair) is not tuple or len(pair) != 2
                   or type(pair[0]) is not str or type(pair[1]) not in (int, float)
                   for pair in config.values)
            or config not in parameter_grid(config.arm)):
        raise ValueError("exact_frozen_parameter_grid_member_required")
    return CounterRequest(config.arm, CounterConfig(**dict(config.values)))


@dataclass(frozen=True)
class AdapterOutcome:
    rows: tuple[CounterRow, ...]
    sources: tuple[SourceResult, ...]


class CounterAdapter:
    """A real-dev callback for tune/run_lopo; trusted provider audit boundary.

    verify_source must check the exact trace bytes/provenance BEFORE the factory
    opens input. Merely copying WindowInput.trace_hash into a receipt is invalid.
    Closure/side-channel label isolation needs a later operator/security audit.
    """

    def __init__(self, *, authorization: FitAuthorization, source_factory: SourceFactory,
                 verify_source: VerifySource) -> None:
        if type(authorization) is not FitAuthorization:
            raise PermissionError("fit_authorization_required")
        authorization.require_people(authorization.people)
        self.authorization = authorization
        self.source_factory = source_factory
        self.verify_source = verify_source
        self.last_outcome: AdapterOutcome | None = None

    def __call__(self, config: ParameterConfig,
                 windows: tuple[WindowInput, ...]) -> tuple[CounterRow, ...]:
        return self.evaluate_many((config,), windows)[0]

    def evaluate_many(self, configs: tuple[ParameterConfig, ...],
                      windows: tuple[WindowInput, ...]) -> tuple[tuple[CounterRow, ...], ...]:
        """Future all-arm development dispatch uses the same decoded trace once.

        This does NOT reserve/open held-out editions. Custody's sealed path must
        be integrated separately before any held-out orchestration is possible.
        """
        self.last_outcome = None
        inputs = validate_windows(windows, self.authorization)
        if type(configs) is not tuple or not 1 <= len(configs) <= 128:
            raise ValueError("bounded_frozen_configs_required")
        requests = tuple(counter_request(config) for config in configs)
        by_config: list[list[CounterRow]] = [[] for _ in configs]
        results: list[SourceResult] = []
        all_rows: list[CounterRow] = []
        for window in inputs:
            try:
                admission = self.verify_source(window, self.authorization)
                if (type(admission) is not SourceAdmission
                        or admission.authorization != self.authorization):
                    raise PermissionError("source_authorization_mismatch")
                admission.require(window)
            except Exception:
                # Failed verification never opens source; retain scheduled row
                # and full negative denominator rather than silently skipping it.
                for index, config in enumerate(configs):
                    row = CounterRow(window, config.arm, "error", None, 0, False)
                    by_config[index].append(row)
                    all_rows.append(row)
                continue
            result = run_source(lambda: self.source_factory(window), requests,
                                admission=admission, window=window)
            results.append(result)
            for index, prediction in enumerate(result.predictions):
                row = CounterRow(window, prediction.arm, prediction.status,
                                 None if result.frame_count == 0 and result.source_status == "error"
                                 else prediction.filtered_count,
                                 sum(event.emitted for event in prediction.events),
                                 prediction.hard_gate, prediction.features,
                                 result.visibility_score)
                by_config[index].append(row)
                all_rows.append(row)
        rows = tuple(validate_rows(inputs, group, config.arm)
                     for group, config in zip(by_config, configs))
        self.last_outcome = AdapterOutcome(tuple(all_rows), tuple(results))
        return rows

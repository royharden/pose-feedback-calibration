"""Full-pipeline real-dev LOPO construction; no fitting at module import.

Counter evaluation is an injected typed callback. It receives only allowed
inference inputs, never labels. This audit boundary is not hostile isolation.
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable

from posecount.calibrate import FitRow, MapArtifact, fit_map
from posecount.tuning import (
    CounterRow, Evaluate, FitAuthorization, GuardedLabels, LabelRead,
    OperatingPoint, ParameterConfig, SelectionRow, WindowInput,
    nearest_visibility_policy, parameter_grid, require_sha256,
    select_operating_point, tune, validate_rows, validate_windows,
)


ARMS = ("Z", "A0", "A0v", "A1", "A2-H")


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FoldRecord:
    outer_person: str
    training_people: tuple[str, ...]
    configs: tuple[ParameterConfig, ...]
    map_artifact: MapArtifact | None
    excluded_map_rows: int
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class OOFRecord:
    window: WindowInput
    predictions: tuple[CounterRow, ...]
    probability: float | None
    prior: float | None
    fold_person: str
    map_hash: str
    config_hashes: tuple[tuple[str, str], ...]

    def arm(self, name: str) -> CounterRow:
        return next(row for row in self.predictions if row.arm == name)


@dataclass(frozen=True)
class PipelineResult:
    status: str
    reason: str | None
    folds: tuple[FoldRecord, ...]
    oof: tuple[OOFRecord, ...]
    oof_seal: str | None
    a2_point: OperatingPoint | None
    a0v_point: OperatingPoint | None
    a0v_nearest: OperatingPoint | None
    final_configs: tuple[ParameterConfig, ...]
    final_map: MapArtifact | None
    label_reads: tuple[LabelRead, ...]
    pins: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _configs(windows: tuple[WindowInput, ...], labels: GuardedLabels,
             authorization: FitAuthorization, evaluate: Evaluate) -> tuple[ParameterConfig, ...] | None:
    result = []
    for arm in ARMS:
        if arm == "Z":
            result.append(parameter_grid("Z")[0])
            continue
        tuned = tune(arm, windows, labels=labels, authorization=authorization, evaluate=evaluate)
        if tuned.status != "available" or tuned.config is None:
            return None
        result.append(tuned.config)
    return tuple(result)


def _fit(windows: tuple[WindowInput, ...], config: ParameterConfig, labels: GuardedLabels,
         authorization: FitAuthorization, evaluate: Evaluate,
         pins: tuple[tuple[str, str], ...]) -> tuple[MapArtifact, int]:
    people = tuple(sorted({w.person_id for w in windows}))
    scoped = labels.restrict(people)
    rows = validate_rows(windows, evaluate(config, windows), "A2-H")
    fit_rows = []
    for row in rows:
        gold = scoped.read(row.window, stage="fit")
        if not row.usable or not gold.scoreable:
            continue
        if row.features is None:
            raise ValueError("usable_calibration_features_missing")
        fit_rows.append(FitRow(row.window.person_id, row.window.window_id,
                               row.window.trace_hash, row.features,
                               row.filtered_count == gold.truth))
    artifact = fit_map(fit_rows, authorization=authorization, people=people,
                       pins=(*pins, ("counter_config", digest(asdict(config)))))
    return artifact, len(rows) - len(fit_rows)


def run_lopo(windows: Iterable[WindowInput], *, labels: GuardedLabels,
             authorization: FitAuthorization, evaluate: Evaluate,
             pins: tuple[tuple[str, str], ...]) -> PipelineResult:
    """Future authorized eight-dev-person pipeline; never called in Dirty work.

    Each fold tunes all arms and fits map/prior on seven people, then seals its
    outer inference without reading that person's labels. Only after the full
    OOF prediction seal do outer labels enter threshold selection. Final refit
    cannot repair an unavailable OOF map. Frozen pins are required external input.
    """
    inputs = validate_windows(windows, authorization)
    people = tuple(sorted({w.person_id for w in inputs}))
    if people != tuple(sorted(authorization.people)) or len(people) != 8:
        raise PermissionError("full_eight_person_dev_roster_required")
    pin_dict = dict(pins)
    if len(pin_dict) != len(pins) or not {"code", "model", "runtime", "protocol", "split"} <= set(pin_dict):
        raise ValueError("missing_pipeline_pins")
    if "counter_config" in pin_dict:
        raise ValueError("reserved_counter_config_pin")
    for value in pin_dict.values():
        require_sha256(value)
    folds: list[FoldRecord] = []
    oof: list[OOFRecord] = []
    maps_available = True
    for outer in people:
        training = tuple(w for w in inputs if w.person_id != outer)
        held = tuple(w for w in inputs if w.person_id == outer)
        train_people = tuple(p for p in people if p != outer)
        if len(train_people) != 7 or {w.trace_hash for w in training} & {w.trace_hash for w in held}:
            raise ValueError("LOPO_scope_overlap")
        scoped = labels.restrict(train_people)
        configs = _configs(training, scoped, authorization, evaluate)
        if configs is None:
            folds.append(FoldRecord(outer, train_people, (), None, 0, "not_run", "tuning_unavailable"))
            return PipelineResult("not_run", "tuning_unavailable", tuple(folds), tuple(oof),
                                  None, None, None, None, (), None, labels.reads, pins)
        gated = next(config for config in configs if config.arm == "A2-H")
        artifact, excluded = _fit(training, gated, scoped, authorization, evaluate, pins)
        if artifact.allowed_people != train_people:
            raise PermissionError("map_scope_mismatch")
        maps_available &= artifact.status == "available"
        predictions = {
            config.arm: {row.window.key: row for row in validate_rows(
                held, evaluate(config, held), config.arm
            )} for config in configs
        }
        for window in held:
            row = predictions["A2-H"][window.key]
            probability = (artifact.probability(row.features)
                           if row.usable and row.features is not None else None)
            oof.append(OOFRecord(window, tuple(predictions[arm][window.key] for arm in ARMS),
                                 probability, artifact.prior, outer, digest(artifact.as_dict()),
                                 tuple((c.arm, digest(asdict(c))) for c in configs)))
        folds.append(FoldRecord(outer, train_people, configs, artifact, excluded,
                                "available" if artifact.status == "available" else "calibration_unavailable",
                                artifact.reason))
    if len(oof) != len(inputs) or {row.window.key for row in oof} != {w.key for w in inputs}:
        raise ValueError("incomplete_OOF_predictions")
    # This commitment contains predictions/maps/configs, not outer truth labels.
    seal = digest([asdict(row) for row in oof])
    labels.seal_oof(seal)
    a2_rows = []
    a0v_rows = []
    for row in oof:
        gold = labels.read(row.window, stage="threshold")
        a2_rows.append(SelectionRow(row.arm("A2-H"), row.arm("A0"), gold, row.probability))
        a0v_rows.append(SelectionRow(row.arm("A0v"), row.arm("A0"), gold, None))
    a2 = select_operating_point(a2_rows, authorization=authorization, maps_available=maps_available)
    a0v = select_operating_point(a0v_rows, authorization=authorization, score="visibility")
    nearest = nearest_visibility_policy(a0v_rows, a2.coverage if a2.status != "not_run" else None,
                                         authorization=authorization)
    # All-eight refit occurs only after OOF is sealed; thresholds stay OOF-selected.
    final_configs = _configs(inputs, labels, authorization, evaluate)
    if final_configs is None:
        return PipelineResult("not_run", "final_tuning_unavailable", tuple(folds), tuple(oof),
                              seal, a2, a0v, nearest, (), None, labels.reads, pins)
    final_gated = next(config for config in final_configs if config.arm == "A2-H")
    final_map, _ = _fit(inputs, final_gated, labels, authorization, evaluate, pins)
    available = maps_available and final_map.status == "available" and a2.status != "not_run"
    status = a2.status if available else "not_run"
    reason = a2.reason if available else "OOF_or_final_calibration_unavailable"
    return PipelineResult(status, reason, tuple(folds), tuple(oof), seal, a2, a0v,
                          nearest, final_configs, final_map, labels.reads, pins)

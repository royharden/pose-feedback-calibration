"""Trusted local host bindings; no evidence, I/O or approval at import.

Private receipts/mappings never enter public DTOs. Required owner capabilities
must inspect actual evidence; a True callback is a trust assertion, not proof.
"""

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable

from posecount.custody import ALL_ARMS, AdmissionEvidence, Attempt, CustodyStore, CustodySummary, EditionPins
from posecount.calibrate import MapArtifact
from posecount.pipeline import CounterRequest, HeldoutSourceAdmission, SourceAdmission, _plain_output_path, run_source
from posecount.privacy import PrivacyPolicy
from posecount.report import (
    ResultBundle, bundle_hash, canonical_json, load_bundle_json, validate_bundle, write_artifacts,
)
from posecount.schema import Prediction, Reason
from posecount.tuning import (
    CountLabel, CounterRow, FitAuthorization, ParameterConfig, WindowInput,
    require_sha256, validate_rows,
)
from .admission import Authorize, G0Receipt, G1Receipt, VerifyReceipt, admit_g0, admit_g1, receipt_digest
from .counter_adapter import CounterAdapter, SourceFactory, counter_request
from .lopo import PipelineResult
from .matching import EventStamp
from .runner import (
    EvaluationPermission, FrozenSchedule, ScheduledWindow, from_prediction,
    gold_seal, prediction_seal, run_evaluation,
)
from .split import canonical_digest
from .stats import ClaimGates
from .results_writer import edition_hash


@dataclass(frozen=True, repr=False)
class TraceBinding:
    """Canonical G0 digest IDs, never builder-invented aliases or gold."""

    person_digest: str
    window_digest: str
    trace_sha256: str
    provenance_receipt: str
    native_offline_receipt: str
    private_boundary_receipt: str


@dataclass(frozen=True, repr=False)
class TraceManifest:
    split: str
    bindings: tuple[TraceBinding, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


def _require_true(callback: Callable, *args: object) -> None:
    try:
        allowed = callback(*args) is True
    except Exception:
        allowed = False
    if not allowed:
        raise PermissionError("trusted_host_verification_denied")


class TrustedHost:
    """Retains actual private receipt closure; does not turn hashes into rights.

    verify_current independently reconciles requested EditionPins and mapping
    against current human/rights/source/gold/consent/withdrawal records.
    verify_mapping checks actual G0 identities, split and trace byte provenance.
    verify_source checks exact trace bytes and offline/private evidence before
    access, including existing PrivacyPolicy/DeviceAuthorization safeguards.
    No callback has a permissive default; source code supplies no actual host.
    """

    def __init__(self, *, g0: G0Receipt, g1: G1Receipt, pins: EditionPins,
                 authorize: Authorize, verify_receipt: VerifyReceipt,
                 verify_current: Callable[[AdmissionEvidence, EditionPins], bool],
                 verify_mapping: Callable[[TraceManifest, G0Receipt, EditionPins], bool],
                 verify_source: Callable[[TraceBinding, EditionPins], bool],
                 approved_by: str, approved_at: str):
        if (type(g0) is not G0Receipt or type(g1) is not G1Receipt or type(pins) is not EditionPins
                or not all(callable(c) for c in (authorize, verify_receipt, verify_current,
                                                 verify_mapping, verify_source))
                or not all(isinstance(v, str) and v.strip() for v in (approved_by, approved_at))):
            raise PermissionError("explicit_trusted_host_required")
        self._g0, self._g1, self._pins = g0, g1, pins
        self._authorize, self._verify_receipt = authorize, verify_receipt
        self._verify_current, self._verify_mapping = verify_current, verify_mapping
        self._verify_source = verify_source
        self._by, self._at = approved_by, approved_at
        self._manifests: dict[str, TraceManifest] = {}

    def __repr__(self) -> str:
        return "<TrustedHost private>"

    @property
    def evidence(self) -> AdmissionEvidence:
        return AdmissionEvidence(receipt_digest(self._g0), receipt_digest(self._g1))

    def refresh(self, action: str, subject: str) -> None:
        """Fresh exact-subject operation permission AND actual G0/G1 checks."""
        _require_true(self._authorize, action, subject)
        g0 = admit_g0(self._g0, authorize=self._authorize, verify_receipt=self._verify_receipt)
        g1 = admit_g1(self._g1, self._g0, authorize=self._authorize, verify_receipt=self._verify_receipt)
        if not g0.accepted or not g1.accepted:
            raise PermissionError("current_actual_G0_G1_required")
        original = dict(self._g0.pins)
        if (self._pins.rights_hash != original["rights"] or self._pins.split_hash != original["split"]
                or self._pins.runtime_hash != original["runtime"] or self._pins.gold_hash != original["gold"]):
            raise PermissionError("current_edition_pin_closure_mismatch")
        _require_true(self._verify_current, self.evidence, self._pins)

    def manifest_windows(self, manifest: TraceManifest, *, split: str) -> tuple[WindowInput, ...]:
        if (type(manifest) is not TraceManifest or manifest.split != split
                or split not in {"dev", "heldout"} or type(manifest.bindings) is not tuple
                or len(manifest.bindings) != 96
                or any(type(b) is not TraceBinding for b in manifest.bindings)):
            raise ValueError("complete_typed_split_manifest_required")
        people = {a.person_digest for a in self._g0.split.assignments if a.split == split}
        expected = {w.window_digest: w for w in self._g0.windows if w.person_digest in people}
        if (len({b.window_digest for b in manifest.bindings}) != 96
                or {b.window_digest for b in manifest.bindings} != set(expected)
                or len({b.trace_sha256 for b in manifest.bindings}) != 96):
            raise ValueError("trace_identity_or_schedule_overlap")
        windows = []
        for binding in manifest.bindings:
            for value in asdict(binding).values():
                require_sha256(value)
            row = expected[binding.window_digest]
            if binding.person_digest != row.person_digest:
                raise ValueError("trace_person_identity_mismatch")
            windows.append(WindowInput(binding.person_digest, binding.window_digest, binding.trace_sha256,
                                       row.kind == "positive", "real_dev" if split == "dev" else "real_heldout"))
        # The host checks this mapping against actual records/bytes, not just IDs.
        _require_true(self._verify_mapping, manifest, self._g0, self._pins)
        previous = self._manifests.get(split)
        if previous is not None and previous != manifest:
            raise PermissionError("frozen_trace_manifest_changed")
        if split == "heldout":
            development = self._manifests.get("dev")
            if development is None:
                raise PermissionError("frozen_dev_manifest_required")
            if {b.trace_sha256 for b in development.bindings} & {b.trace_sha256 for b in manifest.bindings}:
                raise PermissionError("dev_heldout_trace_overlap")
        self._manifests[split] = manifest
        return tuple(windows)

    def dev_adapter(self, manifest: TraceManifest, *, source_factory: SourceFactory) -> CounterAdapter:
        self.refresh("host.bind_dev", manifest.digest)
        windows = self.manifest_windows(manifest, split="dev")
        people = tuple(sorted({w.person_id for w in windows}))
        pins = dict(self._g0.pins)
        authorization = FitAuthorization(self.evidence.g0_hash, self.evidence.g1_hash,
                                         pins["rights"], pins["roster"], self._by, self._at,
                                         people, "approved", "real_dev")
        by_key = {w.key: (w, b) for w, b in zip(windows, manifest.bindings)}

        def verify(window: WindowInput, actual: FitAuthorization) -> SourceAdmission:
            self.refresh("host.source.dev", window.trace_hash)
            if actual != authorization or window.key not in by_key or by_key[window.key][0] != window:
                raise PermissionError("source_scope_or_authorization_mismatch")
            # Recheck mapping freshness/withdrawal and bytes on EVERY access.
            self.manifest_windows(manifest, split="dev")
            binding = by_key[window.key][1]
            _require_true(self._verify_source, binding, self._pins)
            return SourceAdmission("real_dev", window.trace_hash, window.key,
                                   binding.provenance_receipt, self._by, self._at,
                                   binding.native_offline_receipt, binding.private_boundary_receipt,
                                   authorization)

        return CounterAdapter(authorization=authorization, source_factory=source_factory, verify_source=verify)


@dataclass(frozen=True, repr=False)
class PredictionRecord:
    window: WindowInput
    prediction: Prediction
    expected_config_hash: str
    probability: float | None = None
    prior: float | None = None
    visibility_score: float | None = None
    filtered_count_unknown: bool = False


@dataclass(frozen=True, repr=False)
class GoldRecord:
    label: CountLabel
    truth_events: tuple[EventStamp, ...] | None = None
    failure_codes: tuple[str, ...] = ()


class FrozenAllArmPredictor:
    """One acquired held-out trace per window, using the actual shared controller.

    Existing frozen config/map/policy artifacts must match EditionPins before
    any source opens. No tuning, fitting or label access is performed here.
    """

    def __init__(self, *, host: TrustedHost, frozen: PipelineResult, source_factory: SourceFactory,
                 verify_frozen: Callable[[PipelineResult, EditionPins], bool]):
        if (type(host) is not TrustedHost or type(frozen) is not PipelineResult
                or not callable(source_factory) or not callable(verify_frozen)):
            raise PermissionError("actual_frozen_pipeline_and_source_required")
        self._host, self._frozen, self._factory = host, frozen, source_factory
        self._verify_frozen = verify_frozen

    def __repr__(self) -> str:
        return "<FrozenAllArmPredictor private>"

    def preflight(self) -> None:
        """Validate the frozen input closure BEFORE reservation/acquisition."""
        self._host.refresh("host.edition.frozen_inference", self._host._pins.config_hash)
        frozen, pins = self._frozen, self._host._pins
        _require_true(self._verify_frozen, frozen, pins)
        development = self._host._manifests.get("dev")
        if development is None:
            raise PermissionError("frozen_dev_manifest_required_before_reservation")
        self._host.manifest_windows(development, split="dev")
        if (type(frozen.final_configs) is not tuple or len(frozen.final_configs) != 5
                or any(type(c) is not ParameterConfig for c in frozen.final_configs)):
            raise ValueError("exact_five_frozen_counter_configs_required")
        for point in (frozen.a2_point, frozen.a0v_point):
            if point is not None:
                value = point.threshold
                if ((point.status in {"available", "failed_dev_operating_point"} and value is None)
                        or (value is not None and (type(value) not in (int, float)
                            or value not in tuple(i / 20 for i in range(21))))):
                    raise ValueError("frozen_operating_point_grid_required")
        if (canonical_digest([asdict(c) for c in frozen.final_configs]) != pins.config_hash
                or canonical_digest(None if frozen.final_map is None else frozen.final_map.as_dict()) != pins.map_hash
                or canonical_digest({"a2": None if frozen.a2_point is None else asdict(frozen.a2_point),
                                     "a0v": None if frozen.a0v_point is None else asdict(frozen.a0v_point)}) != pins.threshold_hash):
            raise PermissionError("frozen_inference_pin_mismatch")
        configs = {c.arm: c for c in frozen.final_configs}
        if len(configs) != 5 or set(configs) != set(ALL_ARMS) - {"A2"}:
            raise ValueError("all_five_frozen_counter_configs_required")
        for config in frozen.final_configs:
            counter_request(config)
        artifact = frozen.final_map
        if type(artifact) is MapArtifact and artifact.status == "available":
            map_pins = dict(artifact.pins)
            if (map_pins.get("model") != pins.model_hash or map_pins.get("runtime") != pins.runtime_hash
                    or map_pins.get("split") != pins.split_hash
                    or map_pins.get("counter_config") != canonical_digest(asdict(configs["A2-H"]))):
                raise PermissionError("final_map_scope_pin_mismatch_before_reservation")

    def __call__(self, manifest: TraceManifest,
                 source_guard: Callable[[TraceBinding], None]) -> tuple[PredictionRecord, ...]:
        self.preflight()
        windows = self._host.manifest_windows(manifest, split="heldout")
        frozen, pins = self._frozen, self._host._pins
        configs = {c.arm: c for c in frozen.final_configs}
        requests = [counter_request(configs[arm]) for arm in ALL_ARMS if arm != "A2"]
        visibility = (frozen.a0v_point.threshold if frozen.a0v_point is not None
                      and frozen.a0v_point.status in {"available", "failed_dev_operating_point"} else None)
        requests = tuple(CounterRequest(r.arm, replace(r.config, visibility_threshold=visibility))
                         if r.arm == "A0v" else r for r in requests)
        development = self._host._manifests.get("dev")
        dev_people = set() if development is None else {b.person_digest for b in development.bindings}
        artifact = frozen.final_map
        point = frozen.a2_point
        calibrated = (frozen.status != "not_run" and type(artifact) is MapArtifact
                      and artifact.status == "available" and artifact.converged
                      and set(artifact.allowed_people) == dev_people and len(dev_people) == 8
                      and point is not None and point.status == "available" and point.threshold is not None
                      and len(frozen.folds) == 8 and {f.outer_person for f in frozen.folds} == dev_people
                      and all(f.map_artifact is not None and f.map_artifact.status == "available"
                              and set(f.map_artifact.allowed_people) == dev_people - {f.outer_person}
                              for f in frozen.folds)
                      and frozen.oof_seal is not None
                      and canonical_digest([asdict(r) for r in frozen.oof]) == frozen.oof_seal)
        result = []
        for window, binding in zip(windows, manifest.bindings):
            def current() -> bool:
                source_guard(binding)
                return True  # Only after the required fresh host/stage checks.
            admission = HeldoutSourceAdmission(window, pins.digest, binding.provenance_receipt,
                        binding.native_offline_receipt, binding.private_boundary_receipt, current)
            source = run_source(lambda: self._factory(window), requests, admission=admission, window=window)
            hard = next(p for p in source.predictions if p.arm == "A2-H")
            # Counter has already checked causal gates; final map/policy affects
            # whole-window answer, never erases earlier exposed events.
            probability = (artifact.probability(hard.features) if calibrated and hard.status == "answered"
                           and not hard.hard_gate and hard.features is not None else None)
            if calibrated and hard.status == "answered" and probability is not None:
                a2 = replace(hard, arm="A2", status="answered" if probability >= point.threshold else "abstain",
                             final_count=hard.filtered_count if probability >= point.threshold else None)
            elif calibrated:
                a2 = replace(hard, arm="A2", final_count=None,
                             status="error" if hard.status == "error" else "abstain")
            else:
                a2 = replace(hard, arm="A2", status="error" if hard.status == "error" else "not_run",
                             final_count=None, filtered_count=0, events=(),
                             reasons=(*hard.reasons, Reason.CALIBRATION_UNAVAILABLE))
            # A2's config identity commits its actual inherited counter plus
            # frozen map/policy roots; unavailable is still an explicit payload.
            a2 = replace(a2, config_hash=canonical_digest({"counter": hard.config_hash,
                              "map": pins.map_hash, "threshold": pins.threshold_hash, "arm": "A2"}))
            for prediction in (*source.predictions, a2):
                result.append(PredictionRecord(window, prediction, prediction.config_hash,
                              probability if prediction.arm == "A2" else None,
                              artifact.prior if calibrated and prediction.arm == "A2" else None,
                              source.visibility_score,
                              (source.frame_count == 0 and prediction.status == "error")
                              or (prediction.arm == "A2" and not calibrated)))
        return tuple(result)


class CustodianEdition:
    """Actual reserve/extract/seal/gold/evaluate ordering with required hosts.

    The concrete predictor uses the acquired manifest exactly once for all
    arms, with per-access guards and current frozen config/map/policy pins.
    This orchestrator does not mislabel held-out data as dev or call CounterAdapter.
    External source/extractor/evidence capabilities remain mandatory, never fake authority.
    """

    def __init__(self, *, host: TrustedHost, custody: CustodyStore,
                 privacy: PrivacyPolicy, artifact_directory: Path,
                 verify_predictions: Callable[[tuple[PredictionRecord, ...], TraceManifest, EditionPins], bool],
                 verify_gold: Callable[[tuple[GoldRecord, ...], EditionPins], bool],
                 independent_operator_receipt: str,
                 claim_gates: ClaimGates | None = None,
                 verify_claims: Callable[[ClaimGates, FrozenSchedule, EditionPins], bool] | None = None):
        if (type(host) is not TrustedHost or type(custody) is not CustodyStore
                or type(privacy) is not PrivacyPolicy):
            raise ValueError("actual_host_and_custody_required")
        if not callable(verify_predictions) or not callable(verify_gold):
            raise PermissionError("independent_host_capabilities_required")
        require_sha256(independent_operator_receipt)
        if claim_gates is not None and (type(claim_gates) is not ClaimGates or not callable(verify_claims)):
            raise PermissionError("actual_claim_verifier_required")
        self._host, self._custody, self._privacy = host, custody, privacy
        self._directory = Path(artifact_directory)
        self._verify_predictions, self._verify_gold = verify_predictions, verify_gold
        self._operator = independent_operator_receipt
        self._claims, self._verify_claims = claim_gates, verify_claims
        self._started = False
        self._attempt: Attempt | None = None
        self._bundle: ResultBundle | None = None

    def __repr__(self) -> str:
        return "<CustodianEdition private>"

    def _write_envelope(self, attempt: Attempt, payload: dict[str, object]) -> Path:
        path = self._privacy.validate(self._directory / ("predictions-" + attempt.attempt_id + ".json"),
                                      must_exist=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > 16 * 1024 * 1024:
            raise ValueError("prediction_artifact_size_limit")
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            # Durability mirrors custody; no database/files are touched at import.
            import os
            os.fsync(stream.fileno())
        return path

    def run(self, edition: str, *, extractor: Callable[[], TraceManifest],
            predictor: FrozenAllArmPredictor,
            gold_loader: Callable[[Path], tuple[GoldRecord, ...]]) -> ResultBundle:
        if (self._started or not all(callable(c) for c in (extractor, gold_loader))
                or type(predictor) is not FrozenAllArmPredictor or predictor._host is not self._host):
            raise PermissionError("one_shot_explicit_capabilities_required")
        self._host.refresh("host.edition.reserve", edition)
        predictor.preflight()
        self._started = True  # No in-process retry, even after a later exception.
        attempt = self._custody.reserve(edition, self._host._pins, self._host.evidence, arms=ALL_ARMS)
        self._attempt = attempt
        manifests: list[TraceManifest] = []

        def extract() -> str:
            self._host.refresh("host.edition.extract", attempt.attempt_id)
            manifest = extractor()
            self._host.manifest_windows(manifest, split="heldout")
            manifests.append(manifest)
            return manifest.digest

        trace_seal = self._custody.extract_once(attempt, extract)
        manifest = manifests[0]
        windows = self._host.manifest_windows(manifest, split="heldout")
        by_key = {w.key: w for w in windows}

        def source_guard(binding: TraceBinding) -> None:
            self._host.refresh("host.source.heldout", binding.trace_sha256)
            summary = self._custody.summary(attempt)
            if (binding not in manifest.bindings or summary.state != "extracted" or summary.withdrawn
                    or summary.pins_hash != self._host._pins.digest or summary.trace_hash != trace_seal):
                raise PermissionError("consumed_attempt_source_stage_required")
            _require_true(self._host._verify_source, binding, self._host._pins)

        self._host.refresh("host.edition.predict", attempt.attempt_id)
        records = predictor(manifest, source_guard)
        if (type(records) is not tuple or len(records) != len(windows) * len(ALL_ARMS)
                or any(type(r) is not PredictionRecord or type(r.prediction) is not Prediction
                       or type(r.window) is not WindowInput or type(r.filtered_count_unknown) is not bool
                       or (r.filtered_count_unknown and r.prediction.status == "answered") for r in records)):
            raise ValueError("complete_all_arm_prediction_records_required")
        for arm in ALL_ARMS:
            group = [r for r in records if type(r) is PredictionRecord and r.prediction.arm == arm]
            validate_rows(windows, (CounterRow(r.window, arm, r.prediction.status,
                          None if r.filtered_count_unknown else r.prediction.filtered_count,
                          sum(e.emitted for e in r.prediction.events),
                          r.prediction.hard_gate, r.prediction.features, r.visibility_score) for r in group), arm)
        for record in records:
            require_sha256(record.expected_config_hash)
            if (record.window != by_key.get(record.window.key) or record.prediction.window_id != record.window.window_id
                    or record.prediction.trace_hash != record.window.trace_hash
                    or record.prediction.config_hash != record.expected_config_hash):
                raise ValueError("prediction_identity_or_config_mismatch")
        _require_true(self._verify_predictions, records, manifest, self._host._pins)
        self._host.refresh("host.edition.seal", attempt.attempt_id)
        envelope = {"attempt_id": attempt.attempt_id, "pins_hash": attempt.pins_hash,
                    "trace_hash": trace_seal, "arms": {
                        arm: [asdict(r) for r in records if r.prediction.arm == arm] for arm in ALL_ARMS}}
        path = self._write_envelope(attempt, envelope)
        seal = self._custody.seal_predictions(attempt, path)
        schedule_rows = tuple(ScheduledWindow(w.person_id, w.window_id, w.positive) for w in windows)
        schedule = FrozenSchedule("real", "held_out", edition, schedule_rows,
                                  canonical_digest([asdict(w) for w in schedule_rows]))

        def score(sealed_path: Path) -> str:
            self._host.refresh("host.edition.gold", attempt.attempt_id)
            _require_true(self._host._authorize, "host.independent_operator", self._operator)
            # Prove these exact immutable in-memory records match the seal before
            # joining externally authorized gold; no pre-seal label callback.
            canonical = self._privacy.validate(sealed_path)
            with canonical.open("rb") as stream:
                payload = stream.read(16 * 1024 * 1024 + 1)
            expected = json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            if payload != expected or sha256(payload).hexdigest() != seal:
                raise PermissionError("sealed_record_identity_mismatch")
            gold = gold_loader(sealed_path)
            if (type(gold) is not tuple or len(gold) != len(windows)
                    or any(type(g) is not GoldRecord or type(g.label) is not CountLabel for g in gold)
                    or {g.label.key for g in gold} != set(by_key)):
                raise ValueError("complete_post_seal_gold_required")
            _require_true(self._verify_gold, gold, self._host._pins)
            labels = {g.label.key: g for g in gold}
            rows = tuple(replace(from_prediction(r.window, r.prediction, labels[r.window.key].label,
                         corpus="real", split="held_out", edition=edition,
                         expected_config_hash=r.expected_config_hash, probability=r.probability,
                         prior=r.prior, visibility_score=r.visibility_score,
                         truth_events=labels[r.window.key].truth_events,
                         failure_codes=labels[r.window.key].failure_codes),
                         filtered_count=None if r.filtered_count_unknown else r.prediction.filtered_count)
                         for r in records)
            # Independent operator receipt must be checked by the actual host;
            # permission flags are emitted only after that required callback.
            permission = EvaluationPermission("approved", "real", "held_out", edition, self._operator,
                         self._host.evidence.g1_hash, self._host._pins.rights_hash,
                         attempt.pins_hash, prediction_seal(rows), gold_seal(rows), True)
            if self._claims is not None:
                _require_true(self._verify_claims, self._claims, schedule, self._host._pins)
            self._bundle = run_evaluation(lambda: rows, schedule=schedule, permission=permission, gates=self._claims)
            return bundle_hash(self._bundle)

        report_seal = self._custody.join_gold_once(attempt, score)
        if self._bundle is None or bundle_hash(self._bundle) != report_seal:
            raise PermissionError("aggregate_report_identity_mismatch")
        return self._bundle

    def rerender(self, renderer: Callable[[ResultBundle], str]) -> str:
        if self._attempt is None or self._bundle is None or not callable(renderer):
            raise PermissionError("completed_immutable_report_required")
        self._host.refresh("host.edition.rerender", self._attempt.attempt_id)
        bundle = self._bundle
        validate_bundle(bundle)
        commitment = sha256(canonical_json(bundle).encode()).hexdigest()
        # Custody verifies seal/withdrawal before and after; callback gets only
        # aggregate data, never extractor/predictor/gold callbacks.
        return self._custody.rerender(self._attempt, commitment, lambda _: renderer(bundle))


@dataclass(frozen=True, repr=False)
class CompletedReportRoot:
    """Owner-established external root, never sourced from untrusted report JSON.

    source_seal is the runner's semantic prediction seal; predictions_hash is
    custody's sealed envelope BYTE hash. They are deliberately distinct pins.
    The actual owner verifier must attest their relationship to this report.
    """

    attempt: Attempt
    pins: EditionPins
    trace_hash: str
    predictions_hash: str
    source_seal: str
    report_hash: str

    def __post_init__(self) -> None:
        if (type(self.attempt) is not Attempt or type(self.pins) is not EditionPins
                or self.attempt.pins_hash != self.pins.digest):
            raise ValueError("completed_attempt_pin_root_required")
        for value in (self.trace_hash, self.predictions_hash, self.source_seal, self.report_hash):
            require_sha256(value)


@dataclass(frozen=True, repr=False)
class CompletedReport:
    """Read-only completed-report binding; no run/extract/predict/gold interface.

    No I/O at construction. Every restoration/render rechecks current actual
    host authority and completed custody state. Bytes are retained immutably,
    never used to establish their own external expected root or approval.
    """

    _host: TrustedHost
    _custody: CustodyStore
    _privacy: PrivacyPolicy
    _root: CompletedReportRoot
    _verify_completed: Callable[[CompletedReportRoot, CustodySummary], bool]
    _payload: bytes = b""

    def __post_init__(self) -> None:
        if (type(self._host) is not TrustedHost or type(self._custody) is not CustodyStore
                or type(self._privacy) is not PrivacyPolicy or type(self._root) is not CompletedReportRoot
                or not callable(self._verify_completed) or type(self._payload) is not bytes):
            raise PermissionError("explicit_completed_report_host_required")

    def _check_current(self, action: str) -> None:
        root = self._root
        self._host.refresh(action, root.attempt.attempt_id)
        if root.pins != self._host._pins:
            raise PermissionError("completed_report_current_pins_mismatch")
        summary = self._custody.summary(root.attempt)
        if (type(summary) is not CustodySummary or summary.state != "complete" or summary.withdrawn is not False
                or summary.attempt_id != root.attempt.attempt_id or summary.pins_hash != root.pins.digest
                or summary.trace_hash != root.trace_hash or summary.predictions_hash != root.predictions_hash
                or summary.report_hash != root.report_hash):
            raise PermissionError("current_completed_sealed_report_required")
        # This owner capability must verify actual persisted roots/window census,
        # semantic-vs-byte seal linkage and current consent/role/withdrawal state.
        # A hash/result/Attempt or values copied from the payload are not evidence.
        _require_true(self._verify_completed, root, summary)

    def _hydrate(self) -> ResultBundle:
        raw, root = self._payload, self._root
        if not 0 < len(raw) <= 4 * 1024 * 1024 or sha256(raw).hexdigest() != root.report_hash:
            raise ValueError("immutable_aggregate_bytes_mismatch")
        try:
            bundle = load_bundle_json(raw.decode("utf-8"), expected_bundle_hash=root.report_hash)
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            raise ValueError("completed_aggregate_unavailable") from None
        # Actual report.json uses canonical_json bytes. Reject reformatted/BOM/
        # trailing/modified inputs instead of normalizing them into a new report.
        if raw != canonical_json(bundle).encode("utf-8") or bundle.state != "measured":
            raise ValueError("canonical_completed_measured_aggregate_required")
        expected_edition = edition_hash(root.attempt.edition)
        if bundle.source_seal != root.source_seal or {arm.arm for arm in bundle.arms} != set(ALL_ARMS):
            raise ValueError("completed_semantic_seal_or_arm_census_mismatch")
        heldout_people = {a.person_digest for a in self._host._g0.split.assignments if a.split == "heldout"}
        scheduled = tuple(w for w in self._host._g0.windows if w.person_digest in heldout_people)
        counts = {"people": len(heldout_people), "scheduled": len(scheduled),
                  "scheduled_positive": sum(w.kind == "positive" for w in scheduled),
                  "scheduled_negative": sum(w.kind != "positive" for w in scheduled)}
        if len(bundle.arms) != len(ALL_ARMS) or counts["people"] != 8 or counts["scheduled"] != 96:
            raise ValueError("complete_original_heldout_report_required")
        for arm in bundle.arms:
            if ((arm.corpus, arm.split, arm.edition_hash) != ("real", "held_out", expected_edition)
                    or any(dict(arm.support).get(name) != count for name, count in counts.items())):
                raise ValueError("completed_report_edition_or_scheduled_support_mismatch")
        comparison = bundle.comparison
        if (comparison is None or (comparison.corpus, comparison.split, comparison.edition_hash, comparison.people)
                != ("real", "held_out", expected_edition, 8)):
            raise ValueError("completed_report_comparison_identity_mismatch")
        return bundle

    @classmethod
    def restore(cls, *, host: TrustedHost, custody: CustodyStore, privacy: PrivacyPolicy,
                root: CompletedReportRoot, aggregate_path: Path,
                verify_completed: Callable[[CompletedReportRoot, CustodySummary], bool]) -> "CompletedReport":
        """Future exact-path aggregate read, only after current owner/state checks."""
        view = cls(host, custody, privacy, root, verify_completed)
        view._check_current("host.edition.restore")  # BEFORE any payload/path read.
        canonical = privacy.validate(aggregate_path)
        _require_true(host._authorize, "host.report.read", str(canonical))
        try:
            with canonical.open("rb") as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
        except OSError:
            raise ValueError("completed_aggregate_unavailable") from None
        restored = replace(view, _payload=raw)
        restored._hydrate()
        restored._check_current("host.edition.restore")  # Reject state changes during read.
        return restored

    def rerender(self, directory: Path) -> tuple[Path, ...]:
        """Exclusive new artifacts from exact retained aggregate; never reevaluate."""
        self._check_current("host.edition.rerender")
        bundle = self._hydrate()
        target = _plain_output_path(directory)
        if target.exists():
            raise FileExistsError("fresh_report_directory_required")
        _require_true(self._host._authorize, "host.report.write", str(target))
        outputs: list[Path] = []

        def render(_sealed_prediction_path: Path) -> str:
            # Custody itself verifies the immutable prediction byte seal and
            # withdrawal around this callback; no private predictions are loaded.
            self._check_current("host.edition.rerender")
            outputs.extend(write_artifacts(target, bundle, expected_bundle_hash=self._root.report_hash))
            self._check_current("host.edition.rerender")
            return bundle_hash(bundle)

        self._custody.rerender(self._root.attempt, self._root.report_hash, render)
        self._check_current("host.edition.rerender")
        return tuple(outputs)

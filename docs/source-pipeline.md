# Source controller and P6 callback

Construction only; runtime, private-source admission and study execution unverified.

`posecount.pipeline.run_source(factory, requests, admission=..., window=...)`
checks admission before calling the zero-argument factory. That factory returns a
fresh, already opened `LandmarkSource`. The controller closes it on every acquired
source path, including read/geometry/counter failure. A factory that fails while
opening must release its own partially acquired resources. Reads are bounded to
7201 frames plus an overflow probe; geometry also enforces media, decoded-object,
rate and schema bounds. One geometry stream feeds every requested Counter.
Warm-up replay is unaugmented; scored/tail evidence is passed through the actual
`bridge_kwargs`/`attach_evidence` seam. No time is rounded or reconstructed.

`SourceResult` preserves predictions, every counter event, source/cleanup status,
closed source reason, frame count, mean scored chosen-joint visibility and supplied
trace/provenance commitments. Missing poses contribute actual zero visibility;
no scored frames gives null. Counter errors remain errors, and source/cleanup
errors force final-count null without deleting earlier events. The source reason
does not contain exception text, paths or participant identity. Clock metadata is
validated by geometry; no latency arithmetic or fabricated host clock is added.
Media-clock events keep the existing Counter clock semantics. DL3 owns latency.

`evaluation.counter_adapter.CounterAdapter(authorization=..., source_factory=...,
verify_source=...)` implements the existing `Evaluate(config, windows)` callback.
It receives no label/accessor. `ParameterConfig` must exactly match a frozen
`parameter_grid` member (ID, arm, keys and values); CounterConfig adds only the
existing algorithm constants for parameters unused by that arm. Every supplied
complete scheduled window yields exactly one immutable CounterRow per config,
with unchanged WindowInput, arm, filtered count, all emitted-event exposure,
hard gate, six features and visibility rank. Verification failures retain error
rows with unknown count and zero observed emissions; no source is opened. Source
failures retain prior emissions. Scheduled exposure remains WindowInput's 27 s,
including negatives failing before access. `last_outcome` contains rows and acquired
source results; validation failures before iteration raise and do not open input.

`evaluate_many(configs, windows)` dispatches identical decoded real-dev frames to
all configs in one pass per window. It is an internal future all-arm source seam,
not a held-out edition command. The ordinary LOPO callback can reopen dev traces
for its separate frozen configurations; it never receives held-out corpus inputs.
No shared schema, detector, tuning, calibration or metric implementation is copied.
The concrete trusted-host caller now lives in `evaluation.host`; see source-host.md.

The required verifier is a trusted local operator/provider boundary: before
access it checks exact trace bytes against the window commitment, provenance,
rights, native-offline and private-boundary receipt, then returns `SourceAdmission` for that exact
window and FitAuthorization. Copying a caller's hash is NOT verification. This
controller validates receipt assertions and identity matching, not signatures,
consent or rights evidence. FitAuthorization is likewise a trusted receipt
assertion. A real-dev source must produce video/camera provenance, whereas
development sources require declared development IDs and synthetic/fixture kind.
Synthetic sources cannot use real-dev receipts or enter tuning here. Python
closures and side channels require later label-isolation and provider audits.
The dev callback still rejects held-out input. The separate consumed-attempt
HeldoutSourceAdmission and trusted-host custodian source now express that path;
actual private access/execution remains blocked until owner evidence/capabilities
and later runtime authorization exist. Source construction grants no study access.

The private-boundary receipt is required for real-dev and forbidden for development.
Before issuing it, the provider must retain the existing `PrivacyPolicy` verified
boundaries and canonical private-path checks, revalidate access paths against
junction/symlink/TOCTOU changes, and run `DeviceAuthorization`'s own private-data,
rights and exact runtime/model checks where that adapter applies. A custom factory
cannot replace those checks with this receipt hash. This is a trusted assertion,
not proof of encryption, consent, authentic signatures or filesystem safety.

Calibrated A2 is not in the frozen counter grid and has no CLI invocation. Without
actual valid OOF/final map, policy and admission pins it remains not_run; manual
development thresholds never establish a calibrated answer.

## Development aggregate boundary

The CLI keeps scalar, declared-landmark and seed-generated development inputs.
Landmark/generated inputs use the shared controller. No camera/model/private
entry point is added. `--development-report NEW_JSON` serializes the explicit
`DevelopmentAggregate` allowlist only: source class, arm, status, synthetic event
exposure and filtered count, unverified/unadmitted flags, null accuracy/coverage/
calibration/headline and `not_run_no_independent_truth`. Event output is unverified
development output, not truth or accuracy. The output has no trace hash, path,
person/window IDs, individual events/labels or raw coordinates. The explicit
JSON path must have an existing parent and no link/junction components; exclusive
creation refuses overwrite. No directories or files are deleted. Path checking
is a local operator boundary, not a hostile concurrent-filesystem guarantee.

This provisional typed JSON boundary requires later reconciliation with DL2's
actual report/ResultBundle API (DL4 owns CLI integration; DL2 owns renderer/schema).
It does not pretend an unavailable report import succeeded, render a fake measured study,
calculate statistics or claim HTML report integration. HTML/JSON/SVG study reports
and custody orchestration stay with their respective owners. Public aggregates
must be escaped by the report owner. No generated expected answers are authored.

Deferred: execute callback exact-coverage/error/exposure/grid and label-isolation
cases; replay all-arm identical inputs and provider lifecycle failures; inspect
source-verification receipts and private-path/TOCTOU enforcement; exercise CLI
legacy/landmark/generator and exclusive output failures; reconcile actual DL2
report API; exercise joined runtime and installed packaging. All require later
authorization outside Dirty Mode. No tests/imports/fits/app/model/device runs
were used to construct this source.

## Actual report and timing API reconciliation

The current accepted caller contract is DL2s actual `ResultBundle`, with
`unmeasured_bundle()`, `bundle_hash(bundle)` and
`write_artifacts(directory, bundle, expected_bundle_hash=...)`.
`--unmeasured-report NEW_DIRECTORY` names that API through a lazy future import.
This branch now contains report.py and its exact source signatures are reconciled.
The lazy unavailable-import branch still returns explicit
`report_source_unavailable`, creates no report directory and exits nonzero.
The integrated caller can write an empty unmeasured shell only, never reinterpret generated events as truth
or measured support. Fixed report.json/report.html/coverage.svg are exclusively
created by DL2s writer; the caller requires a fresh local directory with existing
parent and rejects link/junction, ADS, reserved-device and UNC paths. Failures
preserve partial artifacts for operator disposition, never delete or retry.
DevelopmentAggregate JSON remains separate from that statistical ResultBundle.
Its filtered count is null for error results; observed emitted-event exposure is
retained even when no valid whole-window count exists.

The provisional P9 contract is compatible at the aggregate boundary: future study
reports may consume only `SpanWriter.summary()`, `SessionResult.aggregate()` and
`device_profile_templates()`. The current development controller has no capture,
preprocess or inference hooks and supplies no timing measurements. Read completion
must not be relabelled capture time. Do not export private Span anchors,
presentations or per-event arrays. Source receive clocks retain their separate
domain/scope; media Counter event clocks are not host render clocks. Backend drop
counts and physical-device/session observations remain unknown. No live CLI or
renderer dependency is added. DL3s P9 implementation is still in progress; DL2s
current bundle supports device_state unmeasured/incomplete, with no numeric latency
field. Do not silently squeeze timing into another public field. Reconcile actual
numeric embedding with DL2/DL3 only after final source integration.

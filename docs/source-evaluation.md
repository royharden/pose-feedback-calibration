# Evaluation and aggregate report construction — runtime unverified

Original P4/P10 source under the resumed Dirty Mode grant. No application, metric,
bootstrap, fit, report renderer, scanner, callback, device, model or dataset has been
executed/read for this package. No figures, outcomes or human-independent evidence
are claimed. Immutable PLAN-M17-v1.md section8 remains authoritative. G0/G1, historical
pre-G0 ordering, rights, human custody/annotation/verifier and actual study remain pending.
CLI/README/pyproject are INT-owned and unchanged here.

## Private rows and exact schedule/seal boundary

metrics.EvalWindow holds private corpus/split/edition/person/window keys, scheduled
positive class, scoreability/truth count, arm/status, filtered/final counts, immutable
Event tuple, hard flag, optional probability/prior/visibility rank, full27s exposure,
optional observed-return truth stamps and supplied F1–F18 failure tags. These private
rows NEVER reach public report inputs. No real rows/held-out schedules/expected answers
are authored here. Corpus is synthetic or real; split dev/held_out/regression. Groups
cannot mix corpora/splits/editions/arms. Unscoreable truth is null; nonanswers never
have a final count. Prediction source errors remain distinct from unavailable arms.

runner.from_prediction is a pure explicit scorer join between current WindowInput,
Prediction and CountLabel, with exact identity checks. Scored joins require an exact
nonblank prediction window ID, valid trace SHA256 matching WindowInput.trace_hash,
and Prediction.config_hash matching REQUIRED expected_config_hash caller pin. This is
the frozen selected Counter configuration commitment, not a parameter display ID or
an assumed default. Missing/mismatched provenance fails; legacy unpinned development
Counter usage remains outside this scored join. P6 probability/prior and truth
timestamps are separately supplied after permitted sealing. It neither activates
calibrated Counter A2 nor duplicates geometry/counters/calibration. INT owns the
remaining actual runner/CLI/source-to-row/map adapter integration.

FrozenSchedule records typed scheduled keys/classes/exposure and a canonical manifest
SHA256; it does not create an independent schedule. Real splits require EXACT96 windows,
eight people, twelve each (six positives/six negatives), never only observed/scoreable
windows. Synthetic schedule is bounded600, and must still match its declared complete
manifest. EvaluationPermission requires explicit approved operator/admission/rights/
custody receipts and prediction/gold seals before callback access. Held-out/regression
requires an independent-operator receipt flag. Actual trusted operator must verify
receipts, consumed all-arm reservation and human independence; hashes/flags cannot
authenticate consent or replace those people.

run_evaluation checks permission BEFORE callback/data access, then exact complete keys
for ALL Z/A0/A0v/A1/A2-H/A2, identical scheduled exposure and gold across arms, canonical
prediction seal excluding gold fields and separate gold seal. Wrong/missing/added rows
fail, never shrink negative exposure. Seals are typed canonical commitments, not raw
CSV/video byte hashes; the future custodian must reconcile them to actual custody pins.
Rendering later accepts the sealed aggregate ResultBundle only; it never calls runner
or reevaluates a counter. Broken seals cannot be repaired by silently rerunning an edition.

## Metrics and deterministic event matching

ArmMetrics is aggregate-only: identity/support counts, named Metric(value,reason,
numerator,denominator), five calibration bins, risk points and supplied failure-tag
counts. Scheduled/scoreable/positive/negative/status/hard/calibration/unclassified
supports remain visible. Unscoreable windows remain scheduled utility failures.
Exercise coverage uses scoreable scheduled positives; overall separately. Answered
MAE/exact/OBO accompany support; end-to-end exact denominator is ALL scheduled positives.
Null denominators/support remain named null, never zero or silently omitted windows.

Exposed FC/min counts EVERY emitted negative event over ALL scheduled negative27s,
including later abstain/error/source failure. Filtered negative counts are separate.
Final-retained events require emitted AND retained AND final status answered; a final
refusal never erases displayed exposure. Worst-person rates remain aggregate maxima.

matching.EventStamp(event_id,t_event_media) and match_events use observed-return MEDIA
time within inclusive0.5s, greedy GLOBAL nearest distance, earlier observed time, then
predicted/truth time and stable string IDs. One-to-one matching retains all FP/FN.
Heap-merging sorted per-prediction candidate streams avoids materializing7201² pairs.
Missing truth support makes event metrics unavailable, never correct-zero; truth stamps
must match count and [3,30). Confirmation/display lags remain separate. Host/media clock
mixing makes display lag null; sensor exposure/display photon timing stays unknown.

A2 Brier and same-training-row-prior Brier, five equal-width ECE bins/support and
risk-coverage/AURC use scoreable nonhard pre-confidence-usable rows, including confidence
abstentions. Missing eligible scores/prior are unavailable, not dropped. A0v has rank/
AURC only, never probability Brier/ECE. A1 wrong-count AUROC uses1−mean visibility,
tie-aware ranks and degenerate-class nulls. Descriptive AUROC CI reuses the SAME numeric
helper with whole-person2000-draw seed17017 percentile95; this routine method assumption
is NOT an added preregistered headline test. No draws ran here. Any undefined draw makes
its main interval unavailable; conditional bounds are descriptive only.

Failure counts mean SUPPLIED closed F1–F18 annotations, not absence of failures when
tags are missing. Unclassified and missing-event-truth support remains explicit.

## Paired inference and claim gates

stats.paired_comparison accepts ONLY A0/A2 on exactly matching windows/truth/schedule;
no substituted arm. deltaFC=A0 emitted FC/min−A2; deltaMAE=A2 MAE−A0 MAE on EXACTLY A2's
answered scoreable positive subset. ANY baseline nonanswer makes comparison unavailable,
no zero substitution or omitted pair. Raw same-subset MAEs and person macros accompany
the deltas; unavailable individual supports make macro summaries unavailable.

Both statistics resample SAME whole paired people:10000 draws/seed1702 and2000/seed17017,
recomputing ratios in each draw. Percentile95 uses linear interpolation at(n−1)p.
ANY undefined draw in either run makes its associated headline CI unavailable, with
explicit count; optional conditional bounds cannot rescue the claim. Exact rational
two-sided sign-flip enumerates per-person deltaFC, bounded16 people. These are source
algorithms only, no bootstrap/sign-flip execution result.

Claim selection requires real held_out, matching edition, >=8 people, computed COMPLETE
96-window census, explicit verified manifest/commitment, admission/freeze/custody/
qualifiedOOF/final-map commitments and calibrated A2 availability. Runner binds the
claim schedule receipt to its validated manifest. These checks cannot attest actual
humans or signatures. False flag/null pin means no headline. Full conjunction:
coverage>=0.60, deltaFC>0, exact p<0.05, BOTH FC lower bounds>0, BOTH MAE upper<=0 and
no unavailable subset/CI. Lower-error wording additionally needs both MAE uppers<0.
Calibration attribution requires separate A2-H ablation evidence commitment; otherwise
whole gated counter. False-count-only fallback requires its measured gates; all other
outcomes retain negative/inconclusive/unavailable wording and failed gate list.

## Public ResultBundle / rendering / release boundary

results_writer converts ArmMetrics/Comparison into posecount.report frozen public DTOs.
It hashes the private edition alias; no participant/window/name/path/coordinates,
individual labels, media or arbitrary free-text labels exist in the public schema.
Closed metric/support/reason/gate/arm/split vocabularies reject unexpected text; all
numbers must be finite or named null. Public support/metric/bins/intervals/failure
tags are the sole report inputs. Synthetic/real and dev/held_out/regression remain
separate. No diagnostic silently becomes a headline. CPU/cost/device measurements
not produced by this package remain unmeasured, never invented run values.

canonical_json and HTML tables use the SAME validated payload/numeric representations.
Handwritten SVG coverage bars use finite validated ratios and escaped closed labels.
Complete supports/bin/risk/CI/draw/undefined/failed-gate values appear as escaped JSON
TEXT, not executable script. Device heading is “2 devices, not a device survey” with
unmeasured/incomplete state, not a two-device performance result. Pretrained/owned
engineering and no-coaching/medical/form/safety limitations remain explicit disclaimers.

bundle_hash seals aggregate bytes. write_artifacts requires that exact expected hash,
load_bundle_json accepts only bounded4MiB closed-schema JSON, rejects duplicate/extra/
missing fields and nonfinite constants, reconstructs frozen aggregate DTOs and verifies
the expected canonical bundle hash. A restarted process can re-render that sealed
aggregate without loading private rows or invoking evaluator/counter/model code.
The identity is canonical payload identity, not a whitespace-sensitive JSON-file hash.
write_artifacts then
creates fixed report.json/report.html/coverage.svg with exclusive creation, refuses
existing files and never deletes/overwrites/publishes. Later authorized caller supplies
a fresh output directory and owns interruption/partial-artifact disposition; no such
writes or renderings ran during construction. Rerender reads immutable aggregate data,
not private rows and not detector output reevaluation.

README scanner grammar is metric:id marker + JSON number/null + matching closing
marker. It flags missing/extra/duplicate/malformed/planted value mismatches; unrelated
numbers are ignored. It does not rewrite README. Wording scanner returns hashed hits,
not private excerpts; form/depth/tempo/appearance grading, coaching, medical/injury
inflections and exercise-safety claims are flagged. Explicit disclaimer blocks are recognized but EVERY hit still
needs actual nonbuilder receipt/disposition. Unresolved/pending/actual claim hits block
wording-release readiness. Builder source supplies no sign-off. Writing a draft is
not publication or release acceptance; all other rights/study/human gates still apply.

## Checks/deferred work

Only source inspection/AST/whitespace checks are permitted now. Later authorized owner
must run independent hand-math matching/ties/null/MAE/FC/Brier/ECE/AURC/AUROC checks,
whole-person resampling/sign-flip/undefined-draw cases, full96-manifest and claim-census
regressions, malformed/hostile labels/schema/rendered JSON-table-SVG fidelity, README
marker mismatch/wording dispositions and sealed rerender/no-reevaluation checks. Actual
private scorer/CLI integration, calibrated A2 activation, packaging/wheel behavior,
device/offline/CI/runtime and independent verifier remain unverified. No fixtures,
expected answers, held-out schedules, labels or results were authored by this package.

## Optional timing/device report extension (source only)

The optional LAST ResultBundle field is timing: PublicTimingReport|None=None.
Existing constructor calls continue working. payload/canonical_json OMIT the timing
key when None, preserving the original canonical payload/hash for old no-timing
bundles; unmeasured_bundle() remains empty, with timing=None. load_bundle_json
explicitly accepts the original closed field set without timing and supplies None.
New nonnull timing payloads carry their own schema_version=1 and are fully hydrated
into frozen DTOs before validation/hash verification. Unknown/missing fields still
fail; an upgraded source cannot silently relabel a new canonical hash as an old seal.

PublicTimingReport contains TimingObservation, PublicTimingSummary, optional
PublicSessionTiming and PublicDeviceProtocol. Phase/stage DTOs preserve the producer
p50/p95/p99, valid/unknown counts/reasons, first5s exclusion, retained/overflow
population and nullable backend drops/overwrites. No quantile/statistics implementation
is duplicated. Session frame identities are checked; source unavailable slots,
backend counts, controller drops and slot overwrites remain distinct. Only the fixed
process_monotonic_ns/capture-return-to-render-enqueue boundary is allowed; photon
latency, sensor exposure and LIVE_STREAM parity remain null, never inferred.

results_writer.timing_report(*,span_summary=None,session_aggregate=None,
device_profiles,source_sha256,observation_status,operator_receipt_sha256=None)
returns PublicTimingReport. Exactly one aggregate source is required. Supply the exact
SpanWriter.summary() OR SessionResult.aggregate(), and current
device_profile_templates() shape (including any later operator-supplied permitted
observations). Only the approved closed source schema is accepted: no Span,
ClockAnchor, Event/presentation arrays, pixels, source/person/window identifiers,
serials, private paths or arbitrary error/CPU/SDK descriptions can enter this DTO.
Hardware/runtime evidence is closed metadata or private-receipt SHA commitments.

source_sha256 is the lowercase SHA256 of canonical JSON (sort_keys=True,
allow_nan=False,separators=(",",":"),UTF-8) for the complete packet:
source_kind (span_writer_summary or session_result_aggregate), aggregate (the exact
selected producer aggregate), and device_profiles. The converter seals its immutable
DTO snapshot rebuilt into that same source shape, not subsequently mutable caller
dictionaries. The source seal binds supplied aggregate values, not the authenticity
of actual native measurements or human receipts.
Core validate_timing_report uses the shared timing_source_sha256 immutable packet
serializer, so direct DTO validation, JSON hydration and rendering also enforce the
source seal; there is no converter-only bypass or second packet implementation.

observation_status is REQUIRED and closed: unmeasured, incomplete, operator_reported.
Any nonempty timing/session/device observation requires a non-unmeasured status and
explicit operator_receipt_sha256; unmeasured rejects observed values. Operator-reported
booleans/digests are NEVER independent verification. Two device slots with three60s
requested session slots each are protocol parameters, not observed machines or
sessions. Device profiles retain unverified_operator_receipts/trust-limit labels;
physical distinction, rights, native offline acceptance, denial/restoration/release
and real observations still require actual authorized operator/custodian evidence.
Unknown backend counts stay null even if a synchronous controller reports zero slot
overwrites. No source/device/preview/renderer function is invoked by the converter.

attach_timing(bundle,*,span_summary=None,session_aggregate=None,device_profiles,
source_sha256,observation_status,operator_receipt_sha256=None)->ResultBundle returns
a NEW frozen bundle. It validates the exact source seal and full public timing DTO,
marks reported device state incomplete, and preserves the original evaluation seal.
For an otherwise-empty unmeasured bundle with explicitly reported timing, it uses
incomplete state/source timing seal; it cannot manufacture accuracy/calibration or
successful native observations. Existing measured count results are not recomputed.
render_html adds actual aggregate phase/stage quantile, session-accounting and device
protocol/observation tables; the complete closed schema is also in escaped JSON text.
All display values are copied from the same sealed DTO. No renderer/loader or timing
source was executed during construction.

Later authorized validation remains required: original canonical-hash compatibility,
closed JSON hydration/roundtrip with/without timing, exact producer source seals,
known-vs-unknown backend counts, received/retained/overflow and controller identities,
null/malformed quantiles/phase support, mutable caller snapshot isolation, protocol
slots versus operator observations, finite/bounds/reason/privacy rejection and actual
HTML/JSON table fidelity. These source paths establish no runtime/independence pass.

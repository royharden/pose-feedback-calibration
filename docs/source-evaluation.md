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

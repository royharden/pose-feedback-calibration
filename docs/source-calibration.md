# Calibration/tuning/LOPO source — runtime unverified

Original source under the resumed P6 Dirty grant. No labels, recordings, fits, model
calls, sklearn imports, runtime checks or calibration results were used/executed here.
G0/G1, historical pre-G0 ordering, consent/rights and independent study execution remain
pending Roy. Sources implement future permission checks; they supply no admission.
Immutable outer PLAN-M17-v1.md section7 remains authoritative.

## Frozen inputs and authorization

tuning.FitAuthorization has REQUIRED G0/G1/rights/roster SHA256 commitments,
approved_by/approved_at, exact eight distinct dev people, status and corpus. Every
fit/tune path requires explicit approved + real_dev, nonblank approval and valid pins;
no default pass or synthetic selection. Future trusted operator must verify the actual
signed/authorized receipt behind each commitment. This source hash/status check cannot
attest human independence, consent or authentic signatures. It is not a security sandbox.
Public report consumes bounded aggregates only; private rows/logs stay in the admitted
encrypted local root and never enter coding-model context or public artifacts.

WindowInput(person_id,window_id,trace_hash,positive,corpus=real_dev,scored_seconds=27)
is inference metadata only. positive is preassigned capture class, not inferred truth.
Every person contributes all12 scheduled windows, six positive/six negative, including
unscoreable/source-failed windows. Global window/trace keys must be unique and person
disjoint. Full pipeline requires the EXACT eight-person roster; seven-person training
subsets are allowed. No shorter observed-exposure denominator or dropped callback rows.

CountLabel(person_id,window_id,trace_hash,truth,scoreable) is separate supervised data.
Unscoreable truth must be null; scoreable truth is a nonnegative integer, never bool.
GuardedLabels stores labels privately and returns them only through instrumented read:
stage tune/fit requires allowed-person scope; stage threshold additionally requires an
OOF seal. restrict narrows scope and shares immutable access records with the parent;
each denied read is logged and raises. Full LOPO gives upstream code a seven-person
restricted accessor, so the current outer person's labels cannot enter counter tuning,
map targets or prior fitting via that accessor. Callbacks receive no accessor or labels.
Python closures/private-attribute tampering are outside this trusted-operator audit
boundary. Independent future accessor/closure audits and leakage checks remain required.

## Counter callback and finite-grid tuning

ParameterConfig(config_id,arm,values) uses immutable sorted key/value tuples and lexical
config IDs. Evaluate(config, tuple[WindowInput,...])->Iterable[CounterRow] is the only
counter-evaluation callback. CounterRow(window,arm,status,filtered_count,emitted_events,
hard_gate,features=None,visibility_score=None) must return each supplied window exactly
once, unchanged, for the selected arm. It reports ALL emitted negative events even if
later refused/errored. No geometry/counter duplication or not-built module import occurs.
An adapter from actual counter/source results to these rows is not executed/proven.

Grids reproduce Z/A0/A1 and full A1×q×g A2-H from the frozen plan. A0v tunes its own
A0 grid with threshold0 for unrefused ranking rows; actual OOF visibility policies are
selected later. Caller must supply mean scored-window chosen-joint visibility ranking,
not a probability. No fitted parameters or label-selected movement inside callback.

Tune each arm by mean positive-window loss WITHIN person then mean across people.
Usable row cost = abs(filtered_count−truth); hard abstain/error/nonanswer cost = truth+1.
Unscoreable positives cannot supply supervised loss: exclusions are counted, and each
person must retain scoreable positive support. Do not call this exclusion a utility
success; scheduled coverage/utility still retains those windows. Tie: lower every-emitted
negative FC/min over ALL scheduled negative27s windows, then lexical config ID.

## Fixed map and full-pipeline LOPO

calibrate.FitRow keeps identity/features/boolean exact-count target/status/hard_gate/
scoreable/corpus separate from inference rows. Only scoreable usable nonhard windows
enter training; target = filtered_count equals adjudicated truth BEFORE confidence
abstention, including positives and negatives. Hard/error rows never become correct zero.
Raw six inputs in order vis,gapfree,amp,intv,mean_g,no_cycle are bounded, with no-cycle
amp/intv0; no standardization, feature search or model contest.

fit_map checks authorization BEFORE lazy optional sklearn import. Fixed
LogisticRegression(C=1,penalty=l2,solver=lbfgs,max_iter=1000,tol=1e-6,random_state=17017).
Require >=5 correct AND5 incorrect eligible rows; insufficient support, absent dependency,
fit failure/nonconvergence or invalid numerical output gives calibration_unavailable,
null coefficients/probabilities and a bounded reason. Fixed-coefficient sigmoid is
stable source only, not a measured numerical check. MapArtifact records coefficients,
intercept, feature order, support/correct/incorrect/exclusions, sklearn version,
convergence, same-eligible-training-row constant prior, allowed_people, actual eligible
training_people and pins. Missing prior support stays null. Invalid input rows fail
explicitly rather than inventing a map. Artifact.as_dict preserves unavailable/nulls.

evaluation.lopo.run_lopo requires code/model/runtime/protocol/split SHA256 pins and
all96 dev inputs. For each outer person, independently tune Z/A0/A0v/A1/A2-H on the
other seven; fit map/prior from their eligible selected A2-H rows; predict the outer
person with NO outer label reads. FoldRecord holds seven-person scope/configs/map and
excluded map rows; OOFRecord holds immutable per-arm predictions, p_exact or null,
prior, outer person, map/config hashes. Disjoint trace keys are asserted.

Only after all eight folds' complete prediction records are hashed/sealed do downstream
outer labels join for threshold selection. OOF seal excludes outer truth. LabelRead
records make allowed-person sets/stages visible. Then refit counters/map on all eight
with OOF thresholds frozen. PipelineResult records folds/OOF/seal/policies/final config/
map/pins/accesses and status/reason. ANY unavailable outer map prevents calibrated A2;
an available final refit cannot repair it. Unavailable final map also yields not_run.
A2-H predictions remain in OOF regardless; no arm substitution or fabricated confidence.

## Thresholds and consumers

SelectionRow pairs a prediction with A0 on the EXACT same window, its downstream label
and p_exact (or visibility rank for A0v). OperatingPoint serializes status, threshold,
coverage, wrong-rate, MAE/A0-MAE, all-exposure FC/min and reason; unavailable numerics
stay null. Search0..1 by0.05. Choose greatest OOF exercise coverage subject to ALL:
coverage>=0.60, answered-positive wrong<=0.10, MAE<=A0 on identical answered positives,
and every-emitted-negative FC/min<=A0 over full scheduled exposure. Ties lower MAE then
higher threshold. A0 subset nonanswer makes that comparison unavailable, never zero or
an omitted pair. No qualifying point freezes threshold0 with failed_dev_operating_point;
it is NOT success. Missing scores/maps is explicit not_run.

A0v selects its own qualifying visibility policy and a separate nearest-A2-dev-coverage
variant, ties retaining more coverage. Nearest policy is marked descriptive, never
qualification, and is not test-matched. A2 coverage unavailable => nearest not_run.
Nearest policy also preserves comparison_status/comparison_reason and the original
unavailable reason (for example no_answers/A0_subset_nonanswer), so null comparisons
remain explained even when the outer policy label is nearest_dev_coverage.
Threshold selection never tunes held-out/test coverage. A fitted map alone never grants
the useful-counter headline; all section8 metrics/interval/human gates remain separate.

Later consumers must use PipelineResult.status as well as map/point availability; an
OOF point can remain recorded even when final-map failure prevents calibrated A2.
Parameter IDs/pins/data commitments are provenance fields, not verified rights or
actual fit receipts by mere serialization.

## Deferred validation

AST/whitespace source review is the only current check. Later authorized validation:
person-macro hand loss; finite grids/ties/all-exposure denominator; accessor outer-label
denials and complete96-row/person/trace accounting; stable-sigmoid handwritten vectors;
fixed40-row fit/sign/convergence/support/dependency failures; exact seven-person maps/
prior and full-pipeline eight-fold sealing; threshold constraint/tie/no-point/undefined-
subset cases; A0v independent/nearest policies; unavailable OOF/final-map branches and
serialization. Runtime fitting is blocked until real-dev G1/rights permission; no toy
data, synthetic performance selection, held-out schedules or independent expected
answers are supplied. CLI/model/counter adapter, actual sklearn compatibility and all
real study outcomes remain unverified.

# DRAFT — aggregate evaluation/report contract

Unsigned and unverified. No measurements, independent approvals or runtime report
exist by authority of this document. Immutable outer PLAN-M17-v1.md sections 8–10/13
control; this is documentary preparation, not a new protocol or runnable schema.
G0/G1, historical pre-G0 ordering disposition, rights and future product grant remain
pending. No data collection, evaluation, device operation or release is authorized.

## Result bundle and missing states

Future aggregate bundle identifies corpus (synthetic versus real), dev versus held-out,
edition, arm, code/config/model/runtime/map/threshold pins and sealed-prediction
commitment. Blank/unavailable commitments never become verified hashes. Reserve the
all-arm held-out attempt BEFORE any detector-held-out video/trace/gold read; reservation
consumes the edition even on crash. Seal predictions before gold join. Report rerender
may use immutable sealed predictions without reevaluation. Custody is a trusted-operator
audit convention, not hostile-operator isolation. No per-device held-out re-extraction.

Keep answered, abstain, error, unscoreable, calibration_unavailable and not_run support
visible; never convert them into correct zeros or silently drop scheduled windows.
Unmeasured means no measurement exists, not zero. Each unavailable numeric field is
null with a bounded reason and numerator/denominator/support metadata where applicable.
Retain failed or partial attempts and their status. Missing/degenerate denominator or
unavailable comparison is null with reason, not NaN/infinity or an omitted row.

Synthetic and real tables stay separate; never pool support or suggest synthetic
success demonstrates body accuracy, calibration or device performance. Include each
preregistered arm Z/A0/A0v/A1/A2-H/A2, explicitly not_run when unbuilt/unavailable.
No numeric results are populated here.

## Metrics and aggregate columns

| Field group | Definition / required support |
|---|---|
| Corpus support | Corpus/edition/arm, people, scheduled and scoreable positive/negative windows, each status count; retain private per-person/view support for authorized reporting. Public aggregates contain no recognizable identities. |
| Coverage and counting | Exercise coverage = answered / scoreable scheduled positives; overall coverage separately. Answered MAE = mean absolute count error, exact = fraction exact, OBO = fraction absolute error <=1. Always accompany with support/coverage. End-to-end exact = answered-and-correct / ALL scheduled positives; unscoreable windows remain scheduled utility failures. Include raw positive counts and A0/A1 full-set results. |
| Negative exposure | Exposed FC/min = EVERY emitted negative event / full scheduled scored negative minutes, even after final abstain/error. Missing source never reduces exposure. Also report final-retained FC/min and worst-person rate. Internal candidates are not displayed events. |
| Event matching | One-to-one nearest-distance match on observed-return MEDIA time within 0.5s; ties earlier time then stable event ID. Precision/recall/F1 use resulting TP/FP/FN; missing/rejected truth events remain FN. Freeze matcher/tie cases independently of counter; confirmation/display lag separately. |
| Probability diagnostics | A2 Brier against same-training-people constant prior; ECE with five fixed equal-width bins and bin support; risk-coverage/AURC; calibration support/ineligible counts; confident wrong at p_exact>=0.9 and support. A0v visibility is ranking only: AURC, no probability Brier/ECE. Include mean-vis AUROC for A1 wrong-count detection with interval/support. |
| Resources/failures | CPU seconds and paid cost only if measured; otherwise null/unmeasured. Keep FP/FN and wrong/abstained/error categories F1–F18 from plan, including cold-start, late confirmation and other-described. Real private event/trace/label records stay outside public output/model context. |

## Paired inference and headline selector

deltaFC = A0 exposed FC/min − A2 exposed FC/min (positive favorable).
deltaMAE = A2 answered MAE − A0 MAE on EXACTLY A2's answered positive subset
(negative favorable). A0 nonanswer on ANY paired window makes the comparison
unavailable: no zero substitution and no omitted pair. Never substitute another arm.

Resample the same whole held-out people, never split their windows across draws.
Primary percentile 95% bootstrap: 10,000 draws, seed1702. Sensitivity: 2,000 draws,
seed17017. Recompute aggregate ratios per draw; report person-macro/per-person rates.
Any undefined draw in either run makes its associated headline interval unavailable;
do not discard it. Separately labeled conditional descriptive intervals cannot rescue
the headline. Include exact two-sided sign-flip p on per-person deltaFC, person count,
both intervals/draw counts, undefined-draw counts and selected claim text.

Only if ALL conditions hold may the future selector say: “fewer displayed non-exercise
false counts without worse matched-subset counting in this pilot”:

- Valid admission, freeze and custody; at least eight distinct held-out people.
- Available preregistered calibrated A2 operating point; no failed dev point/not_run
  or unavailable OOF/final map; exercise coverage >=0.60.
- Mean deltaFC >0, exact sign-flip p<0.05, BOTH bootstrap deltaFC lower bounds >0.
- BOTH deltaMAE upper bounds <=0, no unavailable paired comparison or headline interval.

Lower count error additionally requires both deltaMAE upper bounds <0. Attribute any
benefit to the whole gated counter; calibration benefit requires A2-H ablation evidence.
If only false-count conditions pass, state fewer displayed false counts but no
demonstrated useful counting advantage, with failed gates/coverage/deltaMAE alongside.
Otherwise state no demonstrated advantage in this pilot. Current state is unmeasured;
none of these measured conclusions is asserted. Keep null/negative results visible.

## Rendering and release checks deferred

Escape ALL untrusted labels/IDs/reasons in HTML and SVG; never interpolate executable
markup, scripts, unsafe URLs or raw participant records. JSON is the numerical source
for tables; future nonbuilder verifier reconciles every rendered metric and wording
hit. README metrics belong in designated metric:id markers checked against JSON.
No planted mismatch, unresolved claim-linter hit or actual prohibited claim may pass.
Explicit disclaimers/non-goals remain distinguishable from claims. Preserve F1–F18
failures, arm/status support and separate dev/held-out and synthetic/real labels.

No runnable renderer, measurements or fixtures are authored. Later checks: independent
hand math/matching; Brier/bin support; person-grouped 10,000/2,000 resampling and exact
permutation; undefined draws/nonanswers; escaped malicious labels; immutable exposure;
JSON/table/README consistency and claim selection. Runtime/CI/offline Docker validation,
actual human verifier and publication approval remain deferred and unverified.

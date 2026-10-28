# DRAFT — counter contract and admission gaps

Unsigned preparation only. No implementation, data use, tuning, acquisition, evaluation
or release permission is granted here. Outer planning/promoted/PLAN-M17-v1.md sections
3–7 and P4/P5 remain authoritative. This trace does not replace the immutable plan.
Source inspected at base 6f2a750f329dc5278508aaf78335defdb544bb13; nothing was executed.

## Admission remains pending

G0 requires Roy-appointed recorder/custodian and two nonbuilder annotators, two actual
physical machines, 16 adult consents and 192 valid private clips, both independent
CSVs complete, at least 90% scheduled windows scoreable by both in EACH split,
support disclosed, frozen rubric/roster/split/gold commitments, accepted private
storage/retention/withdrawal/offline procedures and exact model/runtime rights evidence.
Builder receives commitments and bounded aggregates only. Hashes establish bytes,
never consent or independence. G0 failure means SKIPPED_DATA_GATE, not a synthetic-only
substitute study.

Existing source predates G0. A new receipt cannot establish historical pre-code ordering.
Roy must disposition that ordering and admission scope; INT must issue a separate
product grant before further gated source work. G1 separately reconciles imported
CSV/rights/split hashes against G0, requires dev pre-adjudication exact-count agreement
>=0.80, valid labels and scoreability quotas. Held-out agreement stays with the
custodian/scorer; builder has no tuning access. R01/R02/R03/R07/R08 human/data/device/
rights/license decisions remain pending. No signatures, people or evidence are supplied.

| Future receipt field | Value |
|---|---|
| Roy ordering disposition/signature/date | |
| Custodian and nonbuilder A/B commitments | |
| G0 receipt commitment/sign-off | |
| Model/runtime rights evidence commitment | |
| G1 reconciliation/dev-agreement receipt | |

## Existing scalar seam versus required contracts

| Path under src/posecount | Static source fact | Missing integration / later obligation |
|---|---|---|
| schema.py | Frozen AngleFrame(t_media, theta, visibility, poses) validates finite ranges. CounterConfig contains the A1 finite grid. | No 33-landmark FrameBatch. DL1 must supply aspect correction, warm-up side choice (tie left), presence distinct from visibility, clock/source status and bounded transport. Reconcile through the existing schema, not a duplicate. |
| counter.py | A1 update(AngleFrame) returns immutable events; finish() caches Prediction. Warm-up median, EMA, hysteresis, return confirmation/deadline and source resets exist in source. | Full update(frame)/finish(window) integration and Z/A0/A0v/A2-H/A2 remain unbuilt. Static tracing is no temporal test pass. |
| schema.py Event | Start/observed-return/confirmation/display times, display domain/scope, emitted/retained and excursion/duration/amp/intv/cold_start are represented. | Preserve all displayed exposure after later refusal/error. Offline display equals confirmation media time; never mix media and host domains/scopes. |
| schema.py Prediction | Arm/status/candidate_count/filtered_count/final_count/events/reasons and null-only p_exact exist. | Required window_id, hard_gate, config_hash and trace_hash are absent. D2 must reconcile shared consumers with DL1 and future DL3/DL4; placeholder hashes establish no provenance. |
| features.py | consistency, union-slot gapfree, movement, quality and WindowFeatures.vector are numeric helpers. | No stream accumulators wire cycle vis/gapfree/q, trailing gates, sticky invalid state or whole-window summaries. Helpers do not establish A2-H or calibration. |

## Temporal and evidence obligations for later implementation

Score [3,30): discard warm-up partial state at 3s; descent below stand−m, return above
stand−m/3; tau {0.1,0.2}s, m {25,40} degrees, minimum duration {0.6,1.0}s.
Observed return must precede 30s. Require 0.3s continuously above return threshold
within 1.5s of observed return. Tail can confirm only an existing eligible return;
end-of-stream invents no frames. Preserve plan examples 29.4/30.8 and truncated
29.8/30.2 for later independently specified checks, not claimed observed outcomes.

Previous-five excursion/duration references exclude the current candidate and include
rejected completed candidates; defaults 40 degrees/2s, floors 1 degree/0.001s.
Current A1 appends references at observed return before confirmation. Future D2 must
explicitly reconcile that boundary with the plan's completed-candidate wording; this
document neither silently resolves the ambiguity nor authorizes source changes.

Cycle vis is the fraction with all three selected joints visibility >=0.5. Gap support
uses the union of missing/late nominal slots; invalid expected count is an error.
q=min(vis,gapfree,amp,intv), threshold {0.25,0.5,0.75}. Movement uses causal trailing
6s post-reset leg/elbow variance and torso-normalized hip ranges, epsilon 1e-6,
threshold {0.4,0.6}. Missing inputs close the gate; invalid torso/reference scale is
an error. Gate closure/discontinuity resets unfinished cycles; recovery cannot finish
stale state. Shoulder-width yaw is diagnostic only.

A2-H hard invalidity is sticky for the window: selected-joint visibility <0.5 in >20%
of trailing 2s frames, gap >0.5s, or two poses causes abstention/reset and excludes
map fitting/final answer even after recovery. This differs from current A1 source-error
handling; do not relabel all A1 errors as calibrated abstention.

Six future map inputs: vis, gapfree, amp, intv, mean scored-window g, no_cycle.
Vis/gapfree take min(worst retained-cycle, whole scored-window), using whole-window
support when no cycle remains. Amp/intv use worst retained-cycle, both zero when none
remains; no_cycle=1 then. q and A0v visibility ranking are never probabilities.
Keep p_exact null until an authorized available exact-whole-window map exists.
Missing OOF map prevents calibrated A2 even with an available final refit. Hard/error
windows never become correct zero. A2-H remains separately reported.

## Closed reasons: existing values and proposed additions

Existing Reason values retain their exact spellings and current A1 distinctions:
invalid_input, nonmonotonic_time, input_limit, source_gap, missing_joints, pose_count,
standing_reference_unavailable, no_scored_frames, short_cycle, confirmation_expired,
unconfirmed_return, partial_cycle, incomplete_window, source_error.

The following are DRAFT enum/template proposals for future D2 reconciliation. They
are not installed enum members; the plan does not prescribe these spellings.
Never emit arbitrary exception text as a public gate reason.

| Proposed reason | Trigger / later semantics |
|---|---|
| required_joint_visibility | >20% low visibility in trailing 2s: sticky A2-H hard abstain/reset. |
| second_person | Two poses: sticky A2-H hard abstain/reset; retain A1 pose_count compatibility. |
| movement_inputs_missing | Missing elbow/hip/angle inputs: close movement gate/reset partial state. |
| movement_below_threshold | g below selected threshold: close/reset; not by itself sticky hard invalidity. |
| invalid_reference_scale | Zero/nonfinite torso/reference scale: error, null final answer. |
| quality_below_threshold | q below threshold: reject candidate, preserve reference/exposure semantics. |
| invalid_expected_frames | Invalid expected nominal count: source error, never perfect gap support. |
| zero_feature_denominator | Other zero denominators: zero consistency plus diagnostic. |
| calibration_unavailable | Insufficient/nonconverged map: null probability; calibrated A2 unavailable. |

Reuse source_gap for >0.5s discontinuity; future A2-H tracks sticky hard_gate separately
from A1 error. Display template: not counting: <closed reason>. Status, hard_gate,
counts and exposed events remain distinct. Raw A1 candidates, post-q/movement filtered
count and answered-only final_count must not be conflated. Retention/refusal never
subtracts displayed negative exposure.

## Deferred activation and validation

Preparation changes documentation only. After Roy admission/order/rights disposition
and explicit INT grant, D2 owns shared schema/gate reconciliation. DL3/DL4 remain future
seam owners, not active approvals. Confirm FrameBatch integration with DL1 before
claiming integrated behavior. All human-independent work remains pending Roy.

Later authorized checks: warm-up/window/prefix invariance; late/tail/deadline cases;
past-only references including rejected candidates; missing/late-slot union; all hard
gates and sticky recovery; movement startup/missing/zero denominators; no-cycle six-
feature summaries; immutable exposure under refusal/error; malformed input/prediction
pins; Z/A0/A0v/A2-H parity. Runtime, tests, real data, model, calibration/OOF, devices,
offline acceptance, packaging and independent evidence remain unverified. No held-out
schedules, expected answers or participant data are authored here.

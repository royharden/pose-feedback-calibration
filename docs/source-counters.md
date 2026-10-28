# Scalar counter construction — runtime unverified

## Public current gate callback (P9 reconciliation)

Import posecount.counter.counter_gate_reason(counter:Counter,latest_scalar:AngleFrame)
-> Reason|None, or counter.gate_reason(latest_scalar). Pass the EXACT scalar object
most recently passed to this counter.update(), including its attached evidence.
Equivalent copies and stale/replayed earlier frames close as stale_input. The owner
checks object identity, media time and a snapshot of scalar/evidence values (including
legacy mutable visibility sequences). Wrong types fail as invalid_input. No query
calls finish(), changes state, replays frames, computes movement/q or applies a filter.

Normal update/source_error paths cache the current decision from already-computed
state. No input -> no_current_input; first3s -> warmup; source-invalid -> its first
sticky source Reason. A2 missing map -> calibration_unavailable; A0v missing policy
-> visibility_policy_unavailable. A2-H exposes actual current movement/missing-input
closure, current-frame q rejection and sticky hard-latch Reason; a later valid
movement sample does not erase a hard/source failure. A transient q rejection belongs
only to its processed frame; a later frame can open current movement checks without
promising that its next candidate will pass q. No final-window score/probability or
prospective q is invented. None means CURRENT gate open, not a retained future rep,
final answer or camera/native success. Legacy A1/A0/Z still need no A2-H metadata.

After30s no new candidate gate opens; tail is open only while an existing eligible
non-Z return awaits confirmation. Otherwise scored_window_closed; after explicit
finish, counter_finished or an already recorded source-error Reason. Query itself
never finishes. Existing emissions, counts, filters, references and final decisions
are unchanged by this observation-only seam. The live wrapper can use exactly this
callback; no consumer should inspect private counter state or copy its gate math.
Source integration/identity/repeated-query/no-mutation behavior remains unexecuted.

Original source under Roy's 2026-10-28 resumed Dirty Mode grant. Human admission,
G0/G1, historical pre-G0 ordering, real-data/model/runtime rights and independent
study execution remain pending. No runtime/import/test/device/model execution occurred.
This supersedes the earlier draft's unbuilt status for the source pieces below only;
it does not establish study admission or measured correctness.

## Public producer/consumer seam

Counter(config=CounterConfig(), arm="A1", window_id="", trace_hash=None) consumes
AngleFrame through update(frame)->tuple[Event,...]; finish()->Prediction is cached.
Never reuse an instance for another window. Existing positional Counter(config) and
AngleFrame(t_media,theta,visibility,poses) remain supported; default A1 needs no new
metadata. All source times are media seconds. Event offline display uses confirmation
media time, domain media_seconds, scope input_stream; no host-clock arithmetic occurs.
Production live host-display timing still needs an explicit later adapter/reconciliation.

Optional AngleFrame.evidence is immutable FrameEvidence with required elbow_left/right
angles in degrees, hip_x/y already normalized by a fixed valid warm-up torso scale,
torso_scale, nominal_interval_s and slot_index; missing_slots/late_slots are tuples
of causal grid IDs, default empty. The fixed nominal grid starts at media0; frame
time must be within half a nominal interval of its slot time. Interval is [1/120,0.5]s,
slot0..7200; missing/late IDs cannot exceed the present slot. Metadata must be validated
before counter use; interval and torso scale cannot drift. DL1/INT own reconciliation
of irregular native source timestamps, side selection and aspect-corrected angles.
No FrameBatch duplicate or import of an unbuilt DL1 module is introduced.

Exact bridge: schema.attach_evidence(geometry_frame.angle_frame,
elbow_left=producer_left_elbow, elbow_right=producer_right_elbow,
hip_xy=producer_normalized_hip_xy, torso_scale=producer_fixed_torso_length_px,
nominal_interval_s=producer_fixed_interval, slot_index=producer_actual_slot,
missing_slots=producer_missing_tuple, late_slots=producer_late_tuple).
This function accepts producer VALUES, not GeometryFrame itself; DL1 owns the exact
GeometryFrame field names and geometry calculations. Hip coordinates must already
be normalized; do not normalize twice or compute elbows again in the consumer.
Producer None elbows -> elbow_inputs_missing. Missing grid or a time/grid mismatch
-> evidence_metadata_unavailable; time is never rounded/replaced. Missing hip/torso
-> movement_inputs_missing; invalid nonpositive/nonfinite scale -> named source error.
These reasons sit in AngleFrame.evidence_reason while evidence remains None, closing
A2-H without withholding legacy A1's original scalar time/angle. Invalid metadata types
are named invalid_input. Warm-up replay retains original t<3, so evidence movement
history is excluded/reset before scoring. Delay until3s does not create scored history.
The bridge is original source only, not a claim of joined producer execution; final
DL1 elbow/grid API is still being repaired and INT owns remaining joined reconciliation.

Absent A2-H metadata closes the movement gate by movement_inputs_missing; it never
becomes perfect evidence. Raw A1 geometric candidates run alongside gated state.
Prediction candidate_count is RAW A1 candidates for every arm; filtered_count is
the arm's confirmed retained events; final_count is null unless answered.
Prediction adds window_id/hard_gate/config_hash/trace_hash/features. Config hash is
computed from serialized selected arm/config; trace hash is optional caller-supplied
SHA256, not a verified acquisition receipt. The caller still owns raw trace hashing.
Missing features are null; p_exact is always null in this package.

## Arm behavior and causal references

Z suppresses events and answers zero only on source-valid windows, validating input
and window completeness independently of A1's standing-reference validity. A0 uses fixed
down/up/dwell grid, not a learned reference: down dwell establishes descent and observed
return above up starts standing confirmation. Return confirmation requires the stricter
of configured up dwell and shared0.3s; expires1.5s from observed return. This explicit
shared-confirmation convention needs later plan-conformance validation, not a timing
claim. A0v uses A0 plus an injected future OOF visibility ranking threshold at finish.
Mean scored-window chosen-joint visibility is its ranking score, never probability.
Unspecified policy returns not_run and exposes no events. Two future OOF policies
(own optimal and nearest-A2 coverage) require distinct configured instances; neither
is fitted/selected here. With a configured policy, provisional emitted A0v exposure
survives final low-visibility abstention. A2 stays not_run until future valid maps.

A1 preserves fixed warm-up median, reset at3s, causal EMA, descent/return thresholds,
minimum duration and0.3s continuous standing within1.5s. Observed return must precede30s;
tail confirms only existing returns. No synthesized finish frames. Source discontinuities,
missing joints and gate closure discard partial state; recovery cannot finish stale cycles.

A completed geometric A1 candidate is defined at its observed standing return, BEFORE
confirmation or quality rejection. Its excursion/duration enter the previous-five
population only AFTER computing its own references; failed confirmation and rejected
candidates remain in history. This resolves the earlier draft boundary explicitly.
A2-H snapshots RAW A1 history before a gated candidate starts, keeping that snapshot
through its later return/confirmation even if RAW A1 completes earlier. This prevents
the same physical cycle from entering its own reference while keeping rejected past
candidates in the reference population.

A2-H keeps causal movement history across ordinary below-threshold gate closure so
startup can accumulate variance; it resets partial cycles on every closure and clears
motion history at source interruptions. g uses only post-reset trailing6s. Zero variance
produces zero movement via epsilon, never perfect support. Hard visibility (>20% low
frames in trailing2s), source gap>0.5s or two poses latches hard_gate; final answer/map
eligibility never recovers within that window. Missing-angle/invalid-source errors
remain errors. Every earlier displayed event stays immutable, including after error
or hard abstention. Gate display uses closed Reason values via reason_message.

Candidate q uses start-through-confirmation evidence available AT display, including
confirmation frames. Cycle excursion/duration references still use observed return.
Reject q below selected threshold; never display it retrospectively. Whole summaries
exclude tail frames: vis/gapfree min(worst retained-cycle,whole scored window), amp/intv
worst retained-cycle; no retained cycle => amp/intv0,no_cycle1. Mean g is scored-frame
mean. Missing scored metadata makes the map vector unavailable. Gap support uses
union of reported missing/late and inferred absent nominal slots, counted once.
Window expected slots cover the full [3,30) scheduled grid, even when source is missing.

## Configuration, ownership and deferred validation

config/features.json records fixed protocol constants; search_space.json records the
finite grid. CounterConfig validates selected grid values. No file is auto-loaded:
current protocol constants are mirrored in source and require later consistency checks;
no arbitrary external config, fitting or label access is introduced. DL1 must enforce
FrameBatch/trace128MiB limits and reconcile producer metadata; scalar inputs are bounded
by60s/120fps/7201 frames. CLI remains existing A1-only development interface, unchanged.

Next authorized checks: all arm/prefix/boundary cases, A0 shared-confirmation convention,
late/deadline/truncation, missing metadata and sticky gates, raw versus filtered counts,
candidate reference history, evidence-slot unions, no-cycle summaries, numerical extremes,
A0v policies, source-error exposure and config/provenance parity. These are DEFERRED,
not tests or held-out expected data authored here. Static AST/JSON/diff review cannot
establish integration, real accuracy, calibrated confidence or device readiness.

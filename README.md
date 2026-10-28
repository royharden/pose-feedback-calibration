# pose-feedback-calibration

M17 source-only foundation. Runtime unverified; no measured accuracy or calibration result.

Authoritative adopted plan: `../planning/promoted/PLAN-M17-v1.md`. Coordination and transcripts remain outside this product repository.

This milestone implements the A1 scalar-angle state machine and numeric feature contracts.
It does not perform pretrained landmark inference. A future adapter must choose the side from
warm-up joint visibility, apply pixel-aspect correction, and supply one finite knee angle per
frame. The core fixes its standing reference to the median valid first-three-second angles.
One `Counter` instance owns one stream; scoring starts at 3 s and observed returns must precede
30 s. Tail samples can confirm an existing return. They cannot start a new scored candidate.

The A1 counter applies a causal time-based EMA, descent/return hysteresis, minimum duration,
continuous 0.3 s standing confirmation and a 1.5 s confirmation deadline. Incomplete returns
are tagged at finish, never synthesized. Emitted events are immutable: later input errors
leave them visible while setting the final answer to null. Offline display timestamps use
the media-seconds domain and input-stream scope; do not subtract host clock times from them.
`candidate_count` includes eligible observed returns, including unconfirmed ones;
`filtered_count` is confirmed A1 events. A1 has no q/movement/confidence filtering.
Finishing before the scored interval ends is an incomplete-window error. The CLI preserves
emitted events in error JSON and returns a nonzero exit code on source/core errors.

`features.py` supplies bounded amplitude/duration consistency, union-counted missing/late
slots, trailing-six-second movement, q, and the six-input window feature vector.
The movement input hip coordinates must already be normalized by a valid warm-up torso
length. It rejects future/pre-reset/nonmonotonic inputs. Feature summaries and A2-H gate
wiring are deferred. No probability is fabricated: `p_exact` is always null.

The JSONL example is builder-authored synthetic **development** input, not independent
evaluation data. There are no held-out answers, independent schedules, or real media here.
The CLI labels input as synthetic; it cannot establish data rights or protect private paths.
Do not pass real-derived traces to this seam. Human admission, rights, private-root enforcement,
held-out custody and study execution require separate authorized work.

After Dirty Mode closes and an operator authorizes runtime checks, the proposed local journey is:

```powershell
$env:PYTHONPATH = 'src'
python -m posecount.cli --synthetic examples/synthetic_development.jsonl
```

This command has **not been run**. No dependencies are needed by the source core. Packaging
declares Python 3.12 and setuptools; neither installation nor wheel compatibility was checked.

Integration seams: `AngleFrame -> Counter.update -> tuple[Event, ...]`, then idempotent
`Counter.finish -> Prediction`; the CLI only serializes this result. Config supports the frozen
A1 grid (tau 0.1/0.2 s, margin 25/40 degrees, minimum duration 0.6/1.0 s). No cross-app imports.
This is a partial numeric seam, not the plan's full 33-landmark `FrameBatch` or source adapter.

Deferred: execute meaningful boundary/prefix/error tests; validate warm-up/EMA and event
timing against independently authored cases; add geometry/side selection and full source
contracts; wire A2-H gates/window summaries; add all other arms, calibration, custody,
privacy enforcement and reports. No model downloads, camera, real-data or device work,
installs, runtime tests, network calls, spend, keys, or pushes occurred in this milestone.
This counter supplies no form, medical, exercise-safety or coaching judgment.

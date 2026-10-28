# Guarded device/live producer seam

Source construction only; runtime, imports, compatibility, devices, preview,
permissions, measurements and study admission remain unverified. No command starts
this path. No raw image, session, timing value or device observation was produced.
The existing model/rights/G0/G1/offline/private-boundary gates remain pending Roy.

## Adapter and timing

VideoSource/CameraSource keep `read() -> FrameBatch | None`, source errors and
existing authorization, manifest/hash/runtime-origin/PrivacyPolicy checks.
Constructors add optional `preview_authorized=False`, which never grants real
processing permission. Device stage instrumentation uses latency.anchor_now()
(`perf_counter_ns`, `process_monotonic_ns`, shared latency.PROCESS_SCOPE UUID).
The separate original receive_ns/source scope and media times stay unchanged.

`read_receipt() -> DeviceReadReceipt | None` calls the same existing read path:
None is clean EOF. DeviceReadReceipt fields are batch, capture_return,
preprocess, inference, failure_reason, dropped_since_read, overwritten_since_read.
Successful batch is the actual validated FrameBatch; failed batch is null with a
named failure_reason and only reached anchors. No raw image enters this receipt.
Unobservable backend drop/overwrite counts stay null, even with a synchronous slot.
Anchors are observed immediately after capture.read return, after preprocessing
conversion, and after detector return. Failure cannot synthesize an unreached
anchor. Failed inference can retain capture/preprocess while inference stays null.
No stage value is fabricated from read completion, nominal FPS or media time.

In the live bridge a failed receipt becomes InstrumentedReadFailure carrying only
reason/anchors. run_session records one failed-attempt Span with null counter/render
anchors, increments failed_source_reads, and terminates through its normal error
and cleanup path. failed_source_reads is separate from accepted source_frames;
the existing source_frames = processed_frames + controller_dropped identity holds
for accepted typed batches. Sample retention and first-five-active-second exclusion
are unchanged. Generic uninstrumented sources retain unknown source-stage values.

## Single-frame private preview

Only explicit preview authorization permits the adapter to retain the single
current validated decoded frame. The next read, close, EOF or failure clears the
adapter's prior reference. `consume_preview(batch, *, authorization)` checks the
current source/device authorization, verified-boundary assertion and exact current
batch association; it transfers the pending image once. Wrong/stale/repeated access
fails closed; there is no unconditional getter, image history, image serialization,
image field in FrameBatch, or raw image in aggregate output.

This capability is for the trusted approved local renderer. The caller can retain
an image after transfer; Python references and native libraries are not hostile
operator isolation or a memory-erasure guarantee. Runtime/library internal buffer
retention is unaudited. An immutable approved local environment and current operator
authorization remain required. No raw pixels may enter coding-model context,
logs, Git/sync roots, traces or public output. Existing image dimension/byte bounds
precede preprocessing and inference; the adapter stores no unbounded raw history.

## Explicit wrapper

`run_device_session(*, manifest,privacy,device_authorization,
session_authorization=SessionAuthorization(),preview_authorized=False,
pixel_aspect,video_path=None,camera_index=None,counter=None,gate_reason=counter_gate_reason,
stop_requested=...,max_seconds=60,max_frames=7201) -> SessionResult` selects
exactly one explicit input. Both default session denial and preview denial occur
before opening. Real-session receipt digests, rights assertion, all four
DeviceAuthorization confirmations and PrivacyPolicy.boundaries_verified are required.
The adapter independently rechecks its existing evidence before optional imports.
There is no discovery, device fallback, networking, download, account, CLI flag,
settings/disconnect change, automatic startup or new development bypass.

Source factory creates the existing VideoSource/CameraSource and opens it; a partial
open error/interruption attempts source.close before reraising. The renderer factory
is called only after source opening succeeds. A later factory/render/read/stop/error
still attempts both close paths. Deadline enforcement remains cooperative; native
operations can block. Hard wall-clock bounds and actual stop/release require later
authorized runtime validation. No retry/spin is added.

The wrapper reads DeviceReadReceipt into live.ReadReceipt. Its image callback is
the sole raw path from consume_preview to approved OpenCV drawing/imshow. It draws
`Provisional count` and the existing gate_message, and neither logs nor writes the
image. OpenCV stays lazy; source evidence checks happen before renderer loading.
The renderer anchors imshow return before waitKey; neither sensor exposure nor
display photons are measured. Existing emitted events/media timestamps are
immutable and remain retained across later read/preview/render failures.

## Counter-owner reconciliation

The integrated public `counter.counter_gate_reason(counter, latest_scalar)` is the
safe default in both run_session and run_device_session. It reports already-computed
current/past gate state without finishing/mutating the counter, future samples,
private-state inspection or duplicated movement/evidence math. The wrapper forwards
the default or explicit override unchanged. The controller passes the exact final
attached scalar object most recently accepted by the same Counter.update, after
all current conversion/warmup replay outputs and before display.

The callback signature is `(counter: Counter, latest_scalar: AngleFrame) -> Reason
| None`: a callback result of None means the CURRENT gate is open; blocked gates
use closed Reason messages. Explicit parameter gate_reason=None disables the
producer and stays failclosed as `not counting: evidence_metadata_unavailable`
(Reason.EVIDENCE_UNAVAILABLE). No scalar output during buffered warmup uses
Reason.WARMUP. Invalid callback results cause the existing sanitized session error
and cleanup path. No final confidence, fitness or native-device success is inferred.
Actual live readiness remains unverified.

## Deferred validation

AST/diff/manual source review only during Dirty Mode. Future authorization must
exercise original read compatibility, stage ordering/shared scope and failure-null
anchors; preview default denial, matching/stale/repeated batch rejection, one-frame
clearing on read/EOF/failure/close, and guard revocation; partial open/read/render/
interruption/close cleanup and retained emitted exposure; counter gate callback;
approved optional-runtime compatibility and hard native operation bounds; actual
two-device three-session timing/offline/permission-denial/invalid-index/no-spin/
second-app release. Receipt digests and booleans are operator commitments, not
independent verification, rights admission, consent proof or vendor telemetry audit.

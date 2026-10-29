# Timing and synchronous viewer source contract

Construction only; runtime, camera, measurements and study admission are unverified.
No CLI command activates this module. No device session was performed. G0/G1,
rights, private data boundaries and independent operator work remain pending Roy.

`posecount.latency` owns numeric timing and device metadata; `posecount.live`
joins the existing LandmarkSource, GeometryAdapter, attach_evidence and Counter.
Neither implements inference or new geometry. Optional OpenCV is imported lazily
inside the future renderer, with no acquisition. A trusted `image_for(batch,state)`
callback supplies an approved local image; existing FrameBatch contains landmarks,
not raw pixels. The guarded run_device_session wrapper now connects an optional
single-frame device preview; see source-device-live.md. Operator admission and
all actual preview/runtime/device validation remain pending.

## Span and aggregate seam

`ClockAnchor(ns, domain, scope)` uses integer nanoseconds, domain
`process_monotonic_ns`, and UUID process scope. `anchor_now()` observes
`perf_counter_ns`; `PROCESS_SCOPE` is shared by this loaded timing module.
`duration(start,end)` returns `Duration(value_ms,reason)`. Unknown reasons are:
`missing_anchor`, `invalid_anchor`, `missing_time`, `nonfinite_time`,
`invalid_nanoseconds`, `clock_domain_mismatch`, `missing_clock_scope`,
`invalid_clock_scope`, `clock_scope_mismatch`, `reversed_time`,
`nonfinite_duration`. Unknown values are null, never zero. Domains/scopes are never
rebased. A consistent UUID supplied by a caller is an assertion, not provenance proof.

`Span(frame_index, elapsed_s, capture_return=None, preprocess=None,
inference=None, counter_update=None, render_return=None)` has these durations:

| Field | Start -> end |
|---|---|
| preprocess_ms | capture_return -> preprocess completion |
| inference_ms | preprocess completion -> inference completion |
| counter_update_ms | inference completion -> counter completion |
| render_ms | counter completion -> imshow return/render enqueue |
| capture_to_render_ms | capture_return -> imshow return/render enqueue |

`Span.to_dict()` is a private per-frame record with frame_index, elapsed_s,
phase, phase_reason, anchors, stages. Geometry warmup replay creates no historical
host render observations; its counter work contributes only to the current frame.
Existing device.receive_ns uses monotonic_ns and a separate source UUID: this
controller deliberately does not relabel it as its own perf_counter anchor.
Generic read() provides no preprocessing/inference timing callbacks. Its capture,
preprocess and inference anchors therefore remain absent. The optional existing
device adapter now offers genuine stage receipts consumed by run_device_session;
see source-device-live.md. Source read completion occurs after inference and cannot
supply a capture anchor.

`SpanWriter(max_samples=7201).append(span)` retains the first bounded samples.
`record_drop(count)`/`record_overwrite(count)` record caller declarations only.
`summary()` returns clock_domain, measurement_boundary, photon_latency_ms=null,
photon_reason, steady_state_excludes_first_s=5, sample_limit, received_spans,
retained_spans, sample_overflow, quantile_population, reported_dropped_frames,
reported_overwritten_frames, drop_accounting and phases. Each phase
(`init_warmup`, `steady_state`, `unclassified`) has span_count and stages. Each
stage has unit, valid_count, unknown_count, unknown_reasons counts, p50, p95, p99,
reason (`no_valid_samples` if empty). Quantiles use sorted x[ceil(p*n)-1].
In session spans, `elapsed_s` is host elapsed since both source and renderer
factories returned; the first 5 seconds of that active interval are excluded from
steady state, regardless of initialization duration. Invalid elapsed has
phase_reason invalid_elapsed_time. Initialization milliseconds cover authorization
and both factories separately from stage spans. Overflow declares a
truncated quantile population; unknown samples are counted, never imputed.

For report consumers, use only `SpanWriter.summary()`,
`SessionResult.aggregate()` and `device_profile_templates()`. Do not serialize
Span, Prediction.events, SessionResult.emitted_events or presentations into
aggregate reports. Those contain individual traces and belong only in an
authorized encrypted private root outside sync/Git. No output writer is provided.

## Guarded session and cleanup

`run_session(source_factory,renderer_factory,authorization=SessionAuthorization(),
input_kind=...,counter=None,read_instrumented=None,gate_reason=counter_gate_reason,
stop_requested=...,max_seconds=60,max_frames=7201)` defaults to denied permission.
Factories are called only after validation. For real video/camera, rights_admitted
must be True and offline_receipt_sha256/private_boundary_receipt_sha256 must be
explicit lowercase digests. These operator commitments do not verify offline
state, telemetry, consent or filesystem boundaries. The existing device adapter
must still run all its own DeviceAuthorization/pin/PrivacyPolicy checks. Callers
must not bypass those checks with a custom factory. Development input declarations
are also trust boundaries; returned source_kind must match input_kind.

The source factory returns an already-open managed source; both factories must
release any partial resources if opening raises before returning. The optional
instrumented reader returns `ReadReceipt(batch,capture_return=None,
preprocess=None,inference=None,dropped_since_read=None,
overwritten_since_read=None)` or None at EOF. Missing source backend counts stay
unknown; the controller cannot observe driver queues. An instrumented reader must
report each drop/overwrite once since the prior read, without double counting.
Source missing/late slot union is separate and is never added to backend counts.

`LatestOneFrame.offer/take` maintains one pending receipt; replacing one increments
overwritten exactly once. This controller reads, offers and takes synchronously:
its slot overwrite count is zero and it makes no read-ahead/backend-latest claim.
Every accepted typed ReadReceipt/FrameBatch increments source_frames and contributes
one span, including failure and deadline-discard paths. Frames whose geometry/counter
processing does not complete increment controller_dropped exactly once; completing
the counter loop increments processed_frames, even if a later gate/render fails.
Thus source_frames = processed_frames + controller_dropped. An invalid receipt that
does not contain a typed FrameBatch is rejected before frame acceptance. Failed
frames retain only reached stage anchors; counter/render anchors stay null when
those stages did not return. Prior emitted events survive partial frame failure.
Source-internal drops/overwrites are null without instrumentation. The session's
timing summary overrides reported_dropped_frames/reported_overwritten_frames with
the same nullable backend counts; drop_accounting is source_backend_uninstrumented
if either is unknown, otherwise caller_reported_not_driver_verified. A known count
remains numeric when the other is unknown. Slot overwrites, controller drops and
the source missing/late slot union are separate and are never added to these fields.
No LIVE_STREAM parity, sensor exposure or camera-to-photon timing is asserted.

The max_seconds deadline covers the active interval after both factories return;
initialization is measured separately and excluded from that budget. The deadline
is cooperative, checked before reads, after reads and after renders. A
blocking native open/read/render cannot be forcibly preempted by this synchronous
controller. Future real sessions require a separately verified bounded backend;
the current source API does not establish a hard 60-second wall-clock guarantee.
There is no retry/spin on permission denial, invalid index or source error.
Normal EOF, stop, timeout, callback error and interruption all attempt renderer
close then source close, even when one close fails. Cleanup failures are errors.

The default `counter_gate_reason(counter,latest_scalar)` public producer supplies
the current causal gate as a closed Reason or a callback result of None for open.
It receives the exact final attached scalar object most recently passed successfully
to that same Counter.update, after the conversion/replay loop and before rendering.
No copy, pre-attach scalar or stale warmup object is substituted. An explicit
caller callback overrides the default; explicit parameter gate_reason=None disables
the producer and displays `not counting: evidence_metadata_unavailable` (closed
Reason.EVIDENCE_UNAVAILABLE), never an inferred open gate. No output during warmup
displays the closed Reason.WARMUP. Open means current gate only, not final confidence,
fitness or device success. The callback does not finish/mutate/recompute the counter.
DisplayState fields
are provisional_count, newly_emitted, gate_message, provisional=True. All counter
emissions are retained before rendering; late refusal/stop/failure cannot erase
them. Gate status never changes Counter events. Count/provisional labels are
instructions to the trusted image callback, whose visual output is unverified.

`RenderReceipt(render_return=None,stop_requested=False)` is supplied by a renderer.
OpenCVRenderer records its anchor immediately after imshow and before waitKey;
Esc/q requests stop. It destroys only its own fixed window, never global windows.
`HostPresentation(event_ids,render_return)` records the renderer boundary separately;
it does not rewrite immutable Event.t_display/media timestamps or prove photons.

`SessionResult` fields: status, stop_reason, prediction, emitted_events,
presentations, source_frames, processed_frames, source_unavailable_slots,
backend_dropped, backend_overwritten, slot_overwritten, controller_dropped,
failed_source_reads (instrumented failed attempts without an accepted batch),
cleanup_errors, timing, initialization_ms, initialization_reason. The aggregate
includes status/stop_reason, prediction_status/final_count, provisional_count,
presentation_receipts, frame/count fields, backend_counts_reason,
cleanup_errors, timing, initialization fields and explicit null
sensor_exposure_ms/display_photon_ms/live_stream_parity. Empty source/failures
cannot establish successful timing. Prediction remains the original counter
result; session status separately records interrupted/partial execution.

## 2 devices, not a device survey

`device_profile_templates()` returns heading, status=unverified_not_run,
physical_distinctness=null and two device slots with three session templates each.
Only protocol parameters are filled; all observed values remain null.

DeviceProfile fields: machine_slot (device_1/device_2), requested_width=640,
requested_height=480, physical_distinctness_verified, os_family, cpu_description_sha256,
cpu_cores, ram_gib, python_version, runtime_sha256, model_sha256,
configuration_sha256, cpu_delegate_confirmed, python312_deviation,
deviation_receipt_sha256, rights_receipt_sha256, supported, sessions.
Its dict adds observation_status=unverified_operator_receipts and receipt_trust_limit.
CPU/SDK detailed descriptions are held in private digest-bound receipts, avoiding
personal names, serials, paths and individual traces in aggregate reports.

SessionReceipt fields: session_number (1..3), requested_duration_s=60,
actual_duration_s, actual_width, actual_height, actual_source_fps,
actual_processed_fps, source_frames, processed_frames, dropped_frames,
overwritten_frames, initialization_ms, offline_fps,
permission_denial_observed, invalid_index_observed, no_retry_spin_observed,
stop_release_observed, second_app_open_observed, prior_settings_restored_observed,
offline_verified_observed, offline_receipt_sha256, supported.

Two slots do not establish two physically distinct machines. A future operator
must record physical distinction, actual hardware/runtime/model/conditions,
3x60-second sessions, denial/invalid-index/no-spin and second-app release, and
native offline receipts. No settings are edited here. Unsupported platforms
remain null/unverified. Digests and operator assertions are not independent proof.
Timing summaries remain separate from unpopulated device receipts until real runs.

Deferred validation: known-clock duration and nearest-rank cases; malformed/mixed
scope and phase cases; latest-slot overwrite accounting; failure/timeout/stop
cleanup including failed opens; event exposure under render failure; gate/image
callback integration; hard backend bounds; optional-runtime compatibility;
two physical devices, actual FPS/resolution/three sessions and operator offline,
denial/invalid-index/second-app release. No tests or runtime checks ran in Dirty Mode.

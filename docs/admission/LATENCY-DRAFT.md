# DRAFT — latency and native-device observation checklist

Unsigned; all receipts blank and all operations unperformed. This describes future
operator work under immutable PLAN-M17-v1.md sections 9/10/13. It appoints no operator,
asserts no rights and authorizes no network/settings/camera/device changes. G0/G1,
exact model/runtime rights, machine availability and explicit activation remain pending.

## Measurement boundary

Heading for a future populated table: **2 devices, not a device survey**.
Use two physically different existing Python-capable machines, same approved pinned
model/CPU delegate and reported conditions. Repeated extraction/latency uses DEV footage
only. No per-device held-out extraction. Exact model/SDK/defaults/OS acquisition and
rights evidence must be pinned; no latest alias, auto-download or silent runtime fallback.
Check Python3.12 wheel availability later; any device-extra-only version deviation
requires a recorded convention/approval before use.

Per machine: three 60s live sessions, requested640×480, actual resolution/FPS recorded.
Exclude first5s from steady-state quantiles; report initialization/warm-up separately.
Synchronous VIDEO-mode latest-one-frame buffer logs EVERY overwrite/drop, source and
processed counts. No LIVE_STREAM parity assertion. Requests are protocol parameters,
not achieved rates or measured results.

| Future clock/result field | Contract |
|---|---|
| Media event times | Source-media seconds for observed return/confirmation, distinct from host clocks. Offline display may equal confirmation media time with explicit domain/scope. |
| Host spans | perf_counter_ns domain process_monotonic_ns, UUID process scope. Anchors capture_return/preprocess/inference/counter_update/render_return. |
| End-to-end | capture-return to OpenCV imshow return/render enqueue; not camera-to-photon latency. Sensor exposure/display photons are unknown. |
| Invalid spans | Missing, reversed, nonfinite or mixed-domain/scope anchors => unknown/null with bounded reason; never zero or subtraction across scopes. |
| Quantiles | Sorted valid samples x[1..n], nearest-rank p50/p95/p99 = x[ceil(p*n)], n>0; n=0 => null with reason. Report support/exclusions/units. |
| Device row | OS/CPU/cores/RAM/Python/deviation/SDK/delegate/model hash, actual resolution/rates, sessions/source/processed/drop counts, each stage quantiles, init ms and offline FPS. All unmeasured values remain null. |

## Future operator checklist — no action performed

- Confirm consent/admission, exact approved model/runtime rights and private storage;
  approve impact on other users/sessions before any native run.
- Record prior interface state; disconnect all active Wi-Fi/Ethernet/cellular/VPN
  paths and verify offline state. If unavailable/unverified, STOP private-data use.
- Run only the authorized process, close it BEFORE restoring recorded network state;
  record receipt. Claim only successful outbound transport unavailable during the
  measured run. Queued telemetry/vendor internals remain unaudited.
- Keep own-code socket-blocked fixture and later Docker network-none checks separate;
  neither establishes vendor telemetry absence. Optional process firewall diagnostic
  needs separate operator permission and cannot establish general no-telemetry.
- Record normal/denied/unavailable/invalid-index outcomes separately, without retry
  spin. On Windows, future operator temporarily disables desktop camera access in
  Privacy & security > Camera; on macOS, owning terminal/launcher permission in
  Privacy & Security > Camera, relaunch if needed. Preserve/restore prior settings.
- Close/release device; verify a second ordinary camera app can open it. Other
  platforms require equivalent observed procedures or stay unverified.

| Future receipt field | Value |
|---|---|
| Operator identity/approval/date | |
| Machine A / machine B commitments | |
| Rights/model/runtime/config pins | |
| Prior interface state / offline proof / restoration | |
| Three session receipts per machine / actual rates | |
| Permission denial / invalid index / restoration | |
| Stop/release / second-app observation | |
| Independent observer sign-off | |

Later validation: known10ms/fake-clock arithmetic, nearest-rank/empty support, invalid
anchors/domains/scopes, overwrite counts, actual devices/offline/camera procedures.
No runtime, tests, camera, browser, settings, network or device operations ran here.

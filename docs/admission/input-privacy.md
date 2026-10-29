# Input and privacy admission — DRAFT / UNSIGNED

Preparation only. This document implements no enforcement and admits no data. G0/G1, consent, independent roles, rights and disposition of historical pre-G0 source remain PENDING — needs Roy. Existing scalar source does not establish the plan's required pre-code ordering. Normative source: OUTER planning/promoted/PLAN-M17-v1.md sections 3, 4, 6 and P1/P3. The promoted plan prevails on conflict.

## Proposed source boundary

`LandmarkSource.read() -> FrameBatch` is a future interface, not an existing import. Each batch carries strictly increasing finite nonnegative source/media seconds; optional receive-monotonic timestamp with explicit clock domain and process scope; source/model/runtime identifiers and status; explicit missing/late slots; and zero, one or two poses. A pose has exactly 33 named landmarks, each with finite x/y/z plus distinct visibility and presence values. Confidence values must be bounded [0,1]; missing presence cannot be silently copied from visibility. Missing pose/joint values need explicit status rather than fabricated coordinates. The source convention, frame width/height and pixel aspect must be known and valid; conversion failures produce named errors. The exact serialized schema remains a future DL1/DL2 seam reconciliation, not a second schema in these docs.

Reject wrong dimensions, nonfinite numbers, nonmonotonic time, more than two poses, streams beyond 60 seconds, source rates above 120 fps and decoded traces beyond 128 MiB. Validate before allocation/processing where possible and cap cumulative decoded size. A second pose is a refusal signal, not permission to track identities. Missing/late slots use a union so a slot is not counted twice. Source errors remain explicit; never return a successful zero count. No labels, names, split truth or gold enter inference.

Future geometry uses pixel-aspect-corrected 2D hip–knee–ankle angles. Choose side once from the higher first-three-second mean hip/knee/ankle visibility, tie left; invalid standing reference gives named error/abstention. Use the median valid warm-up angles for the standing reference. Reset partial cycles at 3 seconds; score [3,30). Tail may confirm an eligible observed return before 30 seconds, never start a new scored candidate. Aspect correction does not fix foreshortening. Existing `AngleFrame` is only a partial scalar seam; a future adapter must preserve missing-data and visibility semantics without treating presence as visibility.

Keep media seconds and host monotonic times separate. Display uses an explicit domain/scope; offline display is confirmation media time. Never subtract media and host times or anchors from different process scopes. Bounds and conventions are contracts awaiting executable checks, not measured compatibility.

## Private-root admission checklist for a future operator

All boxes remain unchecked; do not populate this document with private records.

- [ ] Roy accepts encrypted, local, operator-supplied storage (proposed `C:\PrivateData\M17\`) and names its owner; consent and withdrawal/retention procedure are accepted.
- [ ] Resolve the intended root and every actual input/output path through symlinks/junctions; reject unresolved or unverifiable boundaries. Revalidate resolved destinations at use to address path substitution, not merely lexical prefix checks.
- [ ] Reject containment in every configured sync root, at least PJ-OD and OneDrive/OneDriveConsumer/OneDriveCommercial roots, using path-component boundaries and Windows case handling. Unknown configured roots or verification failure deny admission.
- [ ] Reject `.git` containment and Git working trees, including external-git-dir and linked worktrees; absence of an in-directory `.git` directory is insufficient. Check actual path ancestry with appropriate Git discovery; failure to establish a safe boundary denies admission. Do not scan home directories for data.
- [ ] Apply the boundary to video, consent/name mappings, traces, individual labels, event/failure records, temporary files and derivatives. Keep every such artifact outside sync/Git; no real records in repository fixtures, logs, reports or coding-model context.
- [ ] Human operator verifies approved native offline procedure before private processing; unverified offline state stops private-data use. Runtime/device work requires later authorization.
- [ ] Only bounded redacted aggregates/commitments reach coding agents. A digest establishes byte identity, never consent, anonymity or rights.
- [ ] Raw video deletion within proposed 90 days after closeout and traces/labels within proposed 180 days are explicitly agreed or separately replaced in writing. Withdrawal deletes affected derivatives, invalidates the sealed edition and stops affected use.

## Unfilled admission fields

Storage owner: __________; actual root commitment: __________; consent/retention receipt: __________; role-holder commitments: __________; rubric/roster/split/gold commitments: __________; exact rights evidence digest: __________; two physical-machine commitments: __________; G0 signature/date: __________; G1 reconciliation/agreement receipt: __________.

G0 requires actual named roles/machines, 16 adult consents, all 192 private valid clips, both blind CSVs complete, at least 90% mutually scoreable windows in each split, frozen commitments and rights evidence. G1 additionally reconciles admitted hashes and dev agreement >=0.80 before tuning; held-out agreement stays in the custodian/scorer channel. Neither this checklist nor agent review supplies those receipts. Failure means stop/skip under the frozen plan; no synthetic-only substitute. Product construction requires INT's explicit new grant and Roy's ordering/gate disposition.

"""Guarded private label journal. Source construction only; runtime unverified.

The trusted host supplies authorization, frozen schema/window pins and private
storage policy. Pins identify bytes, never consent or permission. Journal files
are create-only full snapshots; an external custodian must retain the latest
sequence/digest to detect rollback. Local file owners can defeat these controls.
No rows, free text or paths belong in logs or builder-facing reports.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from .privacy import PrivacyError, PrivacyPolicy

MAX_BYTES = 4_000_000
MAX_ROWS = 4096
MAX_WINDOWS = 1024
MAX_EVENTS = 256
MAX_REVISIONS = 4096
MAX_CELL = 2048
CSV_FIELDS = (
    "window_id", "annotator_code", "source_sha256", "movement",
    "return_media_timestamps", "count", "scoreable", "notes", "revision",
)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
Authorize = Callable[[str, str], bool]


class SourceError(ValueError):
    """Only fixed reason codes, never input values, are exposed."""


@dataclass(frozen=True, repr=False)
class WindowSpec:
    source_sha256: str
    movement: str
    split: str


@dataclass(frozen=True, repr=False)
class BlindVote:
    window_id: str
    annotator_code: str
    source_sha256: str
    movement: str
    return_media_timestamps: tuple[float, ...]
    count: int | None
    scoreable: bool
    notes: str
    revision: int = 0


@dataclass(frozen=True, repr=False)
class Decision:
    count: int | None
    scoreable: bool
    return_media_timestamps: tuple[float, ...]


@dataclass(frozen=True, repr=False)
class Revision:
    window_id: str
    revision: int
    old: Decision
    new: Decision
    reason: str


@dataclass(frozen=True)
class LabelSummary:
    windows: int
    original_votes: int
    revisions: int
    blind_frozen: bool
    sequence: int
    journal_sha256: str
    dataset_sha256: str


def _fail(reason: str) -> None:
    raise SourceError(reason)


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail("invalid_identifier")
    return value


def _sha(value: object) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        _fail("invalid_digest")
    return value


def _text(value: object, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > MAX_CELL:
        _fail("invalid_text")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        _fail("invalid_text")
    if required and not value.strip():
        _fail("reason_required")
    return value


def _decision(count: object, scoreable: object, times: object) -> Decision:
    if type(scoreable) is not bool or not isinstance(times, (tuple, list)):
        _fail("invalid_decision")
    if len(times) > MAX_EVENTS:
        _fail("event_limit")
    if any(type(t) not in (int, float) or not 3 <= t < 30
           or not math.isfinite(t) for t in times):
        _fail("invalid_return_timestamp")
    values = tuple(float(t) for t in times)
    if any(a >= b for a, b in zip(values, values[1:])):
        _fail("unordered_returns")
    if scoreable:
        if type(count) is not int or not 0 <= count <= MAX_EVENTS or count != len(values):
            _fail("count_timestamp_mismatch")
    elif count is not None or values:
        _fail("unscoreable_requires_unknown_count")
    return Decision(count, scoreable, values)


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    _fail("invalid_json_constant")


def _decision_json(value: Decision) -> dict:
    return {"count": value.count, "scoreable": value.scoreable,
            "return_media_timestamps": list(value.return_media_timestamps)}


def _decision_from_json(value: object) -> Decision:
    if not isinstance(value, dict) or set(value) != {"count", "scoreable", "return_media_timestamps"}:
        _fail("invalid_decision_schema")
    return _decision(value["count"], value["scoreable"], value["return_media_timestamps"])


class LabelSource:
    """Inert constructor; all I/O requires an explicit authorized operation.

    ``schema_sha256`` pins the human-approved schema/rubric artifact externally;
    CSV syntax is exactly CSV_FIELDS, with revision 0 for original blind votes.
    The host must enforce blindness outside this process. No builder read API is
    supplied. Readers require labels.read plus labels.custodian or labels.scorer.
    The same role checks cover dev and heldout; permission is rechecked per call.
    """

    def __init__(self, expected_windows: Mapping[str, WindowSpec], *,
                 schema_sha256: str, policy: PrivacyPolicy,
                 journal_directory: Path, authorize: Authorize) -> None:
        if not callable(authorize) or not isinstance(policy, PrivacyPolicy):
            _fail("trusted_host_required")
        if not isinstance(journal_directory, Path):
            _fail("private_path_required")
        if not 1 <= len(expected_windows) <= MAX_WINDOWS:
            _fail("window_limit")
        copied = {}
        for key, spec in expected_windows.items():
            _identifier(key)
            if not isinstance(spec, WindowSpec):
                _fail("invalid_window_spec")
            _sha(spec.source_sha256)
            _identifier(spec.movement)
            if spec.split not in ("dev", "heldout"):
                _fail("invalid_split")
            copied[key] = spec
        self._windows = MappingProxyType(copied)
        self._schema = _sha(schema_sha256)
        self._dataset = hashlib.sha256(_encode({"schema": self._schema, "windows": {
            k: [v.source_sha256, v.movement, v.split] for k, v in copied.items()
        }})).hexdigest()
        self._policy, self._directory, self._authorize = policy, journal_directory, authorize
        self._votes: tuple[BlindVote, ...] = ()
        self._revisions: tuple[Revision, ...] = ()
        self._imports: tuple[str, ...] = ()
        self._frozen = False
        self._sequence = 0
        self._digest = "0" * 64

    def _allow(self, action: str, subject: str | None = None) -> None:
        try:
            allowed = self._authorize(action, subject or self._dataset)
        except Exception:
            raise SourceError("authorization_failed") from None
        if allowed is not True:
            _fail("permission_denied")

    def _reader(self) -> None:
        self._allow("labels.read")
        try:
            role = (self._authorize("labels.custodian", self._dataset) is True
                    or self._authorize("labels.scorer", self._dataset) is True)
        except Exception:
            raise SourceError("authorization_failed") from None
        if not role:
            _fail("permission_denied")

    def _read(self, path: Path, expected_sha256: str) -> bytes:
        _sha(expected_sha256)
        try:
            canonical = self._policy.validate(path)
            with canonical.open("rb") as stream:
                data = stream.read(MAX_BYTES + 1)
        except (OSError, PrivacyError, ValueError):
            raise SourceError("private_read_failed") from None
        if len(data) > MAX_BYTES:
            _fail("file_limit")
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            _fail("source_digest_mismatch")
        return data

    def summary(self) -> LabelSummary:
        self._allow("labels.summary")
        return self._summary()

    def _summary(self) -> LabelSummary:
        return LabelSummary(len(self._windows), len(self._votes), len(self._revisions),
                            self._frozen, self._sequence, self._digest, self._dataset)

    def _snapshot(self, votes: tuple[BlindVote, ...], revisions: tuple[Revision, ...],
                  imports: tuple[str, ...], frozen: bool) -> dict:
        return {"version": 1, "dataset": self._dataset, "schema": self._schema,
                "sequence": self._sequence + 1, "previous": self._digest,
                "imports": list(imports), "frozen": frozen,
                "votes": [{"window_id": v.window_id, "annotator_code": v.annotator_code,
                           "source_sha256": v.source_sha256, "movement": v.movement,
                           "notes": v.notes, "revision": 0,
                           **_decision_json(Decision(v.count, v.scoreable, v.return_media_timestamps))}
                          for v in votes],
                "revisions": [{"window_id": r.window_id, "revision": r.revision,
                               "old": _decision_json(r.old), "new": _decision_json(r.new),
                               "reason": r.reason} for r in revisions]}

    def _commit(self, votes: tuple[BlindVote, ...], revisions: tuple[Revision, ...],
                imports: tuple[str, ...], frozen: bool) -> LabelSummary:
        self._allow("labels.journal.write")
        data = _encode(self._snapshot(votes, revisions, imports, frozen))
        if len(data) > MAX_BYTES:
            _fail("journal_limit")
        path = self._directory / f"labels-{self._sequence + 1:08d}.json"
        try:
            canonical = self._policy.validate(path, must_exist=False)
            # Exclusive create prevents replacement; no cleanup/delete on failure.
            with canonical.open("xb") as stream:
                stream.write(data)
                stream.flush()
                import os
                os.fsync(stream.fileno())
        except (OSError, PrivacyError, ValueError):
            raise SourceError("private_journal_write_failed") from None
        self._votes, self._revisions, self._imports, self._frozen = votes, revisions, imports, frozen
        self._sequence += 1
        self._digest = hashlib.sha256(data).hexdigest()
        return self._summary()

    def import_csv(self, path: Path, *, annotator: str, expected_sha256: str) -> LabelSummary:
        if annotator not in ("A", "B") or self._frozen or annotator in self._imports:
            _fail("invalid_blind_import_stage")
        self._allow("labels.import." + annotator)
        self._allow("labels.custodian")
        data = self._read(path, expected_sha256)
        try:
            text = data.decode("utf-8-sig", errors="strict")
            reader = csv.reader(io.StringIO(text, newline=""), strict=True)
            if tuple(next(reader)) != CSV_FIELDS:
                _fail("invalid_csv_header")
            votes = []
            seen = set()
            for row in reader:
                if len(votes) >= MAX_ROWS or len(row) != len(CSV_FIELDS):
                    _fail("invalid_csv_size")
                for cell in row:
                    _text(cell)
                item = dict(zip(CSV_FIELDS, row))
                window = _identifier(item["window_id"])
                if window not in self._windows or window in seen:
                    _fail("unknown_or_duplicate_window")
                spec = self._windows[window]
                if (item["annotator_code"] != annotator or item["revision"] != "0"
                        or item["source_sha256"] != spec.source_sha256
                        or item["movement"] != spec.movement):
                    _fail("vote_pin_mismatch")
                if item["scoreable"] not in ("true", "false"):
                    _fail("invalid_scoreable")
                scoreable = item["scoreable"] == "true"
                count_text = item["count"]
                if count_text and not re.fullmatch(r"0|[1-9][0-9]{0,2}", count_text):
                    _fail("invalid_count")
                decision = _decision(int(count_text) if count_text else None, scoreable,
                                     json.loads(item["return_media_timestamps"],
                                                parse_constant=_reject_constant))
                votes.append(BlindVote(window, annotator, spec.source_sha256, spec.movement,
                                       decision.return_media_timestamps, decision.count,
                                       decision.scoreable, item["notes"]))
                seen.add(window)
            if seen != set(self._windows):
                _fail("incomplete_blind_import")
        except (UnicodeError, csv.Error, StopIteration, json.JSONDecodeError, RecursionError,
                OverflowError, TypeError):
            raise SourceError("invalid_csv") from None
        return self._commit(self._votes + tuple(votes), self._revisions,
                            self._imports + (annotator,), False)

    def freeze_blind(self) -> LabelSummary:
        self._allow("labels.freeze")
        self._allow("labels.custodian")
        if self._frozen or set(self._imports) != {"A", "B"}:
            _fail("incomplete_or_frozen_blind_stage")
        return self._commit(self._votes, self._revisions, self._imports, True)

    def original_votes(self, *, split: str) -> tuple[BlindVote, ...]:
        self._reader()
        if split not in ("dev", "heldout"):
            _fail("invalid_split")
        self._allow("labels.read." + split)
        return tuple(v for v in self._votes if self._windows[v.window_id].split == split)

    def _resolved(self, window: str) -> Decision:
        changes = [r for r in self._revisions if r.window_id == window]
        if changes:
            return changes[-1].new
        votes = [v for v in self._votes if v.window_id == window]
        if len(votes) == 2 and all(v.scoreable for v in votes):
            left, right = (Decision(v.count, v.scoreable, v.return_media_timestamps) for v in votes)
            if left == right:
                return left
        return Decision(None, False, ())

    def adjudicate(self, window_id: str, *, count: int | None, scoreable: bool,
                   return_media_timestamps: tuple[float, ...], reason: str) -> LabelSummary:
        _identifier(window_id)
        if not self._frozen or window_id not in self._windows or len(self._revisions) >= MAX_REVISIONS:
            _fail("invalid_adjudication_stage")
        # Host verifies actual joint approval; annotator strings are never credentials.
        self._allow("labels.adjudicate.A", window_id)
        self._allow("labels.adjudicate.B", window_id)
        self._allow("labels.custodian")
        new = _decision(count, scoreable, return_media_timestamps)
        old = self._resolved(window_id)
        revision = 1 + sum(r.window_id == window_id for r in self._revisions)
        record = Revision(window_id, revision, old, new, _text(reason, required=True))
        return self._commit(self._votes, self._revisions + (record,), self._imports, True)

    def resolved_votes(self, *, split: str) -> Mapping[str, Decision]:
        self._reader()
        if not self._frozen or split not in ("dev", "heldout"):
            _fail("invalid_resolution_stage")
        self._allow("labels.read." + split)
        return MappingProxyType({k: self._resolved(k) for k, spec in self._windows.items()
                                 if spec.split == split})

    def revisions(self) -> tuple[Revision, ...]:
        self._reader()
        self._allow("labels.read.heldout")
        self._allow("labels.read.dev")
        return self._revisions

    def restore(self, path: Path, *, expected_sha256: str, expected_sequence: int) -> LabelSummary:
        """Explicit externally pinned restart, never select newest by directory scan.

        Complete snapshot is validated before installation. Restoring does not
        rewrite a file or establish approval. External pins prevent stale choice;
        this journal is not a hostile-operator or cross-process locking service.
        """
        self._allow("labels.journal.restore")
        self._allow("labels.custodian")
        if self._sequence or self._votes or type(expected_sequence) is not int or expected_sequence < 1:
            _fail("invalid_restore_stage")
        data = self._read(path, expected_sha256)
        try:
            payload = json.loads(data, object_pairs_hook=_unique_object,
                                 parse_constant=_reject_constant)
            if not isinstance(payload, dict) or set(payload) != {
                "version", "dataset", "schema", "sequence", "previous", "imports",
                "frozen", "votes", "revisions"
            }:
                _fail("invalid_journal_schema")
            if (payload["version"] != 1 or payload["dataset"] != self._dataset
                    or payload["schema"] != self._schema
                    or type(payload["sequence"]) is not int
                    or payload["sequence"] != expected_sequence
                    or type(payload["frozen"]) is not bool):
                _fail("journal_pin_mismatch")
            _sha(payload["previous"])
            imports = payload["imports"]
            rows = payload["votes"]
            changes = payload["revisions"]
            if (not isinstance(imports, list) or len(imports) not in (1, 2)
                    or any(v not in ("A", "B") for v in imports) or len(set(imports)) != len(imports)
                    or not isinstance(rows, list) or len(rows) > MAX_ROWS
                    or not isinstance(changes, list) or len(changes) > MAX_REVISIONS):
                _fail("invalid_journal_size")
            votes = []
            seen = set()
            for row in rows:
                if not isinstance(row, dict) or set(row) != set(CSV_FIELDS):
                    _fail("invalid_vote_schema")
                window = _identifier(row["window_id"])
                annotator = row["annotator_code"]
                if window not in self._windows or annotator not in imports or (window, annotator) in seen:
                    _fail("invalid_journal_vote")
                spec = self._windows[window]
                if (row["source_sha256"] != spec.source_sha256 or row["movement"] != spec.movement
                        or type(row["revision"]) is not int or row["revision"] != 0):
                    _fail("vote_pin_mismatch")
                decision = _decision(row["count"], row["scoreable"], row["return_media_timestamps"])
                votes.append(BlindVote(window, annotator, spec.source_sha256, spec.movement,
                                       decision.return_media_timestamps, decision.count,
                                       decision.scoreable, _text(row["notes"])))
                seen.add((window, annotator))
            if seen != {(w, a) for w in self._windows for a in imports}:
                _fail("incomplete_blind_import")
            frozen = payload["frozen"]
            if (frozen and set(imports) != {"A", "B"}) or (changes and not frozen):
                _fail("invalid_journal_stage")
            # Replay on a separate inert source so malformed input cannot change this instance.
            staged = LabelSource(self._windows, schema_sha256=self._schema, policy=self._policy,
                                 journal_directory=self._directory, authorize=self._authorize)
            staged._votes = tuple(votes)
            revisions = []
            for row in changes:
                if not isinstance(row, dict) or set(row) != {"window_id", "revision", "old", "new", "reason"}:
                    _fail("invalid_revision_schema")
                window = _identifier(row["window_id"])
                if window not in self._windows:
                    _fail("unknown_window")
                number = 1 + sum(r.window_id == window for r in revisions)
                old, new = _decision_from_json(row["old"]), _decision_from_json(row["new"])
                if type(row["revision"]) is not int or row["revision"] != number or old != staged._resolved(window):
                    _fail("revision_chain_mismatch")
                revisions.append(Revision(window, number, old, new, _text(row["reason"], required=True)))
                staged._revisions = tuple(revisions)
            minimum = len(imports) + int(frozen) + len(revisions)
            if expected_sequence != minimum:
                _fail("sequence_stage_mismatch")
        except (json.JSONDecodeError, UnicodeError, RecursionError, OverflowError, TypeError, KeyError):
            raise SourceError("invalid_journal") from None
        self._votes, self._revisions = tuple(votes), tuple(revisions)
        self._imports, self._frozen = tuple(imports), frozen
        self._sequence, self._digest = expected_sequence, expected_sha256
        return self._summary()

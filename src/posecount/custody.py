"""Trusted-operator SQLite custody source; no database opens on import/construction.

Reservations consume editions, including crashes. No reset/reopen/deletion API exists.
Callbacks are explicit trusted-host permission/execution seams, not hostile-operator
isolation, human signatures, or authority derived from hashes/receipt objects.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Callable, Iterator
from uuid import uuid4

from .privacy import PrivacyPolicy

ALL_ARMS = ("Z", "A0", "A0v", "A1", "A2-H", "A2")
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
Authorizer = Callable[[str, str], bool]

class CustodyError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

def _identifier(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 128 and all(c.isascii() and (c.isalnum() or c in "_-.") for c in value)

def _digest(value: object, size: int = 64) -> bool:
    return isinstance(value, str) and len(value) == size and all(c in "0123456789abcdef" for c in value)

def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CustodyError("duplicate_artifact_key")
        result[key] = value
    return result

def _constant(_value: str) -> None:
    raise CustodyError("invalid_artifact_number")

@dataclass(frozen=True)
class EditionPins:
    code_commit: str
    model_hash: str
    runtime_hash: str
    config_hash: str
    map_hash: str
    threshold_hash: str
    video_hash: str
    gold_hash: str
    split_hash: str
    rights_hash: str
    source_hash: str

    def __post_init__(self) -> None:
        if not _digest(self.code_commit, 40) or any(not _digest(value) for key, value in asdict(self).items() if key != "code_commit"):
            raise CustodyError("invalid_edition_pins")

    @property
    def digest(self) -> str:
        return _sha(asdict(self))

@dataclass(frozen=True)
class AdmissionEvidence:
    g0_hash: str
    g1_hash: str

    def __post_init__(self) -> None:
        if not _digest(self.g0_hash) or not _digest(self.g1_hash):
            raise CustodyError("admission_evidence_missing")

@dataclass(frozen=True)
class Attempt:
    edition: str
    attempt_id: str
    pins_hash: str

    def __post_init__(self) -> None:
        if not _identifier(self.edition) or not _identifier(self.attempt_id) or not _digest(self.pins_hash):
            raise CustodyError("invalid_attempt_identity")

@dataclass(frozen=True)
class CustodySummary:
    attempt_id: str
    state: str
    pins_hash: str
    trace_hash: str | None
    predictions_hash: str | None
    report_hash: str | None
    withdrawn: bool

@dataclass(frozen=True, repr=False)
class PrivateDerivative:
    path: Path
    sha256: str
    category: str
    person_commitment: str

@dataclass(frozen=True, repr=False)
class DeletionItem:
    path: Path
    sha256: str
    category: str

@dataclass(frozen=True, repr=False)
class WithdrawalPlan:
    attempt_id: str
    request_hash: str
    inventory_hash: str
    items: tuple[DeletionItem, ...]
    report_status: str = "withdrawn_invalidated"
    deletion_performed: bool = False

_SCHEMA = """
CREATE TABLE editions(
 edition TEXT PRIMARY KEY, attempt_id TEXT UNIQUE NOT NULL,
 pins_json TEXT NOT NULL, pins_hash TEXT NOT NULL, admission_json TEXT NOT NULL,
 arms_json TEXT NOT NULL, state TEXT NOT NULL,
 reserved_utc TEXT NOT NULL, trace_hash TEXT, prediction_path TEXT,
 predictions_hash TEXT, report_hash TEXT, withdrawn INTEGER NOT NULL DEFAULT 0
 CHECK(withdrawn IN (0,1)));
CREATE TABLE events(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, edition TEXT NOT NULL,
 kind TEXT NOT NULL, utc TEXT NOT NULL, commitment TEXT,
 FOREIGN KEY(edition) REFERENCES editions(edition));
CREATE TRIGGER immutable_pins BEFORE UPDATE OF edition,attempt_id,pins_json,pins_hash,
 admission_json,arms_json,reserved_utc ON editions BEGIN
 SELECT RAISE(ABORT,'immutable_custody_identity'); END;
CREATE TRIGGER no_edition_delete BEFORE DELETE ON editions BEGIN
 SELECT RAISE(ABORT,'custody_no_delete'); END;
CREATE TRIGGER no_event_update BEFORE UPDATE ON events BEGIN
 SELECT RAISE(ABORT,'immutable_custody_event'); END;
CREATE TRIGGER no_event_delete BEFORE DELETE ON events BEGIN
 SELECT RAISE(ABORT,'custody_no_delete'); END;
"""

class CustodyStore:
    """One explicitly private database, operated by a trusted independent host.

    verify_admission must check actual G0/G1 signatures/role/rights/ordering and
    their entire pin closure AGAINST the requested EditionPins. A constructed
    AdmissionResult, declarative hash or returned Attempt is never permission.
    No default verifier/permission grant is supplied.
    """
    def __init__(self, path: Path, *, privacy: PrivacyPolicy,
                 authorize: Authorizer,
                 verify_admission: Callable[[AdmissionEvidence, EditionPins], bool],
                 study_id: str):
        if not _identifier(study_id) or not callable(authorize) or not callable(verify_admission):
            raise CustodyError("trusted_host_required")
        self._path, self._privacy = Path(path), privacy
        self._authorize, self._verify = authorize, verify_admission
        self._study = study_id

    def _permit(self, action: str, subject: str) -> None:
        try:
            allowed = self._authorize(action, subject) is True
        except Exception:
            allowed = False
        if not allowed:
            raise CustodyError("custody_permission_denied")

    def initialize(self) -> None:
        """Future create-only setup; never repair/overwrite an existing store."""
        self._permit("custody.initialize", self._study)
        try:
            path = self._privacy.validate(self._path, must_exist=False)
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(descriptor)
            con = sqlite3.connect(path, timeout=5)
            try:
                con.executescript(_SCHEMA)
                con.commit()
            finally:
                con.close()
        except (OSError, sqlite3.Error, ValueError):
            # Preserve even partial stores for owner disposition. No delete/reset.
            raise CustodyError("custody_initialization_failed") from None

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        con: sqlite3.Connection | None = None
        try:
            path = self._privacy.validate(self._path)
            con = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True,
                                  isolation_level=None, timeout=5)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except CustodyError:
            if con is not None:
                con.rollback()
            raise
        except (OSError, sqlite3.Error, ValueError):
            if con is not None:
                con.rollback()
            raise CustodyError("custody_storage_unavailable") from None
        finally:
            if con is not None:
                con.close()

    @staticmethod
    def _event(con: sqlite3.Connection, edition: str, kind: str, commitment: str | None = None) -> None:
        con.execute("INSERT INTO events(edition,kind,utc,commitment) VALUES(?,?,?,?)",
                    (edition, kind, _now(), commitment))

    @staticmethod
    def _row(con: sqlite3.Connection, attempt: Attempt) -> sqlite3.Row:
        if type(attempt) is not Attempt or not _identifier(attempt.edition) or not _identifier(attempt.attempt_id) or not _digest(attempt.pins_hash):
            raise CustodyError("invalid_attempt_identity")
        row = con.execute("SELECT * FROM editions WHERE edition=?", (attempt.edition,)).fetchone()
        if row is None or row["attempt_id"] != attempt.attempt_id or row["pins_hash"] != attempt.pins_hash:
            raise CustodyError("attempt_identity_mismatch")
        return row

    def reserve(self, edition: str, pins: EditionPins, admission: AdmissionEvidence,
                *, arms: tuple[str, ...] = ALL_ARMS) -> Attempt:
        if not _identifier(edition) or type(pins) is not EditionPins or type(admission) is not AdmissionEvidence or arms != ALL_ARMS:
            raise CustodyError("invalid_reservation")
        self._permit("custody.reserve", edition)
        try:
            admitted = self._verify(admission, pins) is True
        except Exception:
            admitted = False
        if not admitted:
            raise CustodyError("actual_admission_required")
        attempt = Attempt(edition, str(uuid4()), pins.digest)
        with self._transaction() as con:
            if con.execute("SELECT 1 FROM editions WHERE edition=?", (edition,)).fetchone():
                raise CustodyError("edition_already_consumed")
            con.execute("INSERT INTO editions(edition,attempt_id,pins_json,pins_hash,admission_json,arms_json,state,reserved_utc) VALUES(?,?,?,?,?,?,?,?)",
                (edition, attempt.attempt_id, _canonical(asdict(pins)), pins.digest,
                 _canonical(asdict(admission)), _canonical(arms), "reserved", _now()))
            self._event(con, edition, "reserved", pins.digest)
        return attempt

    def _start(self, attempt: Attempt, action: str, expected: str, started: str) -> dict[str, object]:
        self._permit(action, attempt.edition)
        with self._transaction() as con:
            row = self._row(con, attempt)
            if row["withdrawn"] or row["state"] != expected:
                raise CustodyError("edition_phase_unavailable")
            con.execute("UPDATE editions SET state=? WHERE edition=?", (started, attempt.edition))
            self._event(con, attempt.edition, started)
            return dict(row)

    def _complete(self, attempt: Attempt, expected: str, state: str,
                  *, trace_hash: str | None = None, predictions_hash: str | None = None,
                  prediction_path: Path | None = None, report_hash: str | None = None) -> None:
        with self._transaction() as con:
            row = self._row(con, attempt)
            if row["withdrawn"] or row["state"] != expected:
                raise CustodyError("edition_phase_unavailable")
            con.execute("UPDATE editions SET state=?,trace_hash=COALESCE(?,trace_hash),predictions_hash=COALESCE(?,predictions_hash),prediction_path=COALESCE(?,prediction_path),report_hash=COALESCE(?,report_hash) WHERE edition=?",
                (state, trace_hash, predictions_hash, str(prediction_path) if prediction_path else None,
                 report_hash, attempt.edition))
            self._event(con, attempt.edition, state, predictions_hash or report_hash or trace_hash)

    def _failed(self, attempt: Attempt, expected: str) -> None:
        try:
            self._complete(attempt, expected, "failed")
        except CustodyError:
            # Already-committed started state remains consumed even on DB failure.
            pass

    def extract_once(self, attempt: Attempt, extractor: Callable[[], str]) -> str:
        if not callable(extractor):
            raise CustodyError("extractor_required")
        # This commit precedes ANY callback that can read detector held-out media.
        self._start(attempt, "custody.extract", "reserved", "extracting")
        try:
            trace_hash = extractor()
            if not _digest(trace_hash):
                raise CustodyError("trace_commitment_invalid")
            self._complete(attempt, "extracting", "extracted", trace_hash=trace_hash)
            return trace_hash
        except Exception:
            self._failed(attempt, "extracting")
            raise CustodyError("extraction_failed_consumed") from None

    def _artifact(self, path: Path) -> tuple[bytes, str, Path]:
        try:
            canonical = self._privacy.validate(path)
            with canonical.open("rb") as stream:
                payload = stream.read(MAX_ARTIFACT_BYTES + 1)
            if len(payload) > MAX_ARTIFACT_BYTES:
                raise CustodyError("artifact_size_limit")
            return payload, hashlib.sha256(payload).hexdigest(), canonical
        except (OSError, ValueError):
            raise CustodyError("private_artifact_unavailable") from None

    def seal_predictions(self, attempt: Attempt, predictions: Path) -> str:
        """Create-only private seal of one all-arm envelope, before any gold join.

        Envelope: attempt_id, pins_hash, trace_hash, arms (exact all-arm object).
        Arm payloads are opaque predictions/status; semantic evaluation is separate.
        """
        row = self._start(attempt, "custody.seal", "extracted", "sealing")
        try:
            payload, digest, _ = self._artifact(predictions)
            envelope = json.loads(payload, object_pairs_hook=_pairs, parse_constant=_constant)
            if type(envelope) is not dict or set(envelope) != {"attempt_id", "pins_hash", "trace_hash", "arms"}:
                raise CustodyError("prediction_envelope_invalid")
            if envelope["attempt_id"] != attempt.attempt_id or envelope["pins_hash"] != attempt.pins_hash or envelope["trace_hash"] != row["trace_hash"]:
                raise CustodyError("prediction_identity_mismatch")
            if type(envelope["arms"]) is not dict or set(envelope["arms"]) != set(ALL_ARMS):
                raise CustodyError("all_arm_predictions_required")
            # A not_run/error arm remains an explicit payload, never an omitted arm.
            if any(value is None for value in envelope["arms"].values()):
                raise CustodyError("arm_status_required")
            target = self._path.parent / ("sealed-" + attempt.attempt_id + ".json")
            target = self._privacy.validate(target, must_exist=False)
            with target.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._complete(attempt, "sealing", "sealed", predictions_hash=digest, prediction_path=target)
            return digest
        except Exception:
            self._failed(attempt, "sealing")
            raise CustodyError("prediction_seal_failed_consumed") from None

    def _sealed(self, row: dict[str, object]) -> Path:
        path = row.get("prediction_path")
        expected = row.get("predictions_hash")
        if not isinstance(path, str) or not _digest(expected):
            raise CustodyError("prediction_seal_missing")
        _, actual, canonical = self._artifact(Path(path))
        if actual != expected:
            raise CustodyError("prediction_seal_modified")
        return canonical

    def join_gold_once(self, attempt: Attempt, scorer: Callable[[Path], str]) -> str:
        if not callable(scorer):
            raise CustodyError("scorer_required")
        row = self._start(attempt, "custody.gold_join", "sealed", "gold_joining")
        try:
            predictions = self._sealed(row)
            # Trusted scorer may join custodian gold ONLY in this post-seal call.
            report_hash = scorer(predictions)
            if not _digest(report_hash):
                raise CustodyError("report_commitment_invalid")
            self._complete(attempt, "gold_joining", "complete", report_hash=report_hash)
            return report_hash
        except Exception:
            self._failed(attempt, "gold_joining")
            raise CustodyError("gold_join_failed_consumed") from None

    def rerender(self, attempt: Attempt, expected_report_hash: str,
                 renderer: Callable[[Path], str]) -> str:
        self._permit("custody.rerender", attempt.edition)
        if not _digest(expected_report_hash) or not callable(renderer):
            raise CustodyError("invalid_rerender")
        with self._transaction() as con:
            row = dict(self._row(con, attempt))
            if row["withdrawn"] or row["state"] != "complete" or row["report_hash"] != expected_report_hash:
                raise CustodyError("report_identity_mismatch")
        try:
            path = self._sealed(row)
            if renderer(path) != expected_report_hash:
                raise CustodyError("rerender_identity_mismatch")
            # Recheck withdrawal and seal after callback; no new attempt/inference.
            self._sealed(row)
            with self._transaction() as con:
                current = self._row(con, attempt)
                if current["withdrawn"] or current["state"] != "complete":
                    raise CustodyError("edition_phase_unavailable")
                self._event(con, attempt.edition, "rerendered", expected_report_hash)
            return expected_report_hash
        except Exception:
            raise CustodyError("rerender_failed") from None

    def plan_withdrawal(self, attempt: Attempt, *, request_hash: str,
                        inventory_hash: str, person_commitment: str,
                        inventory: tuple[PrivateDerivative, ...],
                        verify_inventory: Callable[[str, str, tuple[PrivateDerivative, ...]], bool]) -> WithdrawalPlan:
        self._permit("custody.withdraw", attempt.edition)
        if not _digest(request_hash) or not _digest(person_commitment):
            raise CustodyError("withdrawal_request_invalid")
        # Stop future access immediately on an authorized withdrawal, even when
        # the deletion inventory is incomplete. Failed planning cannot revive it.
        with self._transaction() as con:
            row = self._row(con, attempt)
            if not row["withdrawn"]:
                con.execute("UPDATE editions SET state=?,withdrawn=1 WHERE edition=?", ("withdrawn", attempt.edition))
                self._event(con, attempt.edition, "withdrawal_requested", _sha((request_hash, person_commitment)))
        if not all(_digest(x) for x in (request_hash, inventory_hash, person_commitment)) or type(inventory) is not tuple or not inventory or len(inventory) > 4096 or not callable(verify_inventory):
            raise CustodyError("withdrawal_inventory_invalid")
        items = []
        for item in inventory:
            if type(item) is not PrivateDerivative or not _digest(item.sha256) or item.person_commitment != person_commitment or item.category not in ("video", "trace", "label", "consent", "mapping", "prediction", "report", "journal", "cache", "other_derivative"):
                raise CustodyError("withdrawal_inventory_invalid")
            items.append(DeletionItem(self._privacy.validate(item.path), item.sha256, item.category))
        if len({str(item.path) for item in items}) != len(items):
            raise CustodyError("withdrawal_inventory_invalid")
        commitment = _sha([(str(i.path), i.sha256, i.category) for i in items])
        if commitment != inventory_hash:
            raise CustodyError("withdrawal_inventory_hash_mismatch")
        try:
            verified = verify_inventory(request_hash, inventory_hash, inventory) is True
        except Exception:
            verified = False
        if not verified:
            raise CustodyError("owner_inventory_verification_required")
        with self._transaction() as con:
            row = self._row(con, attempt)
            if not row["withdrawn"]:
                raise CustodyError("withdrawal_state_invalid")
            self._event(con, attempt.edition, "withdrawn_deletion_pending", _sha((request_hash, inventory_hash)))
        # Intentionally NO unlink/remove/DELETE. Actual owner must authorize and
        # carry out deletion across the complete private derivative inventory.
        return WithdrawalPlan(attempt.attempt_id, request_hash, inventory_hash, tuple(items))

    def summary(self, attempt: Attempt) -> CustodySummary:
        self._permit("custody.summary", attempt.edition)
        with self._transaction() as con:
            row = self._row(con, attempt)
            return CustodySummary(row["attempt_id"], row["state"], row["pins_hash"], row["trace_hash"], row["predictions_hash"], row["report_hash"], bool(row["withdrawn"]))

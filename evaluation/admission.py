"""Unsigned preparation versus independently authorized actual G0/G1 admission.

These are private in-memory structures, not study evidence authored by builders.
No files are read and no signature is manufactured. Trusted-host callbacks must
verify original human evidence, authority, independence, pre-output chronology,
exact rights and the entire referenced pin closure in their own private store.
A digest establishes byte identity only. Returning True for arbitrary digests
defeats this trust boundary; neither Python objects nor SQLite isolate a hostile
operator. AdmissionResult is an aggregate report, NEVER a bearer credential.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Callable

from .split import AdultMetadata, SplitCommitment, canonical_digest, is_digest, validate_split

VerifyReceipt = Callable[[str, str], bool]
Authorize = Callable[[str, str], bool]
VIEWS = ("front", "45", "side")
CONDITIONS = ("ordinary", "obstructed")
NEGATIVES = ("stand_talk", "walk_twice", "sit_stand", "pickup", "wave", "exit_reenter")
G0_PIN_NAMES = frozenset({
    "roles", "consent", "machines", "private_root", "offline", "rubric",
    "roster", "split", "source", "gold", "rights", "runtime", "ordering",
    "retention_withdrawal", "budgets", "independent_manual_cases",
})


@dataclass(frozen=True, repr=False)
class RoleEvidence:
    custodian_digest: str
    annotator_a_digest: str
    annotator_b_digest: str
    builder_digests: tuple[str, ...] = field(repr=False)
    final_verifier_digest: str


@dataclass(frozen=True, repr=False)
class WindowSupport:
    window_digest: str
    person_digest: str
    kind: str
    view: str
    condition: str
    duration_seconds: float
    jointly_scoreable: bool


@dataclass(frozen=True, repr=False)
class G0Receipt:
    roster: tuple[AdultMetadata, ...] = field(repr=False)
    split: SplitCommitment = field(repr=False)
    roles: RoleEvidence = field(repr=False)
    physical_machine_digests: tuple[str, str] = field(repr=False)
    windows: tuple[WindowSupport, ...] = field(repr=False)
    pins: tuple[tuple[str, str], ...] = field(repr=False)


@dataclass(frozen=True, repr=False)
class BlindAgreement:
    """Original blind dev votes' comparison; no counts or labels exposed here."""

    window_digest: str
    jointly_scoreable: bool
    exact_count_agreement: bool | None


@dataclass(frozen=True, repr=False)
class G1Receipt:
    g0_digest: str
    source_digest: str
    split_digest: str
    rights_digest: str
    gold_digest: str
    import_digest: str
    original_blind_votes_digest: str
    adjudication_digest: str
    heldout_custodian_agreement_digest: str
    dev_agreement: tuple[BlindAgreement, ...] = field(repr=False)


@dataclass(frozen=True)
class AdmissionResult:
    accepted: bool
    stage: str
    pins: tuple[tuple[str, str], ...] = ()
    counts: tuple[tuple[str, int], ...] = ()
    reasons: tuple[str, ...] = ()


def receipt_digest(receipt: G0Receipt | G1Receipt) -> str:
    """Commit the whole typed payload; no raw input is logged or returned."""
    if type(receipt) not in (G0Receipt, G1Receipt):
        raise ValueError("invalid_receipt_type")
    try:
        return canonical_digest({"stage": "G0" if type(receipt) is G0Receipt else "G1",
                                 "schema": "m17-admission-v1", "receipt": asdict(receipt)})
    except (TypeError, ValueError, AttributeError, RecursionError):
        raise ValueError("invalid_receipt_structure") from None


def _g0_checks(receipt: G0Receipt) -> tuple[list[str], dict[str, int]]:
    reasons: list[str] = []
    counts: dict[str, int] = {}
    if type(receipt) is not G0Receipt:
        return ["invalid_g0_type"], counts
    if not validate_split(receipt.roster, receipt.split):
        return ["invalid_frozen_split"], counts
    pins = receipt.pins
    if (not isinstance(pins, tuple) or len(pins) != len(G0_PIN_NAMES) or
            any(not isinstance(pin, tuple) or len(pin) != 2 or
                not isinstance(pin[0], str) or not is_digest(pin[1]) for pin in pins)):
        return ["invalid_pin_closure"], counts
    mapping = dict(pins)
    if set(mapping) != G0_PIN_NAMES:
        return ["incomplete_pin_closure"], counts
    if mapping["roster"] != receipt.split.roster_digest or mapping["split"] != receipt.split.digest:
        reasons.append("split_commitment_mismatch")
    roles = receipt.roles
    if (type(roles) is not RoleEvidence or not isinstance(roles.builder_digests, tuple) or
            not roles.builder_digests or len(roles.builder_digests) > 32 or
            any(not is_digest(value) for value in (
                roles.custodian_digest, roles.annotator_a_digest, roles.annotator_b_digest,
                roles.final_verifier_digest, *roles.builder_digests))):
        reasons.append("invalid_role_evidence")
    elif (roles.annotator_a_digest == roles.annotator_b_digest or
          any(value in roles.builder_digests for value in (
              roles.custodian_digest, roles.annotator_a_digest, roles.annotator_b_digest,
              roles.final_verifier_digest)) or
          roles.final_verifier_digest not in (roles.annotator_a_digest, roles.annotator_b_digest)):
        reasons.append("nonbuilder_independence_required")
    machines = receipt.physical_machine_digests
    if (not isinstance(machines, tuple) or len(machines) != 2 or
            any(not is_digest(value) for value in machines) or machines[0] == machines[1]):
        reasons.append("two_physical_machines_required")
    windows = receipt.windows
    if (not isinstance(windows, tuple) or len(windows) != 192 or
            any(type(row) is not WindowSupport for row in windows)):
        return reasons + ["requires_192_windows"], counts
    if any(not is_digest(row.window_digest) or not is_digest(row.person_digest) or
           row.view not in VIEWS or type(row.jointly_scoreable) is not bool or
           type(row.duration_seconds) not in (int, float) or
           not math.isfinite(row.duration_seconds) or row.duration_seconds < 32 or
           not ((row.kind == "positive" and row.condition in CONDITIONS) or
                (row.kind in NEGATIVES and row.condition == "ordinary")) for row in windows):
        return reasons + ["invalid_window_support"], counts
    if len({row.window_digest for row in windows}) != 192:
        reasons.append("duplicate_window")
    assignments = {row.person_digest: row.split for row in receipt.split.assignments}
    if {row.person_digest for row in windows} != set(assignments):
        reasons.append("person_support_mismatch")
    for person in assignments:
        rows = [row for row in windows if row.person_digest == person]
        positives = [(row.view, row.condition) for row in rows if row.kind == "positive"]
        negatives = [row.kind for row in rows if row.kind != "positive"]
        if (len(rows) != 12 or len(positives) != 6 or
                set(positives) != {(view, condition) for view in VIEWS for condition in CONDITIONS} or
                len(negatives) != 6 or set(negatives) != set(NEGATIVES)):
            reasons.append("per_person_view_activity_support_required")
            break
    for split in ("dev", "heldout"):
        rows = [row for row in windows if assignments.get(row.person_digest) == split]
        scoreable = sum(row.jointly_scoreable for row in rows)
        counts.update({split + "_scheduled": len(rows), split + "_jointly_scoreable": scoreable,
                       split + "_positive": sum(row.kind == "positive" for row in rows),
                       split + "_negative": sum(row.kind != "positive" for row in rows)})
        if len(rows) != 96 or scoreable * 10 < len(rows) * 9:
            reasons.append("per_split_scoreability_quota_failed")
        for view in VIEWS:
            support = [row for row in rows if row.kind == "positive" and row.view == view]
            counts[split + "_positive_" + view + "_scheduled"] = len(support)
            counts[split + "_positive_" + view + "_jointly_scoreable"] = sum(
                row.jointly_scoreable for row in support)
    counts["people"] = 16
    counts["windows"] = 192
    return sorted(set(reasons)), counts


def _result(stage: str, receipt: G0Receipt | G1Receipt, reasons: list[str],
            counts: dict[str, int], *, accepted: bool = False) -> AdmissionResult:
    pins: tuple[tuple[str, str], ...] = ()
    if not reasons or reasons == ["unsigned_not_admitted"]:
        try:
            pins = (("receipt", receipt_digest(receipt)),)
        except ValueError:
            reasons = reasons + ["invalid_receipt_structure"]
    return AdmissionResult(accepted and not reasons, stage, pins,
                           tuple(sorted(counts.items())), tuple(sorted(set(reasons))))


def validate_g0(receipt: G0Receipt) -> AdmissionResult:
    """Unsigned structural preparation; can never admit human/private activity."""
    reasons, counts = _safe_g0_checks(receipt)
    return _result("G0", receipt, reasons + ["unsigned_not_admitted"], counts)


def _host_check(stage: str, digest: str, verify_receipt: VerifyReceipt,
                authorize: Authorize) -> list[str]:
    if not callable(verify_receipt) or not callable(authorize):
        return ["trusted_host_callbacks_required"]
    try:
        if authorize("admission." + stage.lower(), digest) is not True:
            return ["permission_denied"]
        if verify_receipt(stage, digest) is not True:
            return ["receipt_not_independently_verified"]
    except Exception:
        return ["trusted_host_verification_failed"]
    return []


def admit_g0(receipt: G0Receipt, *, verify_receipt: VerifyReceipt,
             authorize: Authorize) -> AdmissionResult:
    reasons, counts = _safe_g0_checks(receipt)
    if not reasons:
        try:
            reasons.extend(_host_check("G0", receipt_digest(receipt), verify_receipt, authorize))
        except ValueError:
            reasons.append("invalid_receipt_structure")
    return _result("G0", receipt, reasons, counts, accepted=True)


def _g1_checks(receipt: G1Receipt, g0: G0Receipt) -> tuple[list[str], dict[str, int]]:
    reasons, counts = _safe_g0_checks(g0)
    if reasons:
        return ["g0_structurally_invalid"], counts
    if type(receipt) is not G1Receipt:
        return ["invalid_g1_type"], counts
    digest_fields = (receipt.g0_digest, receipt.source_digest, receipt.split_digest,
                     receipt.rights_digest, receipt.gold_digest, receipt.import_digest,
                     receipt.original_blind_votes_digest, receipt.adjudication_digest,
                     receipt.heldout_custodian_agreement_digest)
    if any(not is_digest(value) for value in digest_fields):
        return ["invalid_g1_commitment"], counts
    pins = dict(g0.pins)
    if (receipt.g0_digest != receipt_digest(g0) or receipt.source_digest != pins["source"] or
            receipt.split_digest != pins["split"] or receipt.rights_digest != pins["rights"] or
            receipt.gold_digest != pins["gold"]):
        reasons.append("g0_pin_reconciliation_failed")
    dev_people = {row.person_digest for row in g0.split.assignments if row.split == "dev"}
    expected = {row.window_digest: row.jointly_scoreable for row in g0.windows
                if row.person_digest in dev_people}
    rows = receipt.dev_agreement
    if (not isinstance(rows, tuple) or len(rows) != 96 or
            any(type(row) is not BlindAgreement for row in rows)):
        return reasons + ["complete_original_blind_dev_support_required"], counts
    if (len({row.window_digest for row in rows}) != 96 or
            {row.window_digest for row in rows} != set(expected)):
        return reasons + ["dev_window_reconciliation_failed"], counts
    if any(type(row.jointly_scoreable) is not bool or
           row.jointly_scoreable != expected[row.window_digest] or
           (row.jointly_scoreable and type(row.exact_count_agreement) is not bool) or
           (not row.jointly_scoreable and row.exact_count_agreement is not None) for row in rows):
        return reasons + ["original_blind_status_reconciliation_failed"], counts
    denominator = sum(row.jointly_scoreable for row in rows)
    numerator = sum(row.exact_count_agreement is True for row in rows)
    counts.update(dev_blind_agreement_numerator=numerator,
                  dev_blind_agreement_denominator=denominator)
    if denominator == 0 or numerator * 5 < denominator * 4:
        reasons.append("dev_original_blind_agreement_below_080")
    return reasons, counts


def validate_g1(receipt: G1Receipt, g0: G0Receipt) -> AdmissionResult:
    reasons, counts = _safe_g1_checks(receipt, g0)
    return _result("G1", receipt, reasons + ["unsigned_not_admitted"], counts)


def admit_g1(receipt: G1Receipt, g0: G0Receipt, *, verify_receipt: VerifyReceipt,
             authorize: Authorize) -> AdmissionResult:
    """Require fresh host G0 and G1 verification; never accept a result as proof.

    G1 host verification must reconcile import/source/gold/rights bytes, preserved
    original blind votes and joint revisions, frozen quota convention and private
    held-out agreement, and certify that held-out information did not tune dev.
    """
    reasons, counts = _safe_g1_checks(receipt, g0)
    if not reasons:
        reasons.extend(_host_check("G0", receipt_digest(g0), verify_receipt, authorize))
    if not reasons:
        reasons.extend(_host_check("G1", receipt_digest(receipt), verify_receipt, authorize))
    return _result("G1", receipt, reasons, counts, accepted=True)


def _safe_g0_checks(receipt: G0Receipt) -> tuple[list[str], dict[str, int]]:
    try:
        return _g0_checks(receipt)
    except (TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        return ["invalid_g0_structure"], {}


def _safe_g1_checks(receipt: G1Receipt, g0: G0Receipt) -> tuple[list[str], dict[str, int]]:
    try:
        return _g1_checks(receipt, g0)
    except (TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        return ["invalid_g1_structure"], {}

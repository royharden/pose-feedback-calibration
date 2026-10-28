"""Frozen person-disjoint assignment from existing private adult metadata only.

The sixteen-person roster requires eight phone and eight webcam captures;
dev and heldout each receive four people from each capture class.
No enrollment, replacements, persistence, private-file access or authority is
provided here. Hashes identify bytes; they are not consent or adulthood proof.
Private row representations are suppressed. Keep the commitment in custody;
builders receive only its digest and aggregate counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re

SEED = 17012026
CAPTURE_CLASSES = ("phone", "webcam")


def is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def canonical_digest(value: object) -> str:
    """Canonical JSON SHA256; callers supply only the documented primitive schema."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, repr=False)
class AdultMetadata:
    person_digest: str
    capture_class: str
    adulthood_evidence_digest: str


@dataclass(frozen=True, repr=False)
class Assignment:
    person_digest: str
    capture_class: str
    split: str


@dataclass(frozen=True, repr=False)
class SplitCommitment:
    roster_digest: str
    assignments: tuple[Assignment, ...] = field(repr=False)
    digest: str
    seed: int = SEED


def freeze_split(roster: tuple[AdultMetadata, ...]) -> SplitCommitment:
    """Freeze a deterministic stratified 8/8 split before detector outputs.

    The roster must contain exactly eight phone and eight webcam captures,
    giving each split four people from each capture class. The caller supplies
    sixteen existing adults, never generated participant rows.
    A host must independently verify evidence and pre-output ordering at G0.
    There is deliberately no migration/replacement or alternate-seed parameter.
    """
    if not isinstance(roster, tuple) or len(roster) != 16:
        raise ValueError("roster_requires_sixteen")
    if any(not isinstance(row, AdultMetadata) for row in roster):
        raise ValueError("invalid_roster_row")
    if any(not is_digest(row.person_digest) or
           not is_digest(row.adulthood_evidence_digest) or
           row.capture_class not in CAPTURE_CLASSES for row in roster):
        raise ValueError("invalid_roster_metadata")
    if len({row.person_digest for row in roster}) != 16:
        raise ValueError("duplicate_person")
    ordered = sorted(roster, key=lambda row: row.person_digest)
    roster_digest = canonical_digest([
        [row.person_digest, row.capture_class, row.adulthood_evidence_digest]
        for row in ordered
    ])
    assigned: list[Assignment] = []
    for capture_class in CAPTURE_CLASSES:
        group = [row for row in ordered if row.capture_class == capture_class]
        if len(group) != 8:
            raise ValueError("capture_class_balance_required")
        group.sort(key=lambda row: canonical_digest(
            ["m17-split-v1", SEED, roster_digest, row.person_digest]))
        assigned.extend(Assignment(row.person_digest, capture_class,
                                   "dev" if index < len(group) // 2 else "heldout")
                        for index, row in enumerate(group))
    assignments = tuple(sorted(assigned, key=lambda row: row.person_digest))
    digest = canonical_digest({"schema": "m17-split-v1", "seed": SEED,
                               "roster": roster_digest, "assignments": [
                                   [row.person_digest, row.capture_class, row.split]
                                   for row in assignments]})
    return SplitCommitment(roster_digest, assignments, digest)


def validate_split(roster: tuple[AdultMetadata, ...], split: SplitCommitment) -> bool:
    """Compare all rows and hashes to the sole fixed-seed assignment."""
    try:
        return type(split) is SplitCommitment and split == freeze_split(roster)
    except (ValueError, TypeError, AttributeError):
        return False

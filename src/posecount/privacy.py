"""Fail-closed local path boundaries for both source and destination paths.

No filesystem scan or automatic home/sync discovery is performed. The operator must
supply every sync, PJ-OD, OneDrive, Git metadata and external Git worktree root,
then explicitly attest completeness with ``boundaries_verified=True``. In
particular, an external --git-dir worktree with no .git marker is not discoverable
from its contents. Git discovery supplements, never replaces, this attestation.

Validation is a point-in-time check, not an atomic open. A privileged/local actor
can replace a directory or junction after validation (TOCTOU). Callers must use
returned canonical paths, validate immediately before EACH read/write, and keep
the private tree inaccessible to untrusted writers. This API does not create it,
change permissions, open media, or claim to eliminate that residual race.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import subprocess


class PrivacyError(ValueError):
    """A sanitized boundary failure; no path or subprocess output is exposed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _lexical(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise PrivacyError("absolute_path_required")
    for component in path.parts[1:]:
        folded = component.casefold()
        if component in (".", "..") or ":" in component or "\x00" in component:
            raise PrivacyError("unsafe_path_syntax")
        if folded in {".git", "pj-od"} or folded.startswith("onedrive"):
            raise PrivacyError("forbidden_path_component")
        if os.name == "nt":
            stem = folded.split(".", 1)[0]
            if component.endswith((" ", ".")) or stem in {
                "con", "prn", "aux", "nul", "conin$", "conout$",
                *(f"com{i}" for i in range(1, 10)),
                *(f"lpt{i}" for i in range(1, 10)),
            }:
                raise PrivacyError("unsafe_path_syntax")
    # Extended/device namespaces can change Windows path interpretation.
    if os.name == "nt" and str(path).startswith(("\\\\?\\", "\\\\.\\")):
        raise PrivacyError("unsafe_path_syntax")
    return path


def _resolve_existing(path: Path, reason: str) -> Path:
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise PrivacyError(reason) from None


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _nearest_existing(path: Path) -> tuple[Path, tuple[str, ...]]:
    """Preserve missing leaf names without hiding dangling links or access errors."""
    current = path
    missing: list[str] = []
    for _ in range(128):
        try:
            current.lstat()
        except FileNotFoundError:
            missing.append(current.name)
            if current == current.parent:
                break
            current = current.parent
            continue
        except OSError:
            raise PrivacyError("path_unverifiable") from None
        return _resolve_existing(current, "path_unverifiable"), tuple(reversed(missing))
    raise PrivacyError("path_unverifiable")


def _reject_git(directory: Path) -> None:
    """Inspect only target ancestors; non-repository is the sole accepted error.

    A minimal environment prevents inherited GIT_DIR/GIT_WORK_TREE/ceiling settings
    from redirecting discovery. No shell, network command, credentials, global
    configuration, or repository hook is invoked. Missing Git fails closed.
    """
    environment = {
        "LC_ALL": "C", "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
    }
    current = directory
    for _ in range(128):
        try:
            (current / ".git").lstat()
        except FileNotFoundError:
            pass
        except OSError:
            raise PrivacyError("git_boundary_unverifiable") from None
        else:
            raise PrivacyError("git_boundary_forbidden")
        try:
            result = subprocess.run(
                ["git", "--no-optional-locks", "-C", str(current), "rev-parse",
                 "--is-inside-work-tree", "--is-bare-repository", "--absolute-git-dir"],
                cwd=current, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=2, check=False,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            raise PrivacyError("git_boundary_unverifiable") from None
        if result.returncode == 0:
            raise PrivacyError("git_boundary_forbidden")
        # Permission errors, dubious ownership, corrupt metadata, Git installation
        # failures and unfamiliar diagnostics must never become "not a repo".
        if result.returncode != 128 or result.stderr.strip() != (
            b"fatal: not a git repository (or any of the parent directories): .git"
        ) or result.stdout.strip():
            raise PrivacyError("git_boundary_unverifiable")
        if current == current.parent:
            return
        current = current.parent
    raise PrivacyError("git_boundary_unverifiable")


@dataclass(frozen=True)
class PrivacyPolicy:
    """Explicit, verified private storage policy; default construction denies all.

    ``forbidden_roots`` must be a nonempty tuple of existing absolute roots,
    including configured sync and external Git worktrees/metadata. Verification
    is an operator assertion from a trusted configuration, not user media input.
    A private directory must already exist outside all forbidden boundaries.
    """

    private_root: Path
    forbidden_roots: tuple[Path, ...]
    boundaries_verified: bool = False

    def validate(self, path: Path, *, must_exist: bool = True) -> Path:
        """Return a canonical allowed input/output path or a named failure.

        For a new output, the nearest existing ancestor must be a directory;
        unresolved trailing components are appended only after strict resolution.
        Existing symlinks/junctions (including dangling links) never fall through
        to the new-output case. No directory is created by validation.
        """
        if self.boundaries_verified is not True:
            raise PrivacyError("boundaries_unverified")
        if not isinstance(self.forbidden_roots, tuple) or not self.forbidden_roots:
            raise PrivacyError("forbidden_roots_unverified")
        if not isinstance(must_exist, bool):
            raise PrivacyError("invalid_existence_requirement")
        private_lexical = _lexical(self.private_root)
        private = _resolve_existing(private_lexical, "private_root_unverifiable")
        _lexical(private)
        try:
            if not private.is_dir():
                raise PrivacyError("private_root_not_directory")
        except OSError:
            raise PrivacyError("private_root_unverifiable") from None
        roots: list[tuple[Path, Path]] = []
        for root in self.forbidden_roots:
            # Forbidden roots themselves may contain deliberately rejected names.
            if not isinstance(root, Path) or not root.is_absolute():
                raise PrivacyError("forbidden_roots_unverified")
            resolved = _resolve_existing(root, "forbidden_roots_unverified")
            roots.append((root, resolved))
            if _within(private_lexical, root) or _within(private, resolved):
                raise PrivacyError("private_root_forbidden")
        lexical = _lexical(path)
        if not _within(lexical, private_lexical):
            raise PrivacyError("outside_private_root")
        if any(_within(lexical, root) for root, _ in roots):
            raise PrivacyError("forbidden_boundary")
        if must_exist:
            canonical = _resolve_existing(lexical, "path_unverifiable")
            existing = canonical
        else:
            existing, missing = _nearest_existing(lexical)
            canonical = existing.joinpath(*missing)
            try:
                if missing and not existing.is_dir():
                    raise PrivacyError("output_parent_not_directory")
            except OSError:
                raise PrivacyError("path_unverifiable") from None
        _lexical(canonical)
        if not _within(canonical, private):
            raise PrivacyError("outside_private_root")
        if any(_within(canonical, root) for _, root in roots):
            raise PrivacyError("forbidden_boundary")
        try:
            directory = existing if existing.is_dir() else existing.parent
        except OSError:
            raise PrivacyError("path_unverifiable") from None
        _reject_git(directory)
        return canonical

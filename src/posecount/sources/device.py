"""Lazy, opt-in local VIDEO inference. Importing this module never opens a device.

No model or dependency acquisition is implemented. Evidence pins are operator-supplied;
the checked-in manifest intentionally cannot authorize processing. Runtime tree hashes
cover sorted relative POSIX filenames, a NUL, and each file's SHA256 hex plus newline.
Trees are bounded to 4096 files / 512 MiB, with symlinks and junctions rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
from typing import Any
from uuid import uuid4

from ..landmarks import FrameBatch, LANDMARK_NAMES, Landmark, SourceError, StreamValidator
from ..privacy import PrivacyPolicy
from ..windows import missing_between, nominal_slot


@dataclass(frozen=True)
class DeviceAuthorization:
    """Explicit future operator confirmations; none are inferred from a path/pin."""

    processing_authorized: bool = False
    operator_rights_confirmed: bool = False
    offline_confirmed: bool = False
    private_data_confirmed: bool = False


def _fail(reason: str) -> SourceError:
    return SourceError(reason)


def _digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise _fail("evidence_digest_missing")
    if any(c not in "0123456789abcdef" for c in value):
        raise _fail("evidence_digest_invalid")
    return value


def _is_link(path: Path) -> bool:
    # Windows junctions are reparse points, including on Python without is_junction.
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & 0x400)


def _safe_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise _fail("evidence_path_missing")
    path = Path(value)
    if not path.is_absolute():
        raise _fail("evidence_path_not_absolute")
    try:
        if any(_is_link(item) for item in (path, *path.parents)):
            raise _fail("evidence_link_rejected")
        return path.resolve(strict=True)
    except OSError as exc:
        raise _fail("evidence_path_unavailable") from exc


def _file_hash(path: Path, limit: int) -> str:
    if not path.is_file() or path.stat().st_size > limit:
        raise _fail("evidence_file_limit")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise _fail("evidence_file_limit")
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hash(root: Path) -> str:
    if not root.is_dir():
        raise _fail("runtime_tree_missing")
    # Do not recursively traverse unbounded trees, follow links, or inspect home.
    pending = [root]
    files: list[Path] = []
    entries = 0
    size = 0
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            entries += 1
            if entries > 4096 or _is_link(path):
                raise _fail("runtime_tree_boundary")
            if path.is_dir():
                pending.append(path)
            elif path.is_file():
                size += path.stat().st_size
                if size > 512 * 1024 * 1024:
                    raise _fail("runtime_tree_limit")
                files.append(path)
            else:
                raise _fail("runtime_tree_boundary")
    if not files:
        raise _fail("runtime_tree_empty")
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_hash(path, 512 * 1024 * 1024).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


class VideoSource:
    """Explicit open/read/close source; read returns None only at video EOF.

    ``manifest`` is a local JSON evidence file, not an acquisition instruction.
    Runtime package roots must be narrowly scoped installed package directories.
    Offline confirmation is an operator assertion, not a network sandbox guarantee.
    Use only in a separately authorized, offline process with immutable evidence.
    ``pixel_aspect`` is required trusted operator geometry evidence, not inferred.
    Video frame count/FPS are trusted container metadata defining the expected
    endpoint; matching them does not establish forensic media completeness.
    """

    def __init__(
        self,
        path: Path,
        *,
        manifest: Path,
        privacy: PrivacyPolicy,
        authorization: DeviceAuthorization,
        pixel_aspect: float,
    ) -> None:
        if (type(pixel_aspect) not in (int, float) or
                not 0 < pixel_aspect <= 100 or not math.isfinite(pixel_aspect)):
            raise _fail("invalid_pixel_aspect")
        self.path = path
        self.manifest = manifest
        self.privacy = privacy
        self.authorization = authorization
        self.pixel_aspect = float(pixel_aspect)
        self._camera: int | None = None
        self._capture: Any = None
        self._landmarker: Any = None
        self._cv2: Any = None
        self._mp: Any = None
        self._validator: Any = None
        self._last_ms = -1
        self._start_ns = 0
        self._fps = 30.0
        self._model_id: str | None = None
        self._runtime_id: str | None = None
        self._open_attempted = False
        self._previous_media: float | None = None
        self._clock_scope: str | None = None
        self._expected_frames: int | None = None
        self._expected_endpoint: float | None = None
        self._decoded_frames = 0

    def _evidence(self) -> tuple[Path, dict[str, Any], dict[str, float]]:
        auth = self.authorization
        if not all(value is True for value in (
            auth.processing_authorized, auth.operator_rights_confirmed,
            auth.offline_confirmed, auth.private_data_confirmed,
        )):
            raise _fail("operator_authorization_required")
        if not self.privacy.boundaries_verified:
            raise _fail("private_boundary_unverified")
        try:
            if self.manifest.stat().st_size > 64 * 1024:
                raise _fail("manifest_size_limit")
            with self.manifest.open("r", encoding="utf-8") as stream:
                evidence = json.load(stream)
        except (OSError, ValueError) as exc:
            if isinstance(exc, SourceError):
                raise
            raise _fail("manifest_evidence_unavailable") from exc
        if not isinstance(evidence, dict) or evidence.get("state") != "approved":
            raise _fail("model_evidence_unavailable")
        if evidence.get("rights_approved") is not True:
            raise _fail("model_rights_unavailable")
        settings = evidence.get("inference_options")
        if not isinstance(settings, dict) or settings.get("delegate") != "CPU":
            raise _fail("inference_options_missing")
        thresholds: dict[str, float] = {}
        for name in (
            "min_pose_detection_confidence", "min_pose_presence_confidence",
            "min_tracking_confidence",
        ):
            value = settings.get(name)
            if (type(value) not in (int, float) or not 0 <= value <= 1 or
                    not math.isfinite(value)):
                raise _fail("inference_option_invalid")
            thresholds[name] = float(value)
        model = evidence.get("model")
        runtimes = evidence.get("runtimes")
        if not isinstance(model, dict) or not isinstance(runtimes, dict):
            raise _fail("model_runtime_evidence_missing")
        model_path = self.privacy.validate(_safe_path(model.get("path")))
        model_hash = _digest(model.get("sha256"))
        if _file_hash(model_path, 128 * 1024 * 1024) != model_hash:
            raise _fail("model_digest_mismatch")
        for name in ("mediapipe", "cv2"):
            pin = runtimes.get(name)
            if not isinstance(pin, dict):
                raise _fail("runtime_evidence_missing")
            root = _safe_path(pin.get("package_root"))
            # A package root cannot be a drive, home, site-packages, or project tree.
            if root.name != name or root.parent == root:
                raise _fail("runtime_package_boundary")
            if not isinstance(pin.get("version"), str) or not pin["version"]:
                raise _fail("runtime_version_missing")
            if _tree_hash(root) != _digest(pin.get("tree_sha256")):
                raise _fail("runtime_digest_mismatch")
            if name in sys.modules:
                raise _fail("runtime_already_loaded")
            spec = importlib.util.find_spec(name)
            if spec is None or spec.origin is None:
                raise _fail("runtime_unavailable")
            if not Path(spec.origin).resolve(strict=True).is_relative_to(root):
                raise _fail("runtime_origin_mismatch")
        self._model_id = model_hash
        self._runtime_id = ":".join(runtimes[n]["tree_sha256"] for n in ("mediapipe", "cv2"))
        return model_path, runtimes, thresholds

    def open(self) -> VideoSource:
        if self._open_attempted:
            raise _fail("source_open_already_attempted")
        self._open_attempted = True
        try:
            model, pins, thresholds = self._evidence()
            target: str | int
            if self._camera is None:
                target = str(self.privacy.validate(self.path))
            else:
                target = self._camera
            # These are the only optional-runtime imports, after authorization/pins.
            self._cv2 = importlib.import_module("cv2")
            self._mp = importlib.import_module("mediapipe")
            for name, module in (("cv2", self._cv2), ("mediapipe", self._mp)):
                if getattr(module, "__version__", None) != pins[name]["version"]:
                    raise _fail("runtime_version_mismatch")
                if not Path(module.__file__).resolve(strict=True).is_relative_to(
                    _safe_path(pins[name]["package_root"])
                ):
                    raise _fail("runtime_origin_mismatch")
            options = self._mp.tasks.vision.PoseLandmarkerOptions(
                base_options=self._mp.tasks.BaseOptions(
                    model_asset_path=str(model),
                    delegate=self._mp.tasks.BaseOptions.Delegate.CPU,
                ),
                running_mode=self._mp.tasks.vision.RunningMode.VIDEO,
                num_poses=2,
                min_pose_detection_confidence=thresholds["min_pose_detection_confidence"],
                min_pose_presence_confidence=thresholds["min_pose_presence_confidence"],
                min_tracking_confidence=thresholds["min_tracking_confidence"],
            )
            self._landmarker = self._mp.tasks.vision.PoseLandmarker.create_from_options(options)
            self._capture = self._cv2.VideoCapture(target)
            if not self._capture.isOpened():
                raise _fail("camera_unavailable" if self._camera is not None else "video_unavailable")
            self._fps = float(self._capture.get(self._cv2.CAP_PROP_FPS))
            if not math.isfinite(self._fps) or not 0 < self._fps <= 120:
                raise _fail("source_fps_invalid")
            if self._camera is None:
                frame_count = float(self._capture.get(self._cv2.CAP_PROP_FRAME_COUNT))
                if (not math.isfinite(frame_count) or not frame_count.is_integer() or
                        not 1 <= frame_count <= 7201):
                    raise _fail("video_frame_count_invalid")
                self._expected_frames = int(frame_count)
                self._expected_endpoint = (self._expected_frames - 1) / self._fps
                if not 0 <= self._expected_endpoint <= 60:
                    raise _fail("video_duration_invalid")
            self._decoded_frames = 0
            self._validator = StreamValidator()
            self._last_ms = -1
            self._previous_media = None
            self._clock_scope = str(uuid4())
            self._start_ns = time.monotonic_ns()
            return self
        except SourceError:
            self._close_on_error()
            raise
        except Exception as exc:
            self._close_on_error()
            raise _fail("device_open_unavailable") from exc

    def read(self) -> FrameBatch | None:
        if self._capture is None:
            raise _fail("source_not_open")
        try:
            # Camera media time is host sampling elapsed time, not an asserted
            # device exposure timestamp; receive time is captured separately.
            sampled_ns = time.monotonic_ns()
            ok, decoded = self._capture.read()
            received = time.monotonic_ns()
            if not ok:
                if self._camera is not None:
                    raise _fail("camera_read_failed")
                if self._decoded_frames != self._expected_frames:
                    raise _fail("video_read_before_expected_eof")
                self.close()
                return None
            if self._camera is None:
                if self._expected_frames is None or self._decoded_frames >= self._expected_frames:
                    raise _fail("video_frame_count_exceeded")
                self._decoded_frames += 1
            if self._camera is not None:
                t_media = (sampled_ns - self._start_ns) / 1e9
            else:
                # Zero/repeated/invalid backend timestamps fail closed below.
                # Never manufacture timestamps from frame index or nominal FPS.
                t_media = float(self._capture.get(self._cv2.CAP_PROP_POS_MSEC)) / 1000
            if not math.isfinite(t_media) or not 0 <= t_media <= 60:
                raise _fail("source_media_timestamp_invalid")
            if self._camera is None:
                # Only a near-zero origin and an endpoint within one nominal
                # interval are supported. Never synthesize timestamps/frames to
                # reconcile variable or inconsistent container conventions.
                tolerance = 1 / self._fps + 1e-9
                if self._decoded_frames == 1 and t_media > tolerance:
                    raise _fail("video_timestamp_origin_invalid")
                if (self._decoded_frames == self._expected_frames and
                        (self._expected_endpoint is None or
                         abs(t_media - self._expected_endpoint) > tolerance)):
                    raise _fail("video_timestamp_endpoint_invalid")
            if self._previous_media is not None and t_media - self._previous_media < 1 / 120 - 1e-9:
                raise _fail("source_media_timestamp_rate_invalid")
            missing_slots = missing_between(self._previous_media, t_media, self._fps)
            # Videos have no playback-to-host deadline mapping. Camera receive
            # lateness is explicit against the end of the sampled nominal slot.
            slot = nominal_slot(t_media, self._fps)
            late_slots = ((slot,) if self._camera is not None and
                          (received - self._start_ns) / 1e9 > (slot + 1) / self._fps else ())
            if decoded is None or len(decoded.shape) != 3 or decoded.shape[2] != 3:
                raise _fail("decoded_frame_invalid")
            height, width = decoded.shape[:2]
            if (not 1 <= width <= 16384 or not 1 <= height <= 16384 or
                    not 0 < int(decoded.nbytes) <= 128 * 1024 * 1024):
                raise _fail("decoded_frame_limit")
            timestamp_ms = int(t_media * 1000)
            if timestamp_ms <= self._last_ms:
                raise _fail("source_timestamp_not_increasing")
            rgb = self._cv2.cvtColor(decoded, self._cv2.COLOR_BGR2RGB)
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            result = self._landmarker.detect_for_video(image, timestamp_ms)
            if len(result.pose_landmarks) > 2:
                raise _fail("runtime_pose_count_invalid")
            poses = []
            for pose in result.pose_landmarks:
                if len(pose) != len(LANDMARK_NAMES):
                    raise _fail("runtime_landmark_count_invalid")
                landmarks = []
                for name, point in zip(LANDMARK_NAMES, pose):
                    presence = getattr(point, "presence", None)
                    landmarks.append(Landmark(
                        name, float(point.x), float(point.y), float(point.z),
                        float(point.visibility), None if presence is None else float(presence),
                    ))
                poses.append(tuple(landmarks))
            batch = FrameBatch(
                t_media=t_media, poses=tuple(poses), width=int(width), height=int(height),
                pixel_aspect=self.pixel_aspect,
                nominal_fps=self._fps, source_id="local-camera" if self._camera is not None else "local-video",
                source_kind="camera" if self._camera is not None else "video",
                status="late" if late_slots else "ok",
                missing_slots=missing_slots, late_slots=late_slots,
                receive_ns=received, clock_domain="process_monotonic_ns", clock_scope=self._clock_scope,
                model_id=self._model_id, runtime_id=self._runtime_id,
            )
            # StreamValidator accounts for the decoded landmark trace. Raw image
            # buffers are ephemeral and bounded per frame, not accumulated traces.
            batch = self._validator.accept(batch)
            self._previous_media = t_media
            self._last_ms = timestamp_ms
            return batch
        except SourceError:
            self._close_on_error()
            raise
        except Exception as exc:
            self._close_on_error()
            raise _fail("device_read_failed") from exc

    def _close_on_error(self) -> None:
        # Preserve the original named failure while attempting both releases.
        try:
            self.close()
        except SourceError:
            pass

    def close(self) -> None:
        self._open_attempted = True
        capture, landmarker = self._capture, self._landmarker
        self._capture = self._landmarker = None
        self._cv2 = self._mp = self._validator = None
        errors = []
        try:
            if capture is not None:
                capture.release()
        except Exception as exc:
            errors.append(exc)
        finally:
            try:
                if landmarker is not None:
                    landmarker.close()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise _fail("device_release_failed") from errors[0]

    def __enter__(self) -> VideoSource:
        return self.open()

    def __exit__(self, *_exc: object) -> None:
        self.close()


class CameraSource(VideoSource):
    """An explicit local camera index, never implicitly selected as video fallback."""

    def __init__(
        self, index: int, *, manifest: Path, privacy: PrivacyPolicy,
        authorization: DeviceAuthorization, pixel_aspect: float,
    ) -> None:
        super().__init__(
            Path("."), manifest=manifest, privacy=privacy, authorization=authorization,
            pixel_aspect=pixel_aspect,
        )
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise _fail("camera_index_invalid")
        self._camera = index

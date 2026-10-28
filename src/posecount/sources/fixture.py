"""Bounded JSONL for declared builder-authored development input only."""
import json
from pathlib import Path
from typing import BinaryIO
from ..landmarks import FrameBatch, Landmark, SourceError, StreamValidator

_FIELDS = set(FrameBatch.__dataclass_fields__)
_REQUIRED = {"t_media", "poses", "width", "height", "source_kind", "source_id"}

def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("duplicate_json_key")
        result[key] = value
    return result

def _constant(value: str) -> None:
    raise SourceError("nonfinite_json")

def decode_frame(raw: bytes) -> FrameBatch:
    try:
        data = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
        if type(data) is not dict or set(data) - _FIELDS or not _REQUIRED <= set(data):
            raise SourceError("invalid_fixture_schema")
        if data["source_kind"] not in ("fixture", "synthetic") or not data["source_id"].startswith("development-"):
            raise SourceError("development_input_required")
        if type(data["poses"]) is not list or len(data["poses"]) > 2:
            raise SourceError("pose_limit")
        poses = []
        for pose in data["poses"]:
            if type(pose) is not list or len(pose) != 33:
                raise SourceError("invalid_pose_dimensions")
            poses.append(tuple(Landmark(**joint) for joint in pose))
        data["poses"] = tuple(poses)
        for field in ("missing_slots", "late_slots"):
            if field in data:
                if type(data[field]) is not list:
                    raise SourceError("invalid_frame_slots")
                data[field] = tuple(data[field])
        return FrameBatch(**data)
    except SourceError:
        raise
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        raise SourceError("invalid_fixture_json") from None

class FixtureSource:
    """Declarations label development provenance; they cannot certify actual rights.

    Constructing is inert. Explicit open requires development_only=True. No real
    media/trace is admitted through this port; private inputs need gated adapters.
    """
    def __init__(self, path: Path, *, development_only: bool):
        if development_only is not True:
            raise SourceError("development_input_required")
        self._path = Path(path)
        self._file: BinaryIO | None = None
        self._validator = StreamValidator()
        self._used = False
        self._closed = False

    def open(self) -> "FixtureSource":
        if self._used or self._closed:
            raise SourceError("source_closed")
        self._used = True
        try:
            if self._path.stat().st_size > 128 * 1024 * 1024:
                raise SourceError("decoded_trace_limit")
            self._file = self._path.open("rb")
        except OSError:
            self.close()
            raise SourceError("fixture_unavailable") from None
        return self

    def read(self) -> FrameBatch | None:
        if self._file is None or self._closed:
            raise SourceError("source_not_open")
        try:
            raw = self._file.readline(1024 * 1024 + 1)
            if not raw:
                self.close()
                return None
            if len(raw) > 1024 * 1024:
                raise SourceError("fixture_row_limit")
            return self._validator.accept(decode_frame(raw), len(raw))
        except OSError:
            self.close()
            raise SourceError("fixture_read_error") from None
        except ValueError:
            self.close()
            raise

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        self._closed = True

    def __enter__(self) -> "FixtureSource":
        return self.open()

    def __exit__(self, *args: object) -> None:
        self.close()

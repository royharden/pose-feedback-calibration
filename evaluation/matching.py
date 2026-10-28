"""Original deterministic observed-return matching; no counter or label imports."""

from dataclasses import dataclass
from bisect import bisect_left
from heapq import heappop, heappush
from math import isfinite
from typing import Iterable, Iterator


@dataclass(frozen=True)
class EventStamp:
    event_id: str
    t_event_media: float


@dataclass(frozen=True)
class EventMatch:
    predicted_id: str
    truth_id: str
    distance_seconds: float


@dataclass(frozen=True)
class MatchResult:
    matches: tuple[EventMatch, ...]
    fp: int
    fn: int


def validate_stamps(events: Iterable[EventStamp]) -> tuple[EventStamp, ...]:
    rows = tuple(events)
    if len(rows) > 7201:
        raise ValueError("event_support_limit")
    if any(type(row) is not EventStamp or not isinstance(row.event_id, str)
           or not row.event_id or len(row.event_id) > 256
           or type(row.t_event_media) not in (int, float)
           or not 0 <= row.t_event_media <= 60 or not isfinite(row.t_event_media) for row in rows):
        raise ValueError("invalid_event_stamp")
    if len({row.event_id for row in rows}) != len(rows):
        raise ValueError("duplicate_event_id")
    return rows


def match_events(predicted: Iterable[EventStamp], truth: Iterable[EventStamp]) -> MatchResult:
    """Greedy global nearest-distance pairs within inclusive 500ms.

    Candidate pairs sort by distance, then earlier observed event time, then
    predicted/truth time and stable string IDs. Each event is used once. No
    confirmation/display time or counter-specific logic enters matching.
    """
    predictions = validate_stamps(predicted)
    targets = validate_stamps(truth)
    ordered = tuple(sorted(targets, key=lambda row: (row.t_event_media, row.event_id)))
    times = tuple(row.t_event_media for row in ordered)

    def pairs_for(p: EventStamp) -> Iterator[tuple[float, float, float, float, str, str]]:
        split = bisect_left(times, p.t_event_media)

        def left_indices() -> Iterator[int]:
            end = split
            while end:
                start = bisect_left(times, times[end - 1], 0, end)
                # Earlier time groups run backwards, but tied IDs stay forwards.
                yield from range(start, end)
                end = start

        def side(indices: Iterable[int]) -> Iterator[tuple[float, float, float, float, str, str]]:
            for index in indices:
                target = ordered[index]
                distance = abs(p.t_event_media - target.t_event_media)
                if distance > 0.5:
                    break
                yield (distance, min(p.t_event_media, target.t_event_media),
                       p.t_event_media, target.t_event_media, p.event_id, target.event_id)

        left = side(left_indices())
        right = side(range(split, len(ordered)))
        a, b = next(left, None), next(right, None)
        while a is not None or b is not None:
            if b is None or (a is not None and a <= b):
                yield a
                a = next(left, None)
            else:
                yield b
                b = next(right, None)

    # Merge sorted per-prediction streams. This is the same global nearest-pair
    # ordering without materializing up to 7201**2 pair records in memory.
    heap = []
    for index, prediction in enumerate(predictions):
        stream = pairs_for(prediction)
        pair = next(stream, None)
        if pair is not None:
            heappush(heap, (pair, index, stream))
    used_predictions: set[str] = set()
    used_truth: set[str] = set()
    matches = []
    while heap:
        pair, index, stream = heappop(heap)
        distance, _, _, _, predicted_id, truth_id = pair
        if predicted_id in used_predictions:
            continue
        if truth_id in used_truth:
            following = next(stream, None)
            if following is not None:
                heappush(heap, (following, index, stream))
            continue
        used_predictions.add(predicted_id)
        used_truth.add(truth_id)
        matches.append(EventMatch(predicted_id, truth_id, distance))
    return MatchResult(tuple(matches), len(predictions) - len(matches), len(targets) - len(matches))

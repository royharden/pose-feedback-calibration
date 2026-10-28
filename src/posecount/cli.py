"""Bounded synthetic-development JSONL seam; no private-media ingestion."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .counter import Counter
from .schema import AngleFrame


def main() -> None:
    parser = argparse.ArgumentParser(description="M17 scalar synthetic development trace")
    parser.add_argument("--synthetic", type=Path, required=True,
                        help="Author-owned synthetic development JSONL only; never real traces")
    args = parser.parse_args()
    counter = Counter()
    consumed = 0
    try:
        with args.synthetic.open("rb") as stream:
            for index in range(7202):
                line = stream.readline(65537)
                if not line:
                    break
                consumed += len(line)
                if len(line) > 65536 or consumed > 128 * 1024 * 1024 or index >= 7201:
                    raise ValueError("trace input limit")
                row = json.loads(line)
                if not isinstance(row, dict) or set(row) != {"t_media", "theta", "visibility", "poses"}:
                    raise ValueError("invalid scalar frame fields")
                counter.update(AngleFrame(**row))
    except (OSError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        counter.source_error()
        print(json.dumps(asdict(counter.finish()), allow_nan=False))
        parser.exit(2, f"source_error: {exc}\n")
    prediction = counter.finish()
    print(json.dumps(asdict(prediction), allow_nan=False))
    if prediction.status == "error":
        parser.exit(2)


if __name__ == "__main__":
    main()

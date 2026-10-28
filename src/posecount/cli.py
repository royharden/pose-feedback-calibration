"""Keyless development inputs joined to geometry/evidence/counters, never real media."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .counter import Counter
from .pipeline import (
    CounterRequest, SourceAdmission, SourceResult, development_aggregate,
    run_source, write_development_aggregate, write_unmeasured_report,
)
from .schema import AngleFrame, CounterConfig
from .sources.fixture import FixtureSource
from .sources.synthetic import DevelopmentConfig, SyntheticSource, NEGATIVES, PERTURBATIONS


def _scalar(path: Path, counter: Counter) -> None:
    """Retain the original bounded scalar development input mode."""
    consumed = 0
    with path.open("rb") as stream:
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


def _landmarks(args: argparse.Namespace, request: CounterRequest) -> SourceResult:
    """Construct input inside the shared error boundary, after admission."""
    def factory() -> FixtureSource | SyntheticSource:
        if args.landmarks is not None:
            return FixtureSource(args.landmarks, development_only=True).open()
        return SyntheticSource(DevelopmentConfig(
            args.generate_development, perturbation=args.perturbation,
            strength=args.strength, negative=args.negative))
    return run_source(factory, (request,), admission=SourceAdmission("development"))


def main() -> None:
    parser = argparse.ArgumentParser(description=(
        "M17 builder-authored synthetic development only; source construction is runtime unverified. "
        "No human data, model download, camera, calibration evidence or accuracy claim."))
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--synthetic", type=Path, help="Legacy development scalar JSONL")
    inputs.add_argument("--landmarks", type=Path, help="Declared development-only 33-landmark JSONL")
    inputs.add_argument("--generate-development", type=int, metavar="SEED",
                        help="Original development generator, seeds 1000..1599; no expected answers")
    # Calibrated A2 is source-only and has no integrated valid-map path yet.
    # Unavailable policies must not mask an invalid input stream as not_run.
    parser.add_argument("--arm", choices=("Z", "A0", "A0v", "A1", "A2-H"), default="A1")
    parser.add_argument("--visibility-threshold", type=float,
                        help="Explicit development A0v ranking threshold, never an OOF-selected policy")
    parser.add_argument("--perturbation", choices=PERTURBATIONS)
    parser.add_argument("--strength", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--negative", choices=NEGATIVES)
    parser.add_argument("--development-report", type=Path, metavar="NEW_JSON",
                        help="Exclusive aggregate-only JSON export; no truth metrics or study claim")
    parser.add_argument("--unmeasured-report", type=Path, metavar="NEW_DIRECTORY",
                        help="Empty unmeasured aggregate report; no truth metrics or study claim")
    args = parser.parse_args()
    if args.generate_development is None and (
        args.perturbation is not None or args.negative is not None or args.strength != 1
    ):
        parser.error("generator options require --generate-development")
    if args.visibility_threshold is not None and args.arm != "A0v":
        parser.error("--visibility-threshold requires --arm A0v")
    if args.arm == "A0v" and args.visibility_threshold is None:
        parser.error("development A0v requires an explicit --visibility-threshold")
    # The counter must exist before any input operation so later errors preserve
    # all events already exposed. No final confidence can erase them.
    try:
        config = CounterConfig(visibility_threshold=args.visibility_threshold)
        counter = Counter(config, arm=args.arm)
    except (ValueError, TypeError, OverflowError):
        parser.error("invalid development counter configuration")
    failed = False
    source_result = None
    try:
        if args.synthetic is not None:
            _scalar(args.synthetic, counter)
        else:
            source_result = _landmarks(args, CounterRequest(args.arm, config))
            failed = source_result.source_status == "error"
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        failed = True
        counter.source_error()
    prediction = counter.finish() if source_result is None else source_result.predictions[0]
    payload = asdict(prediction)
    source_class = ("development_scalar" if args.synthetic is not None else
                    "development_landmarks" if args.landmarks is not None else "development_generated")
    payload["development_context"] = {
        "source_class": source_class,
        "provenance": "builder-authored development input; declaration is not proof of rights",
        "runtime_verified": False,
        "study_admitted": False,
        "policy": "manual development ranking" if args.visibility_threshold is not None else "unselected",
    }
    if source_result is not None:
        payload["source_status"] = source_result.source_status
        payload["cleanup_status"] = source_result.cleanup_status
    report_failed = False
    if args.development_report is not None:
        try:
            write_development_aggregate(args.development_report,
                                        development_aggregate(prediction, source_class=source_class))
        except (OSError, ValueError, TypeError):
            report_failed = True
            payload["report_status"] = "output_error"
        else:
            payload["report_status"] = "written_development_aggregate"
    if args.unmeasured_report is not None:
        try:
            status = write_unmeasured_report(args.unmeasured_report)
            payload["unmeasured_report_status"] = status
            report_failed |= status != "written_unmeasured_report"
        except (OSError, ValueError, TypeError):
            report_failed = True
            payload["unmeasured_report_status"] = "output_error"
    print(json.dumps(payload, allow_nan=False))
    if failed:
        parser.exit(2, "source_error: development input failed; earlier events preserved\n")
    if prediction.status == "error":
        parser.exit(2)
    if report_failed:
        parser.exit(2, "output_error: aggregate export failed\n")


if __name__ == "__main__":
    main()

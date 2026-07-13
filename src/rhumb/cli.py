from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rhumb.analysis import print_prerequisites, run_prerequisites
from rhumb.instrument import run_instrument
from rhumb.journey import run_journey


def validate_project_path(path: Path) -> Path:
    resolved = path.resolve()

    if not resolved.exists():
        raise ValueError(f"Path does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"Path is not a directory: {resolved}")

    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rhumb — constant-bearing journeys through your app."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to the project folder to analyze",
    )
    parser.add_argument(
        "--journey",
        action="store_true",
        help="Emit JSON map: end route → inbound journey paths",
    )
    parser.add_argument(
        "--instrument",
        action="store_true",
        help="Detect PostHog initialization and instrumentation",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detection + route/edge detail on stderr",
    )
    args = parser.parse_args(argv)

    if not args.journey and not args.instrument:
        parser.error("Specify at least one mode: --journey or --instrument")

    try:
        project_path = validate_project_path(args.path)
        context = run_prerequisites(project_path)
        if args.verbose or args.instrument:
            print_prerequisites(context)
            if args.journey or args.instrument:
                print()

        if args.journey:
            run_journey(context, verbose=args.verbose)
        if args.instrument:
            if args.journey:
                print()
            run_instrument(context)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

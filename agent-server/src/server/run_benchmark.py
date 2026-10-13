"""CLI for the workspace benchmark. No network/model calls during validate/report."""

import argparse
import asyncio
import logging
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .api.schemas import ExecutionConfig
from .app.execution_service import InvalidConfigError
from .benchmark.report import write_report
from .benchmark.runner import (
    DEFAULT_SUITE,
    DEFAULT_WORKSPACE,
    SERVER_ROOT,
    load_suite,
    run_benchmark,
    select_cases,
    validate_case,
)


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def non_negative(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be finite and non-negative")
    return number


def non_negative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def build_parser():
    parser = argparse.ArgumentParser(description="Benchmark analyzer → architect → judge on pinned workspace repos")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "run"):
        child = commands.add_parser(command)
        child.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
        child.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
        child.add_argument("--case", action="append", default=[], help="Select case id; repeat to select several")
        if command == "run":
            child.add_argument("--output", type=Path, default=None)
            child.add_argument("--repeats", type=positive, default=3)
            child.add_argument("--provider", default=None)
            child.add_argument("--model", default=None)
            child.add_argument("--temperature", type=float, default=None)
            child.add_argument("--max-tokens", type=positive, default=None)
            child.add_argument("--max-files", type=positive, default=500)
            child.add_argument("--max-depth", type=positive, default=8)
            child.add_argument("--rounds", type=positive, default=3)
            child.add_argument("--files-per-round", type=positive, default=8)
            child.add_argument("--timeout", type=positive, default=600)
            child.add_argument("--judge-timeout", type=positive, default=300)
            child.add_argument("--request-interval", type=non_negative, default=12.0, help="Minimum pause in seconds between model attempts, shared by all stages/cases")
            child.add_argument("--max-retries", type=non_negative_int, default=3, help="Additional attempts for transient provider errors")
            child.add_argument("--retry-backoff", type=non_negative, default=30.0, help="Initial retry delay in seconds; doubles up to 120s, respecting longer provider hints")
            child.add_argument("--input-price", type=non_negative, default=None, help="USD per million input tokens for the resolved model(s)")
            child.add_argument("--output-price", type=non_negative, default=None, help="USD per million output tokens for the resolved model(s)")
    report = commands.add_parser("report")
    report.add_argument("output", type=Path)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        if args.command == "report":
            result = write_report(args.output)
            print(f"Report: {args.output / 'report.md'} ({result['summary']['runs']} runs)")
            return 0
        suite = load_suite(args.suite)
        cases = select_cases(suite, args.case)
        if args.command == "validate":
            for case in cases:
                snapshot = validate_case(args.workspace, case)
                print(f"{case.id}: OK, {snapshot['commit'][:12]}, {snapshot['input_files']} input files, {len(case.judge_claims)} labeled claims")
            return 0
        config = ExecutionConfig(model={"provider": args.provider, "name": args.model, "temperature": args.temperature, "max_tokens": args.max_tokens})
        options = {key: getattr(args, key) for key in ("max_files", "max_depth", "rounds", "files_per_round", "timeout", "judge_timeout", "input_price", "output_price", "request_interval", "max_retries", "retry_backoff")}
        output = args.output or SERVER_ROOT / "results" / "benchmark" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        asyncio.run(run_benchmark(args.suite, args.workspace, output, args.case, args.repeats, config, options))
        print(f"Report: {output / 'report.md'}")
        return 0
    except (ValueError, OSError, ValidationError, InvalidConfigError, subprocess.SubprocessError) as error:
        print(f"error: {error}")
        return 2
    except KeyboardInterrupt:
        print("Interrupted. Finished runs and their report remain in the output directory.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

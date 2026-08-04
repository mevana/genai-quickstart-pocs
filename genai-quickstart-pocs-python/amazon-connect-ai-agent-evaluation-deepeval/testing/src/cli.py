"""Command-line interface for the evaluation harness.

Exposes the ``python -m src`` flags documented in the blog post:

    --config PATH           Alternate YAML config (default: config/default.yaml)
    --test-cases PATH       Override the configured test cases file
    --invoker {gateway,connect}
                            Invocation strategy (default from config)
    --categories CSV        Comma-separated category filter (e.g. happy_path,jailbreak)
    --dry-run               Validate config and test cases without invoking the agent
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .config import load_config
from .test_cases import filter_by_categories, load_test_cases


logger = logging.getLogger("evals_workshop_deepeval")


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src",
        description="DeepEval evaluation harness for Amazon Connect AI Agents.",
    )
    parser.add_argument(
        "--config",
        help="Path to a YAML config file (default: config/default.yaml).",
    )
    parser.add_argument(
        "--test-cases",
        help="Path to a CSV or JSON test case file. Overrides the config value.",
    )
    parser.add_argument(
        "--invoker",
        choices=["gateway", "connect"],
        help="Which invoker to use. Defaults to the config value (usually 'gateway').",
    )
    parser.add_argument(
        "--categories",
        help="Comma-separated list of categories to include (e.g. happy_path,jailbreak).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and validate config and test cases without invoking the agent.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Keep third-party loggers quiet even in verbose mode.
    if args.verbose:
        for noisy in ("botocore", "urllib3", "s3transfer", "boto3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    config = load_config(args.config)

    test_cases_path = args.test_cases or config.test_cases.path
    cases = load_test_cases(test_cases_path)
    if args.categories:
        cases = filter_by_categories(cases, args.categories.split(","))

    if not cases:
        logger.error("No test cases selected. Aborting.")
        return 2

    invoker_name = args.invoker or config.invoker.default

    logger.info(
        "Loaded %d test case(s) from %s using invoker=%s, judge=%s",
        len(cases),
        test_cases_path,
        invoker_name,
        config.aws.bedrock_model_id,
    )

    if args.dry_run:
        logger.info("--dry-run set; config and test cases validated. Exiting 0.")
        return 0

    # Delayed imports: DeepEval and boto3 are only needed for a real run, so
    # --dry-run and --help stay fast and work without the optional deps.
    from .evaluator import Evaluator
    from .invokers import build_invoker
    from .judge import get_bedrock_judge
    from .metrics import build_metrics
    from .reports import write_reports

    judge = get_bedrock_judge(
        model_id=config.aws.bedrock_model_id,
        region=config.aws.region,
    )
    metrics = build_metrics(
        judge_model=judge,
        correctness_threshold=config.metrics.correctness_threshold,
        relevancy_threshold=config.metrics.relevancy_threshold,
        guardrail_threshold=config.metrics.guardrail_threshold,
    )
    invoker = build_invoker(invoker_name, config)
    evaluator = Evaluator(config=config, invoker=invoker, metrics=metrics)

    try:
        run = evaluator.run(cases)
    finally:
        invoker.close()

    report_folder = write_reports(run, Path(config.reports.output_dir))
    logger.info("Wrote reports to %s", report_folder)

    return 0 if run.passed else 1


if __name__ == "__main__":
    sys.exit(main())

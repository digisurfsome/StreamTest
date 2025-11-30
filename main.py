#!/usr/bin/env python3
"""Main entry point for StreamTest QA automation."""

import argparse
import asyncio
import logging
import sys
from datetime import datetime

import config
from agent_loop import run_test_manual
from browser_controller import BrowserController
from gemini_client import GeminiClient
from reporter import generate_report, print_summary, save_report
from test_manual_parser import parse_test_manual

logger = logging.getLogger(__name__)


async def run_tests(manual_path: str, target_url: str | None = None) -> int:
    """Run all tests from a test manual.

    Args:
        manual_path: Path to the markdown test manual.
        target_url: Optional URL to test. Defaults to config.TARGET_URL.

    Returns:
        Exit code: 0 if all tests passed, 1 otherwise.
    """
    url = target_url or config.TARGET_URL
    started_at = datetime.now()

    logger.info(f"StreamTest starting")
    logger.info(f"Test manual: {manual_path}")
    logger.info(f"Target URL: {url}")

    # Parse test manual
    try:
        manual = parse_test_manual(manual_path)
        logger.info(f"Loaded test manual: {manual.app_name}")
        logger.info(f"Test cases: {len(manual.test_cases)}")
    except FileNotFoundError as e:
        logger.error(f"Test manual not found: {e}")
        return 1
    except Exception as e:
        logger.error(f"Error parsing test manual: {e}")
        return 1

    # Initialize Gemini client
    if not config.GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY not set. Please set it in .env file.")
        return 1

    gemini = GeminiClient()

    # Run tests
    try:
        async with BrowserController() as browser:
            # Navigate to target URL
            logger.info(f"Navigating to {url}")
            await browser.navigate(url)

            # Run all test cases
            manual = await run_test_manual(manual, browser, gemini)

    except Exception as e:
        logger.error(f"Error during test execution: {e}")
        return 1

    completed_at = datetime.now()

    # Generate report
    report = generate_report(manual, started_at, completed_at)
    report_path = save_report(report)

    # Print summary
    print_summary(manual)
    print(f"Full report saved to: {report_path}")

    # Determine exit code
    all_passed = all(tc.passed for tc in manual.test_cases)
    return 0 if all_passed else 1


def main() -> int:
    """Main entry point with CLI argument parsing.

    Returns:
        Exit code: 0 if successful, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        description="StreamTest - Gemini Computer Use QA Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --manual test_manuals/example_manual.md
  %(prog)s --manual tests.md --url http://localhost:3000
  %(prog)s -m test_manuals/login_tests.md -u http://localhost:8501

Environment Variables:
  GEMINI_API_KEY        Your Gemini API key (required)
  TARGET_URL            Default target URL (default: http://localhost:8501)
  VIEWPORT_WIDTH        Browser viewport width (default: 1280)
  VIEWPORT_HEIGHT       Browser viewport height (default: 800)
  MAX_ACTIONS_PER_STEP  Maximum actions per test step (default: 50)
  STEP_TIMEOUT_SECONDS  Timeout per step in seconds (default: 30)
""",
    )

    parser.add_argument(
        "-m",
        "--manual",
        required=True,
        help="Path to the markdown test manual file",
    )

    parser.add_argument(
        "-u",
        "--url",
        default=None,
        help=f"Target URL to test (default: {config.TARGET_URL})",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress all output except errors",
    )

    args = parser.parse_args()

    # Configure logging level
    if args.verbose:
        config.setup_logging("DEBUG")
    elif args.quiet:
        config.setup_logging("ERROR")

    # Run tests
    try:
        exit_code = asyncio.run(run_tests(args.manual, args.url))
    except KeyboardInterrupt:
        logger.info("Test execution interrupted by user")
        exit_code = 130
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

"""Test report generator for StreamTest."""

import logging
from datetime import datetime
from pathlib import Path

import config
from models import TestManual

logger = logging.getLogger(__name__)


def generate_report(
    manual: TestManual,
    started_at: datetime,
    completed_at: datetime,
) -> str:
    """Generate a markdown test report from executed test manual.

    Args:
        manual: The executed test manual with results.
        started_at: Timestamp when test execution started.
        completed_at: Timestamp when test execution completed.

    Returns:
        Markdown formatted report string.
    """
    logger.info(f"Generating report for: {manual.app_name}")

    # Calculate statistics
    total_cases = len(manual.test_cases)
    passed_cases = sum(1 for tc in manual.test_cases if tc.passed)
    overall_passed = passed_cases == total_cases

    total_steps = sum(len(tc.steps) for tc in manual.test_cases)
    passed_steps = sum(
        sum(1 for s in tc.steps if s.passed) for tc in manual.test_cases
    )

    duration = completed_at - started_at
    duration_str = f"{duration.total_seconds():.1f} seconds"

    # Build report
    lines = []

    # Header
    status_emoji = "✅" if overall_passed else "❌"
    lines.append(f"# Test Report: {manual.app_name}")
    lines.append("")
    lines.append(f"**Generated**: {completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Duration**: {duration_str}")
    lines.append(f"**Result**: {status_emoji} {'PASSED' if overall_passed else 'FAILED'}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Test Cases**: {passed_cases} of {total_cases} passed")
    lines.append(f"- **Test Steps**: {passed_steps} of {total_steps} passed")
    lines.append("")

    # Test case details
    for i, tc in enumerate(manual.test_cases, 1):
        tc_status = "✅" if tc.passed else "❌"
        lines.append(f"## Test Case {i}: {tc.name}")
        lines.append("")
        lines.append(f"**Status**: {tc_status} {'PASSED' if tc.passed else 'FAILED'}")
        lines.append(f"**Expected**: {tc.expected_outcome}")
        lines.append("")

        for step in tc.steps:
            step_status = "✅" if step.passed else "❌"
            lines.append(f"### Step {step.step_number}: {step.instruction}")
            lines.append("")
            lines.append(f"**Result**: {step_status} {'PASSED' if step.passed else 'FAILED'}")
            lines.append("")

            # Actions taken
            if step.actions_taken:
                lines.append("**Actions taken**:")
                for action in step.actions_taken:
                    lines.append(f"- {action}")
                lines.append("")

            # Notes
            if step.notes:
                lines.append(f"**Notes**: {step.notes}")
                lines.append("")

            # Screenshots
            if step.screenshot_before:
                lines.append(f"**Before**: ![Before]({step.screenshot_before})")
            if step.screenshot_after:
                lines.append(f"**After**: ![After]({step.screenshot_after})")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Footer
    lines.append("## Execution Details")
    lines.append("")
    lines.append(f"- **Started**: {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **Completed**: {completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **Total Duration**: {duration_str}")
    lines.append("")

    report = "\n".join(lines)
    logger.info(f"Report generated: {len(lines)} lines")
    return report


def save_report(report: str, output_dir: str | None = None) -> str:
    """Save the report to a markdown file.

    Args:
        report: Markdown report string.
        output_dir: Directory to save report. Defaults to config.REPORTS_DIR.

    Returns:
        Path to the saved report file.
    """
    if output_dir is None:
        output_path = config.REPORTS_DIR
    else:
        output_path = Path(output_dir)

    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_report_{timestamp}.md"
    filepath = output_path / filename

    filepath.write_text(report, encoding="utf-8")
    logger.info(f"Report saved: {filepath}")

    return str(filepath)


def print_summary(manual: TestManual) -> None:
    """Print a brief summary of test results to console.

    Args:
        manual: The executed test manual with results.
    """
    total_cases = len(manual.test_cases)
    passed_cases = sum(1 for tc in manual.test_cases if tc.passed)
    overall_passed = passed_cases == total_cases

    status = "PASSED ✅" if overall_passed else "FAILED ❌"

    print("\n" + "=" * 50)
    print(f"TEST RESULTS: {status}")
    print("=" * 50)
    print(f"Test Cases: {passed_cases}/{total_cases} passed")

    for tc in manual.test_cases:
        tc_status = "✅" if tc.passed else "❌"
        steps_passed = sum(1 for s in tc.steps if s.passed)
        print(f"  {tc_status} {tc.name} ({steps_passed}/{len(tc.steps)} steps)")

    print("=" * 50 + "\n")

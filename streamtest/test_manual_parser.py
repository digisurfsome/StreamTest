"""Parser for markdown test manuals."""

import logging
import re
from pathlib import Path

from models import TestCase, TestManual, TestStep

logger = logging.getLogger(__name__)


def parse_test_manual(filepath: str) -> TestManual:
    """Parse a markdown test manual file into a TestManual dataclass.

    Args:
        filepath: Path to the markdown test manual file.

    Returns:
        TestManual dataclass populated with parsed test cases and steps.

    Raises:
        FileNotFoundError: If the filepath does not exist.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Test manual not found: {filepath}")

    content = path.read_text(encoding="utf-8")
    logger.info(f"Parsing test manual: {filepath}")

    # Extract app name from title
    app_name = _extract_app_name(content)
    logger.debug(f"Extracted app name: {app_name}")

    # Extract test cases
    test_cases = _extract_test_cases(content)
    logger.info(f"Extracted {len(test_cases)} test cases")

    return TestManual(app_name=app_name, test_cases=test_cases)


def _extract_app_name(content: str) -> str:
    """Extract app name from the test manual title.

    Args:
        content: Full markdown content.

    Returns:
        App name, or 'Unknown App' if not found.
    """
    # Look for: # Test Manual: [App Name]
    pattern = r"^#\s+Test\s+Manual:\s*(.+)$"
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)

    if match:
        return match.group(1).strip()

    # Fallback: look for any H1 heading
    h1_pattern = r"^#\s+(.+)$"
    match = re.search(h1_pattern, content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    return "Unknown App"


def _extract_test_cases(content: str) -> list[TestCase]:
    """Extract all test cases from the markdown content.

    Args:
        content: Full markdown content.

    Returns:
        List of TestCase dataclasses.
    """
    test_cases = []

    # Split by test case headers (## Test Case N: ...)
    # Pattern matches "## Test Case" followed by optional number and name
    pattern = r"##\s+Test\s+Case\s*\d*:?\s*(.+?)(?=##\s+Test\s+Case|\Z)"
    matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)

    if not matches:
        # Try alternative pattern: any ## heading followed by ### Steps
        alt_pattern = r"##\s+(.+?)(?=##|\Z)"
        matches = re.findall(alt_pattern, content, re.DOTALL)

    for i, match in enumerate(matches):
        test_case = _parse_test_case(match, i + 1)
        if test_case.steps:  # Only add if has steps
            test_cases.append(test_case)

    return test_cases


def _parse_test_case(case_content: str, case_number: int) -> TestCase:
    """Parse a single test case block.

    Args:
        case_content: Content of the test case section.
        case_number: Sequential number of this test case.

    Returns:
        TestCase dataclass.
    """
    # Extract name from first line
    lines = case_content.strip().split("\n")
    name = lines[0].strip() if lines else f"Test Case {case_number}"

    # Extract steps
    steps = _extract_steps(case_content)

    # Extract expected outcome
    expected = _extract_expected(case_content)

    return TestCase(name=name, steps=steps, expected_outcome=expected)


def _extract_steps(case_content: str) -> list[TestStep]:
    """Extract steps from a test case.

    Args:
        case_content: Content of the test case section.

    Returns:
        List of TestStep dataclasses.
    """
    steps = []

    # Find the Steps section
    steps_match = re.search(
        r"###\s*Steps:?\s*\n(.*?)(?=###|\Z)", case_content, re.DOTALL | re.IGNORECASE
    )

    if steps_match:
        steps_content = steps_match.group(1)
    else:
        # Try to find numbered list anywhere in content
        steps_content = case_content

    # Extract numbered items (1. ..., 2. ..., etc.)
    step_pattern = r"^\s*(\d+)\.\s+(.+?)(?=^\s*\d+\.|\Z)"
    matches = re.findall(step_pattern, steps_content, re.MULTILINE | re.DOTALL)

    for step_num, instruction in matches:
        instruction = instruction.strip()
        # Remove any trailing ### or ## markers that got captured
        instruction = re.sub(r"###.*$", "", instruction, flags=re.DOTALL).strip()

        if instruction:
            steps.append(
                TestStep(instruction=instruction, step_number=int(step_num))
            )

    # If no numbered steps found, try bullet points
    if not steps:
        bullet_pattern = r"^\s*[-*]\s+(.+)$"
        matches = re.findall(bullet_pattern, steps_content, re.MULTILINE)
        for i, instruction in enumerate(matches, 1):
            instruction = instruction.strip()
            if instruction:
                steps.append(TestStep(instruction=instruction, step_number=i))

    return steps


def _extract_expected(case_content: str) -> str:
    """Extract expected outcome from a test case.

    Args:
        case_content: Content of the test case section.

    Returns:
        Expected outcome string, or default message if not found.
    """
    # Look for: ### Expected: ...
    pattern = r"###\s*Expected:?\s*(.+?)(?=###|##|\Z)"
    match = re.search(pattern, case_content, re.DOTALL | re.IGNORECASE)

    if match:
        expected = match.group(1).strip()
        # Clean up any markdown artifacts
        expected = re.sub(r"\n+", " ", expected).strip()
        return expected

    return "Test completes successfully"

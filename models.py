"""Data models for StreamTest QA automation."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TestStep:
    """Represents a single test step within a test case.

    Attributes:
        instruction: Natural language instruction for this step.
        step_number: Sequential number of this step within the test case.
        screenshot_before: Path to screenshot captured before executing this step.
        screenshot_after: Path to screenshot captured after executing this step.
        actions_taken: List of actions performed during this step.
        passed: Whether this step passed (None if not yet executed).
        notes: Additional notes or error messages for this step.
    """

    instruction: str
    step_number: int
    screenshot_before: str | None = None
    screenshot_after: str | None = None
    actions_taken: list[str] = field(default_factory=list)
    passed: bool | None = None
    notes: str = ""


@dataclass
class TestCase:
    """Represents a complete test case with multiple steps.

    Attributes:
        name: Name/title of the test case.
        steps: List of test steps to execute.
        expected_outcome: Description of what success looks like.
        passed: Whether all steps in this test case passed (None if not yet executed).
    """

    name: str
    steps: list[TestStep]
    expected_outcome: str
    passed: bool | None = None


@dataclass
class TestManual:
    """Represents a complete test manual with multiple test cases.

    Attributes:
        app_name: Name of the application being tested.
        test_cases: List of test cases to execute.
    """

    app_name: str
    test_cases: list[TestCase]


@dataclass
class TestReport:
    """Represents a generated test report.

    Attributes:
        manual: The test manual that was executed.
        started_at: Timestamp when test execution started.
        completed_at: Timestamp when test execution completed.
        overall_passed: Whether all test cases passed.
        summary: Text summary of the test results.
    """

    manual: TestManual
    started_at: datetime
    completed_at: datetime | None = None
    overall_passed: bool = False
    summary: str = ""

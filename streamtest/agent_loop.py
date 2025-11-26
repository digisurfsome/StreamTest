"""Core agent loop logic for executing test steps."""

import asyncio
import logging
from datetime import datetime

import config
from browser_controller import BrowserController
from gemini_client import GeminiClient
from models import TestCase, TestManual, TestStep

logger = logging.getLogger(__name__)


async def run_test_step(
    step: TestStep,
    browser: BrowserController,
    gemini: GeminiClient,
) -> TestStep:
    """Execute a single test step using Gemini Computer Use.

    Args:
        step: The test step to execute.
        browser: Browser controller instance.
        gemini: Gemini client instance.

    Returns:
        Updated TestStep with execution results.
    """
    logger.info(f"Executing step {step.step_number}: {step.instruction}")
    action_count = 0
    max_actions = config.MAX_ACTIONS_PER_STEP

    try:
        # Capture screenshot before
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        before_path = f"screenshots/step{step.step_number}_before_{timestamp}.png"
        screenshot_bytes = await browser.screenshot(
            str(config.SCREENSHOTS_DIR / f"step{step.step_number}_before_{timestamp}.png")
        )
        step.screenshot_before = before_path
        logger.debug(f"Captured before screenshot: {before_path}")

        # Agent loop: get action, execute, check completion
        while action_count < max_actions:
            action_count += 1
            logger.debug(f"Action {action_count}/{max_actions}")

            # Get next action from Gemini
            action = await gemini.get_action(screenshot_bytes, step.instruction)
            action_type = action.get("action_type", "unknown")
            reasoning = action.get("reasoning", "")

            logger.info(f"Gemini action: {action_type} - {reasoning[:100]}")
            step.actions_taken.append(f"{action_type}: {reasoning[:100]}")

            # Check if done or error
            if action_type == "done":
                logger.info("Step marked as done by Gemini")
                break
            elif action_type == "error":
                logger.error(f"Error from Gemini: {action.get('error', 'Unknown error')}")
                step.notes = f"Error: {action.get('error', 'Unknown error')}"
                step.passed = False
                break
            elif action_type == "observe":
                # Just observing, check if complete
                pass

            # Execute action
            await _execute_action(browser, action)

            # Wait a moment for UI to update
            await asyncio.sleep(0.5)

            # Capture new screenshot
            screenshot_bytes = await browser.screenshot()

            # Check if instruction is complete
            assessment = await gemini.assess_completion(screenshot_bytes, step.instruction)
            if assessment.get("completed", False):
                logger.info(f"Step completed: {assessment.get('reasoning', '')[:100]}")
                step.passed = assessment.get("passed", True)
                break

        # Capture screenshot after
        after_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        after_path = f"screenshots/step{step.step_number}_after_{after_timestamp}.png"
        await browser.screenshot(
            str(config.SCREENSHOTS_DIR / f"step{step.step_number}_after_{after_timestamp}.png")
        )
        step.screenshot_after = after_path
        logger.debug(f"Captured after screenshot: {after_path}")

        # Set passed if not already set
        if step.passed is None:
            if action_count >= max_actions:
                step.passed = False
                step.notes = f"Max actions ({max_actions}) reached without completion"
                logger.warning(step.notes)
            else:
                # Final assessment
                final_assessment = await gemini.assess_completion(
                    screenshot_bytes, step.instruction
                )
                step.passed = final_assessment.get("passed", False)
                step.notes = final_assessment.get("reasoning", "")[:200]

    except Exception as e:
        logger.error(f"Error executing step {step.step_number}: {e}")
        step.passed = False
        step.notes = f"Execution error: {str(e)}"

    logger.info(
        f"Step {step.step_number} {'PASSED' if step.passed else 'FAILED'}: {step.notes[:50] if step.notes else 'OK'}"
    )
    return step


async def _execute_action(browser: BrowserController, action: dict) -> None:
    """Execute a single action on the browser.

    Args:
        browser: Browser controller instance.
        action: Action dictionary from Gemini.
    """
    action_type = action.get("action_type", "")

    if action_type == "click":
        x = action.get("x", 0)
        y = action.get("y", 0)
        await browser.click(x, y)

    elif action_type == "type":
        text = action.get("text", "")
        if text:
            await browser.type_text(text)

    elif action_type == "scroll":
        direction = action.get("direction", "down")
        amount = action.get("amount", 100)
        await browser.scroll(direction, amount)

    elif action_type == "key":
        key = action.get("key", "")
        if key:
            await browser.press_key(key)

    else:
        logger.debug(f"No action executed for type: {action_type}")


async def run_test_case(
    test_case: TestCase,
    browser: BrowserController,
    gemini: GeminiClient,
) -> TestCase:
    """Execute all steps in a test case.

    Args:
        test_case: The test case to execute.
        browser: Browser controller instance.
        gemini: Gemini client instance.

    Returns:
        Updated TestCase with execution results.
    """
    logger.info(f"Running test case: {test_case.name}")
    all_passed = True

    for step in test_case.steps:
        step = await run_test_step(step, browser, gemini)
        if not step.passed:
            all_passed = False
            logger.warning(f"Step {step.step_number} failed, continuing with remaining steps")

    test_case.passed = all_passed
    logger.info(f"Test case '{test_case.name}': {'PASSED' if all_passed else 'FAILED'}")
    return test_case


async def run_test_manual(
    manual: TestManual,
    browser: BrowserController,
    gemini: GeminiClient,
) -> TestManual:
    """Execute all test cases in a test manual.

    Args:
        manual: The test manual to execute.
        browser: Browser controller instance.
        gemini: Gemini client instance.

    Returns:
        Updated TestManual with all execution results.
    """
    logger.info(f"Running test manual: {manual.app_name}")
    logger.info(f"Total test cases: {len(manual.test_cases)}")

    for i, test_case in enumerate(manual.test_cases):
        logger.info(f"Test case {i + 1}/{len(manual.test_cases)}")
        manual.test_cases[i] = await run_test_case(test_case, browser, gemini)

    passed_count = sum(1 for tc in manual.test_cases if tc.passed)
    total_count = len(manual.test_cases)

    logger.info(f"Test manual complete: {passed_count}/{total_count} test cases passed")
    return manual

"""Gemini API client for Computer Use operations."""

import asyncio
import logging
from typing import Any

from google import genai
from google.genai import types

import config

logger = logging.getLogger(__name__)

# Gemini Computer Use model
MODEL_ID = "gemini-2.5-flash-preview-04-17"


class GeminiClient:
    """Client for interacting with Gemini Computer Use API.

    This client handles sending screenshots and instructions to the Gemini API
    and parsing the responses to extract actions for browser automation.
    """

    def __init__(self) -> None:
        """Initialize the Gemini client with API credentials."""
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._max_retries = 3
        self._base_delay = 1.0
        logger.info("GeminiClient initialized")

    async def get_action(
        self, screenshot_bytes: bytes, instruction: str
    ) -> dict[str, Any]:
        """Send screenshot and instruction to Gemini, get next action.

        Args:
            screenshot_bytes: PNG screenshot of current browser state.
            instruction: Natural language instruction for what to do.

        Returns:
            Dictionary containing the action to perform, with keys like:
            - 'action_type': 'click', 'type', 'scroll', 'done', or 'error'
            - 'x', 'y': Coordinates for click actions
            - 'text': Text for type actions
            - 'direction', 'amount': For scroll actions
            - 'reasoning': Explanation of the action
        """
        prompt = f"""You are a QA test automation assistant. Your task is to help execute test steps on a web application.

Current instruction: {instruction}

Look at the screenshot and determine the next action to take to complete this instruction.
Respond with a specific action. If the instruction appears to be complete based on what you see, indicate that.

Describe what you see and what action you will take."""

        return await self._send_request(screenshot_bytes, prompt)

    async def assess_completion(
        self, screenshot_bytes: bytes, instruction: str
    ) -> dict[str, Any]:
        """Assess whether a test step instruction has been completed.

        Args:
            screenshot_bytes: PNG screenshot of current browser state.
            instruction: The instruction that was supposed to be executed.

        Returns:
            Dictionary containing:
            - 'completed': Boolean indicating if instruction is complete
            - 'reasoning': Explanation of the assessment
            - 'passed': Boolean indicating if the step passed (may differ from completed)
        """
        prompt = f"""You are a QA test automation assistant evaluating test step completion.

The instruction was: {instruction}

Look at the screenshot and assess:
1. Has this instruction been completed?
2. Was it successful (did it achieve what was intended)?

Provide your assessment with clear reasoning."""

        return await self._send_request(screenshot_bytes, prompt, assess_mode=True)

    async def _send_request(
        self,
        screenshot_bytes: bytes,
        prompt: str,
        assess_mode: bool = False,
    ) -> dict[str, Any]:
        """Send request to Gemini API with retry logic.

        Args:
            screenshot_bytes: PNG screenshot bytes.
            prompt: Text prompt to send.
            assess_mode: If True, parse response for completion assessment.

        Returns:
            Parsed response dictionary.
        """
        for attempt in range(self._max_retries):
            try:
                contents = [
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    mime_type="image/png", data=screenshot_bytes
                                )
                            ),
                            types.Part(text=prompt),
                        ],
                    )
                ]

                config_obj = types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            computer_use=types.ComputerUse(
                                environment=types.Environment.ENVIRONMENT_BROWSER
                            )
                        )
                    ]
                )

                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=MODEL_ID,
                    contents=contents,
                    config=config_obj,
                )

                return self._parse_response(response, assess_mode)

            except Exception as e:
                delay = self._base_delay * (2**attempt)
                logger.warning(
                    f"Gemini API request failed (attempt {attempt + 1}/{self._max_retries}): {e}"
                )
                if attempt < self._max_retries - 1:
                    logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("Max retries exceeded for Gemini API request")
                    return self._error_response(str(e))

        return self._error_response("Unknown error")

    def _parse_response(
        self, response: Any, assess_mode: bool = False
    ) -> dict[str, Any]:
        """Parse Gemini API response to extract actions or assessment.

        Args:
            response: Raw response from Gemini API.
            assess_mode: If True, parse for completion assessment.

        Returns:
            Parsed response dictionary.
        """
        try:
            # Check for function calls (computer use actions)
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    # Handle function calls for computer use
                    if hasattr(part, "function_call") and part.function_call:
                        return self._parse_function_call(part.function_call)

                    # Handle text responses
                    if hasattr(part, "text") and part.text:
                        text = part.text.lower()

                        if assess_mode:
                            return self._parse_assessment(part.text)

                        return self._parse_text_action(part.text)

            # Default response if no actionable content
            if assess_mode:
                return {
                    "completed": False,
                    "reasoning": "Unable to assess from response",
                    "passed": False,
                }

            return {
                "action_type": "done",
                "reasoning": "No further action identified",
            }

        except Exception as e:
            logger.error(f"Error parsing Gemini response: {e}")
            return self._error_response(str(e))

    def _parse_function_call(self, function_call: Any) -> dict[str, Any]:
        """Parse a function call from Gemini response.

        Args:
            function_call: The function call object from the response.

        Returns:
            Parsed action dictionary.
        """
        name = function_call.name if hasattr(function_call, "name") else ""
        args = function_call.args if hasattr(function_call, "args") else {}

        if "click" in name.lower():
            return {
                "action_type": "click",
                "x": args.get("x", 0),
                "y": args.get("y", 0),
                "reasoning": f"Click at ({args.get('x', 0)}, {args.get('y', 0)})",
            }
        elif "type" in name.lower() or "input" in name.lower():
            return {
                "action_type": "type",
                "text": args.get("text", ""),
                "reasoning": f"Type text: {args.get('text', '')}",
            }
        elif "scroll" in name.lower():
            return {
                "action_type": "scroll",
                "direction": args.get("direction", "down"),
                "amount": args.get("amount", 100),
                "reasoning": f"Scroll {args.get('direction', 'down')}",
            }
        else:
            return {
                "action_type": "unknown",
                "raw_function": name,
                "args": args,
                "reasoning": f"Unknown function: {name}",
            }

    def _parse_text_action(self, text: str) -> dict[str, Any]:
        """Parse action from text response when no function call is present.

        Args:
            text: Text response from Gemini.

        Returns:
            Parsed action dictionary.
        """
        text_lower = text.lower()

        # Check for completion indicators
        if any(
            phrase in text_lower
            for phrase in ["complete", "done", "finished", "no action needed"]
        ):
            return {
                "action_type": "done",
                "reasoning": text[:200],
            }

        # Check for click action descriptions
        if "click" in text_lower:
            return {
                "action_type": "click",
                "x": 640,  # Default to center
                "y": 400,
                "reasoning": text[:200],
                "needs_coordinates": True,
            }

        # Check for type action descriptions
        if any(word in text_lower for word in ["type", "enter", "input"]):
            return {
                "action_type": "type",
                "text": "",
                "reasoning": text[:200],
                "needs_text": True,
            }

        # Check for scroll action descriptions
        if "scroll" in text_lower:
            direction = "down"
            if "up" in text_lower:
                direction = "up"
            elif "left" in text_lower:
                direction = "left"
            elif "right" in text_lower:
                direction = "right"

            return {
                "action_type": "scroll",
                "direction": direction,
                "amount": 100,
                "reasoning": text[:200],
            }

        # Default: indicate observation only
        return {
            "action_type": "observe",
            "reasoning": text[:200],
        }

    def _parse_assessment(self, text: str) -> dict[str, Any]:
        """Parse completion assessment from text response.

        Args:
            text: Text response containing assessment.

        Returns:
            Assessment dictionary.
        """
        text_lower = text.lower()

        # Look for positive indicators
        completed = any(
            phrase in text_lower
            for phrase in [
                "completed",
                "successful",
                "done",
                "achieved",
                "passed",
                "yes",
            ]
        )

        # Look for negative indicators
        failed = any(
            phrase in text_lower
            for phrase in ["failed", "error", "not complete", "unsuccessful", "no"]
        )

        if failed:
            completed = False
            passed = False
        elif completed:
            passed = True
        else:
            passed = None

        return {
            "completed": completed,
            "passed": passed if passed is not None else completed,
            "reasoning": text[:300],
        }

    def _error_response(self, error_message: str) -> dict[str, Any]:
        """Create an error response dictionary.

        Args:
            error_message: Description of the error.

        Returns:
            Error response dictionary.
        """
        return {
            "action_type": "error",
            "error": error_message,
            "reasoning": f"Error occurred: {error_message}",
        }

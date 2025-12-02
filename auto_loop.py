#!/usr/bin/env python3
"""
Auto-Loop: Automated Test → Fix → Retest System

This script creates the loop between StreamTest (tester) and Claude (fixer).
When tests fail, it automatically sends errors to Claude API, gets fixes,
applies them, and retests until everything passes.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# Configuration
MAX_LOOPS = 10  # Safety limit - don't loop forever
CLAUDE_MODEL = "claude-sonnet-4-20250514"  # Fast and capable


class AutoLoop:
    """Orchestrates the test → fix → retest loop."""

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set in .env file!\n"
                "Get your key from: https://console.anthropic.com/api-keys"
            )
        self.client = Anthropic(api_key=api_key)
        self.loop_count = 0
        self.history = []  # Track what we've tried

    def run(self, test_manual: str = "test_manuals/example_manual.md"):
        """Run the full auto-loop until tests pass or max loops reached."""
        print("=" * 60)
        print("AUTO-LOOP: Automated Test → Fix → Retest System")
        print("=" * 60)
        print()

        while self.loop_count < MAX_LOOPS:
            self.loop_count += 1
            print(f"\n{'='*60}")
            print(f"LOOP {self.loop_count}/{MAX_LOOPS}")
            print("=" * 60)

            # Step 1: Run tests
            print("\n[1/4] Running StreamTest...")
            test_result = self.run_tests(test_manual)

            if test_result["all_passed"]:
                print("\n" + "🎉" * 20)
                print("ALL TESTS PASSED!")
                print("🎉" * 20)
                self.save_final_report(test_result)
                return True

            # Step 2: Analyze failures
            print("\n[2/4] Analyzing failures...")
            failures = self.extract_failures(test_result)
            print(f"   Found {len(failures)} failure(s)")

            # Step 3: Ask Claude to fix
            print("\n[3/4] Asking Claude for fixes...")
            fixes = self.get_fixes_from_claude(failures)

            if not fixes:
                print("   ❌ Claude couldn't determine fixes")
                continue

            # Step 4: Apply fixes
            print("\n[4/4] Applying fixes...")
            self.apply_fixes(fixes)

            print("\n   ✅ Fixes applied, retesting...")

        print(f"\n❌ Max loops ({MAX_LOOPS}) reached without success")
        return False

    def run_tests(self, test_manual: str) -> dict:
        """Run StreamTest and capture results."""
        try:
            # Run main.py with the test manual
            result = subprocess.run(
                [sys.executable, "main.py", "--manual", test_manual],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            output = result.stdout + result.stderr

            # Check for success indicators
            all_passed = "ALL TESTS PASSED" in output or result.returncode == 0

            # Find the latest report file
            reports_dir = Path("reports")
            report_files = sorted(reports_dir.glob("*.md"), key=os.path.getmtime, reverse=True)
            report_content = ""
            if report_files:
                report_content = report_files[0].read_text()

            return {
                "all_passed": all_passed,
                "output": output,
                "report": report_content,
                "return_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "all_passed": False,
                "output": "Test timed out after 5 minutes",
                "report": "",
                "return_code": -1,
            }
        except Exception as e:
            return {
                "all_passed": False,
                "output": f"Error running tests: {str(e)}",
                "report": "",
                "return_code": -1,
            }

    def extract_failures(self, test_result: dict) -> list:
        """Extract failure information from test results."""
        failures = []

        # Parse output for errors
        output = test_result["output"]
        report = test_result["report"]

        # Look for common error patterns
        error_patterns = [
            r"❌.*",
            r"Error:.*",
            r"Failed:.*",
            r"Exception:.*",
            r"Traceback.*",
        ]

        for pattern in error_patterns:
            matches = re.findall(pattern, output, re.IGNORECASE)
            failures.extend(matches)

        # Add report content if there are failures noted
        if "FAILED" in report:
            failures.append(f"Report indicates failures:\n{report[:2000]}")

        return failures

    def get_fixes_from_claude(self, failures: list) -> list:
        """Send failures to Claude and get fix instructions."""
        # Read current code files for context
        code_files = {}
        for py_file in Path(".").glob("*.py"):
            if py_file.name != "auto_loop.py":  # Don't include self
                code_files[py_file.name] = py_file.read_text()

        prompt = f"""You are an expert Python developer. The following test failures occurred:

FAILURES:
{json.dumps(failures, indent=2)}

CURRENT CODE FILES:
{json.dumps(code_files, indent=2)}

PREVIOUS ATTEMPTS IN THIS SESSION:
{json.dumps(self.history[-5:], indent=2) if self.history else "None yet"}

Analyze the failures and provide fixes. Respond in this exact JSON format:
{{
    "analysis": "Brief explanation of what's wrong",
    "fixes": [
        {{
            "file": "filename.py",
            "action": "replace",
            "old_code": "exact code to find",
            "new_code": "exact code to replace with"
        }}
    ]
}}

IMPORTANT:
- The old_code must match EXACTLY what's in the file
- Only fix what's broken, don't refactor everything
- If you can't determine the fix, return empty fixes array
"""

        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text

            # Extract JSON from response
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                fix_data = json.loads(json_match.group())
                self.history.append({
                    "loop": self.loop_count,
                    "failures": failures[:3],  # Keep history manageable
                    "fixes": fix_data.get("fixes", []),
                })
                print(f"   Analysis: {fix_data.get('analysis', 'N/A')}")
                return fix_data.get("fixes", [])

        except Exception as e:
            print(f"   Error getting fixes: {e}")

        return []

    def apply_fixes(self, fixes: list):
        """Apply the fixes to the code files."""
        for fix in fixes:
            file_path = Path(fix["file"])
            if not file_path.exists():
                print(f"   ⚠️ File not found: {fix['file']}")
                continue

            content = file_path.read_text()
            old_code = fix.get("old_code", "")
            new_code = fix.get("new_code", "")

            if old_code and old_code in content:
                new_content = content.replace(old_code, new_code, 1)
                file_path.write_text(new_content)
                print(f"   ✅ Fixed: {fix['file']}")
            else:
                print(f"   ⚠️ Could not find code to replace in {fix['file']}")

    def save_final_report(self, test_result: dict):
        """Save a summary of the auto-loop session."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_loops": self.loop_count,
            "success": True,
            "history": self.history,
        }

        report_path = Path("reports") / f"auto_loop_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.write_text(json.dumps(report, indent=2))
        print(f"\n📄 Session report saved: {report_path}")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Auto-Loop: Test → Fix → Retest")
    parser.add_argument(
        "--manual",
        default="test_manuals/example_manual.md",
        help="Path to test manual",
    )
    parser.add_argument(
        "--max-loops",
        type=int,
        default=10,
        help="Maximum fix attempts",
    )

    args = parser.parse_args()

    global MAX_LOOPS
    MAX_LOOPS = args.max_loops

    try:
        loop = AutoLoop()
        success = loop.run(args.manual)
        sys.exit(0 if success else 1)
    except ValueError as e:
        print(f"❌ Setup Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()

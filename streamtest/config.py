"""Configuration and environment variable loading for StreamTest."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Gemini API Configuration
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# Target Application Configuration
TARGET_URL: str = os.getenv("TARGET_URL", "http://localhost:8501")

# Browser Viewport Configuration
VIEWPORT_WIDTH: int = int(os.getenv("VIEWPORT_WIDTH", "1280"))
VIEWPORT_HEIGHT: int = int(os.getenv("VIEWPORT_HEIGHT", "800"))

# Test Execution Configuration
MAX_ACTIONS_PER_STEP: int = int(os.getenv("MAX_ACTIONS_PER_STEP", "50"))
STEP_TIMEOUT_SECONDS: int = int(os.getenv("STEP_TIMEOUT_SECONDS", "30"))

# Directory Configuration
BASE_DIR: Path = Path(__file__).parent
SCREENSHOTS_DIR: Path = BASE_DIR / "screenshots"
REPORTS_DIR: Path = BASE_DIR / "reports"
TEST_MANUALS_DIR: Path = BASE_DIR / "test_manuals"

# Ensure directories exist
SCREENSHOTS_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)
TEST_MANUALS_DIR.mkdir(exist_ok=True)

# Logging Configuration
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging(level: str | None = None) -> None:
    """Configure logging for the application.

    Args:
        level: Optional log level override. Defaults to LOG_LEVEL from env.
    """
    log_level = level or LOG_LEVEL
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format=LOG_FORMAT,
    )


# Initialize logging on module import
setup_logging()

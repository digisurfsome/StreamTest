"""Browser controller using Playwright for browser automation."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Self

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

import config

logger = logging.getLogger(__name__)


class BrowserController:
    """Controller for browser automation using Playwright.

    This class provides methods for launching a browser, navigating to URLs,
    capturing screenshots, and performing user interactions like clicks,
    typing, and scrolling.

    Usage:
        async with BrowserController() as browser:
            await browser.navigate("http://localhost:8501")
            screenshot = await browser.screenshot()
    """

    def __init__(self) -> None:
        """Initialize the browser controller."""
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._screenshot_counter = 0
        logger.info("BrowserController initialized")

    async def __aenter__(self) -> Self:
        """Async context manager entry - launches browser."""
        await self.launch()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - closes browser."""
        await self.close()

    async def launch(self) -> None:
        """Launch Playwright Chromium browser.

        Creates a new browser instance with configured viewport settings.
        """
        logger.info("Launching browser...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        self._context = await self._browser.new_context(
            viewport={
                "width": config.VIEWPORT_WIDTH,
                "height": config.VIEWPORT_HEIGHT,
            }
        )
        self._page = await self._context.new_page()
        logger.info(
            f"Browser launched with viewport {config.VIEWPORT_WIDTH}x{config.VIEWPORT_HEIGHT}"
        )

    async def navigate(self, url: str) -> None:
        """Navigate to a URL.

        Args:
            url: The URL to navigate to.

        Raises:
            RuntimeError: If browser is not launched.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        logger.info(f"Navigating to {url}")
        await self._page.goto(url, wait_until="networkidle", timeout=30000)
        logger.info(f"Navigation complete: {url}")

    async def screenshot(self, save_path: str | None = None) -> bytes:
        """Capture current viewport as PNG bytes.

        Args:
            save_path: Optional path to save the screenshot. If None,
                      generates a timestamped filename in screenshots directory.

        Returns:
            PNG screenshot as bytes.

        Raises:
            RuntimeError: If browser is not launched.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        self._screenshot_counter += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if save_path is None:
            filename = f"screenshot_{timestamp}_{self._screenshot_counter:04d}.png"
            save_path = str(config.SCREENSHOTS_DIR / filename)

        screenshot_bytes = await self._page.screenshot(type="png")

        # Save to file
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(screenshot_bytes)

        logger.debug(f"Screenshot saved: {save_path}")
        return screenshot_bytes

    def get_last_screenshot_path(self) -> str:
        """Get the path of the most recently saved screenshot.

        Returns:
            Path to the last screenshot.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}_{self._screenshot_counter:04d}.png"
        return str(config.SCREENSHOTS_DIR / filename)

    async def click(self, x: int, y: int) -> None:
        """Click at specified coordinates.

        Args:
            x: X coordinate (pixels from left).
            y: Y coordinate (pixels from top).

        Raises:
            RuntimeError: If browser is not launched.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        logger.info(f"Clicking at ({x}, {y})")
        await self._page.mouse.click(x, y)
        # Wait a bit for any reactions to the click
        await asyncio.sleep(0.5)

    async def type_text(self, text: str) -> None:
        """Type text using keyboard.

        Args:
            text: Text to type.

        Raises:
            RuntimeError: If browser is not launched.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        logger.info(f"Typing text: {text[:50]}...")
        await self._page.keyboard.type(text, delay=50)

    async def press_key(self, key: str) -> None:
        """Press a specific key.

        Args:
            key: Key to press (e.g., 'Enter', 'Tab', 'Escape').

        Raises:
            RuntimeError: If browser is not launched.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        logger.info(f"Pressing key: {key}")
        await self._page.keyboard.press(key)

    async def scroll(self, direction: str, amount: int = 100) -> None:
        """Scroll the page in specified direction.

        Args:
            direction: Direction to scroll ('up', 'down', 'left', 'right').
            amount: Number of pixels to scroll.

        Raises:
            RuntimeError: If browser is not launched.
            ValueError: If direction is invalid.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        delta_x = 0
        delta_y = 0

        direction = direction.lower()
        if direction == "up":
            delta_y = -amount
        elif direction == "down":
            delta_y = amount
        elif direction == "left":
            delta_x = -amount
        elif direction == "right":
            delta_x = amount
        else:
            raise ValueError(f"Invalid scroll direction: {direction}")

        logger.info(f"Scrolling {direction} by {amount}px")
        await self._page.mouse.wheel(delta_x, delta_y)
        await asyncio.sleep(0.3)

    async def wait_for_load(self, timeout: int = 5000) -> None:
        """Wait for page to be fully loaded.

        Args:
            timeout: Maximum time to wait in milliseconds.

        Raises:
            RuntimeError: If browser is not launched.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        await self._page.wait_for_load_state("networkidle", timeout=timeout)

    async def get_page_title(self) -> str:
        """Get the current page title.

        Returns:
            Current page title.

        Raises:
            RuntimeError: If browser is not launched.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        return await self._page.title()

    async def get_page_url(self) -> str:
        """Get the current page URL.

        Returns:
            Current page URL.

        Raises:
            RuntimeError: If browser is not launched.
        """
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")

        return self._page.url

    async def close(self) -> None:
        """Clean up browser resources."""
        logger.info("Closing browser...")

        if self._page:
            await self._page.close()
            self._page = None

        if self._context:
            await self._context.close()
            self._context = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("Browser closed")

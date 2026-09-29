from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from carfinder.providers.base import RunContext


class ProviderFetchError(RuntimeError):
    pass


class ProviderChallenge(ProviderFetchError):
    pass


class PlaywrightFetcher:
    """One persistent, ordinary Chromium profile for a low-frequency run."""

    def __init__(self, context: RunContext) -> None:
        self._context = context
        self._playwright = None
        self._browser_context = None
        self._last_request_at: float | None = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._context.browser_profile.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            self._browser_context = await self._playwright.chromium.launch_persistent_context(
                str(self._context.browser_profile),
                headless=self._context.headless,
                locale="sr-RS",
                viewport={"width": 1366, "height": 900},
            )
        except Exception:
            await self._playwright.stop()
            self._playwright = None
            raise

    async def get(self, url: str) -> str:
        if self._browser_context is None:
            raise RuntimeError("Provider browser has not been started")
        if self._last_request_at is not None:
            elapsed = asyncio.get_running_loop().time() - self._last_request_at
            delay = self._context.request_delay_seconds - elapsed
            if delay > 0:
                await asyncio.sleep(delay)

        last_error: Exception | None = None
        for attempt in range(2):
            elapsed = asyncio.get_running_loop().time() - self._last_request_at if self._last_request_at is not None else 0
            delay = self._context.request_delay_seconds - elapsed
            if delay > 0:
                await asyncio.sleep(delay)
            page = await self._browser_context.new_page()
            try:
                self._last_request_at = asyncio.get_running_loop().time()
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._context.timeout_seconds * 1000,
                )
                if response and response.status == 404:
                    raise ProviderFetchError(f"Provider listing returned 404: {urlsplit(url).path}")
                if response and response.status >= 400:
                    if response.status >= 500 and attempt == 0:
                        last_error = ProviderFetchError(f"Provider returned HTTP {response.status}")
                        continue
                    raise ProviderFetchError(f"Provider returned HTTP {response.status}")
                final_host = (urlsplit(page.url).hostname or "").lower()
                if final_host != "polovniautomobili.com" and not final_host.endswith(".polovniautomobili.com"):
                    raise ProviderFetchError("Provider page redirected outside PolovniAutomobili")
                title = (await page.title()).lower()
                if any(marker in title for marker in (
                    "just a moment", "checking your browser", "attention required",
                    "sacekajte trenutak", "sačekajte trenutak",
                )):
                    raise ProviderChallenge("Provider returned a verification page; no bypass was attempted")
                selector = "main h1" if "/auto-oglasi/" in urlsplit(url).path and "/pretraga" not in urlsplit(url).path else 'a[href*="/auto-oglasi/"]'
                try:
                    await page.wait_for_selector(selector, timeout=min(self._context.timeout_seconds * 1000, 5000))
                except Exception:
                    pass
                return await page.content()
            except ProviderChallenge:
                raise
            except ProviderFetchError:
                raise
            except Exception as error:
                last_error = error
                if attempt == 1:
                    break
            finally:
                await page.close()
        raise ProviderFetchError(
            f"Provider page request failed after 2 attempts ({type(last_error).__name__ if last_error else 'unknown error'})"
        ) from last_error

    async def close(self) -> None:
        if self._browser_context is not None:
            await self._browser_context.close()
            self._browser_context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

"""Browser runtime — structured DOM-first execution with Playwright.

Uses structured selectors and accessibility tree first.
Vision fallback only when page is structurally ambiguous.
"""

import asyncio
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

BROWSER_PROFILES_DIR = Path("/spool/browser_profiles")


class BrowserRuntime:
    """Manages Playwright browser with persisted profiles."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    async def launch(self, profile_name: str | None = None) -> None:
        """Launch browser with optional persisted profile."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("playwright_not_installed", msg="Browser runtime disabled")
            return

        self._playwright = await async_playwright().start()

        launch_args: dict[str, Any] = {"headless": True}
        if profile_name:
            profile_dir = BROWSER_PROFILES_DIR / profile_name
            profile_dir.mkdir(parents=True, exist_ok=True)
            self._browser = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=True,
            )
            pages = self._browser.pages
            self._page = pages[0] if pages else await self._browser.new_page()
            self._context = self._browser
        else:
            self._browser = await self._playwright.chromium.launch(**launch_args)
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()

        logger.info("browser_launched", profile=profile_name)

    async def close(self) -> None:
        """Close browser and cleanup."""
        if self._context:
            await self._context.close()
        if self._browser and not isinstance(self._context, type(self._browser)):
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("browser_closed")

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict:
        """Navigate to URL and return page state."""
        if not self._page:
            return {"error": "Browser not launched"}
        try:
            await self._page.goto(url, wait_until=wait_until, timeout=30000)
            title = await self._page.title()
            url_final = self._page.url
            return {"title": title, "url": url_final, "success": True}
        except Exception as e:
            logger.error("navigation_failed", url=url, error=str(e))
            return {"error": str(e), "success": False}

    async def search_on_page(
        self,
        query: str,
        input_selector: str = "input[type='search'], input[name='q']",
    ) -> dict:
        """Type a search query using DOM selectors first."""
        if not self._page:
            return {"error": "Browser not launched"}
        try:
            await self._page.wait_for_selector(input_selector, timeout=5000)
            await self._page.fill(input_selector, query)
            await self._page.keyboard.press("Enter")
            await self._page.wait_for_load_state("domcontentloaded")
            return {"success": True, "query": query}
        except Exception as e:
            logger.warning("search_failed", query=query, error=str(e))
            return {"success": False, "error": str(e)}

    async def extract_links(self, selector: str = "a[href]", max_results: int = 20) -> list[dict]:
        """Extract links from current page using DOM."""
        if not self._page:
            return []
        try:
            links = await self._page.eval_on_selector_all(
                selector,
                """els => els.slice(0, arguments[0] || 20).map(el => ({
                    href: el.href,
                    text: el.textContent?.trim() || '',
                    title: el.title || ''
                }))""",
            )
            return links[:max_results]
        except Exception:
            return []

    async def extract_media_info(self) -> dict:
        """Extract media/video information from current page using DOM."""
        if not self._page:
            return {}
        try:
            info = await self._page.evaluate("""() => {
                const sel = 'video, iframe[src*="youtube"], iframe[src*="vimeo"]';
                const videos = document.querySelectorAll(sel);
                const result = {
                    video_count: videos.length,
                    videos: [],
                    title: document.title,
                    meta_description:
                        document.querySelector('meta[name="description"]')?.content || '',
                    og_video: document.querySelector('meta[property="og:video"]')?.content || '',
                    og_duration:
                        document.querySelector('meta[property="video:duration"]')?.content || '',
                };
                videos.forEach(v => {
                    if (v.tagName === 'VIDEO') {
                        result.videos.push({
                            src: v.src || v.querySelector('source')?.src || '',
                            duration: v.duration || null,
                            width: v.videoWidth || null,
                            height: v.videoHeight || null,
                        });
                    } else {
                        result.videos.push({ src: v.src, type: 'iframe' });
                    }
                });
                return result;
            }""")
            return info
        except Exception as e:
            logger.warning("media_extraction_failed", error=str(e))
            return {}

    async def check_playback(self, timeout_sec: int = 10) -> dict:
        """Verify video playback works on current page."""
        if not self._page:
            return {"playback_works": False}
        try:
            video = await self._page.query_selector("video")
            if not video:
                return {"playback_works": False, "reason": "no_video_element"}

            await self._page.evaluate("""() => {
                const v = document.querySelector('video');
                if (v) { v.play().catch(() => {}); }
            }""")
            await asyncio.sleep(min(timeout_sec, 5))

            state = await self._page.evaluate("""() => {
                const v = document.querySelector('video');
                if (!v) return { playing: false };
                return {
                    playing: !v.paused && !v.ended && v.currentTime > 0,
                    currentTime: v.currentTime,
                    duration: v.duration,
                    readyState: v.readyState,
                    width: v.videoWidth,
                    height: v.videoHeight,
                };
            }""")
            return {
                "playback_works": state.get("playing", False),
                "duration_sec": int(state.get("duration", 0)) if state.get("duration") else None,
                "resolution": (
                    f"{state.get('width', 0)}x{state.get('height', 0)}"
                    if state.get("width") else None
                ),
            }
        except Exception as e:
            logger.warning("playback_check_failed", error=str(e))
            return {"playback_works": False, "error": str(e)}

    async def get_page_text(self, max_length: int = 5000) -> str:
        """Get visible text content from current page."""
        if not self._page:
            return ""
        try:
            text = await self._page.evaluate(
                "() => document.body?.innerText?.slice(0, arguments[0] || 5000) || ''"
            )
            return text[:max_length]
        except Exception:
            return ""

    async def login(
        self,
        login_url: str,
        email: str,
        password: str,
        email_selector: str = "input[type='email'], input[name='email'], input[name='username'], input[name='login']",
        pass_selector: str = "input[type='password']",
        submit_selector: str = "button[type='submit'], input[type='submit'], button.login-btn, button.submit",
        success_check: str | None = None,
    ) -> dict:
        """Login to a site and persist the session via profile.

        Returns {"success": True} if login appears to have worked.
        Uses persisted profile — on subsequent calls, already logged-in session is reused.
        """
        if not self._page:
            return {"success": False, "error": "Browser not launched"}

        # Check if already logged in by looking for a logged-in indicator
        if success_check:
            try:
                await self._page.wait_for_selector(success_check, timeout=3000)
                logger.info("login_already_active", url=login_url)
                return {"success": True, "already_logged_in": True}
            except Exception:
                pass  # Not logged in yet, proceed

        result = await self.navigate(login_url)
        if not result.get("success"):
            return {"success": False, "error": f"Could not navigate to {login_url}"}

        # Wait a moment for JS to render
        await asyncio.sleep(2)

        try:
            await self._page.wait_for_selector(email_selector, timeout=8000)
            await self._page.fill(email_selector, email)
            await asyncio.sleep(0.5)
            await self._page.fill(pass_selector, password)
            await asyncio.sleep(0.5)
            await self._page.click(submit_selector)
            await self._page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(2)

            # Verify login worked
            current_url = self._page.url
            page_text = await self.get_page_text(500)
            failed_signals = ["wrong password", "incorrect", "invalid", "login failed", "error"]
            failed = any(s in page_text.lower() for s in failed_signals)

            if failed:
                logger.warning("login_failed", url=login_url, hint=page_text[:100])
                return {"success": False, "error": "Login credentials rejected", "page": page_text[:200]}

            logger.info("login_success", url=login_url, landed_on=current_url)
            return {"success": True, "landed_on": current_url}

        except Exception as e:
            logger.error("login_error", url=login_url, error=str(e))
            return {"success": False, "error": str(e)}

    async def intercept_media_requests(self) -> list[str]:
        """Capture media/download URLs triggered during page interaction.

        Sets up a request listener, plays the video briefly, returns captured URLs.
        """
        if not self._page:
            return []

        captured: list[str] = []
        media_exts = (".mp4", ".m3u8", ".mpd", ".webm", ".flv", ".ts")
        media_keywords = ("download", "get_file", "dl=", "cdn", "media")

        def handle_request(request):
            url = request.url
            if any(url.lower().endswith(ext) for ext in media_exts):
                captured.append(url)
            elif any(kw in url.lower() for kw in media_keywords) and "video" in url.lower():
                captured.append(url)

        self._page.on("request", handle_request)

        try:
            # Trigger video load by clicking play button if present
            await self._page.evaluate("""() => {
                const playBtns = document.querySelectorAll(
                    '.play-button, .play-btn, button.play, [class*="play"], [id*="play"]'
                );
                if (playBtns.length) playBtns[0].click();
                const videos = document.querySelectorAll('video');
                videos.forEach(v => v.play().catch(() => {}));
            }""")
            await asyncio.sleep(4)
        except Exception:
            pass
        finally:
            self._page.remove_listener("request", handle_request)

        return list(set(captured))

    async def click_download_button(self) -> str | None:
        """Click the download button on a video page and return the download URL."""
        if not self._page:
            return None

        download_selectors = [
            "a.download-btn", "a[download]", "a[href*='download']",
            "button.download", ".download-link a", "a[id*='download']",
            "a[class*='download']", ".dl-btn", "a.btn-download",
        ]

        for selector in download_selectors:
            try:
                el = await self._page.query_selector(selector)
                if el:
                    href = await el.get_attribute("href")
                    if href and any(
                        href.lower().endswith(ext) for ext in (".mp4", ".webm", ".flv")
                    ):
                        return href

                    # Click and wait for navigation or new URL
                    async with self._page.expect_navigation(timeout=5000):
                        await el.click()
                    return self._page.url
            except Exception:
                continue

        return None

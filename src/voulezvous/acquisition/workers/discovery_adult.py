"""Adult platform discovery worker.

Navigates to a creator's profile on supported adult platforms,
lists their videos, extracts metadata and download URLs via Playwright.

All processing is local — no content metadata leaves the server.
Credentials are read from environment variables only.
"""

import asyncio
from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.acquisition.browser.adapters import (
    FabhuseAdapter,
    GayboyfriendtvAdapter,
    PornhubAdapter,
    XvideosAdapter,
    get_adapter_for_domain,
)
from voulezvous.acquisition.browser.runtime import BrowserRuntime
from voulezvous.acquisition.enums import (
    CandidateRightsStatus,
    DiscoveryStatus,
    RetrievalStatus,
)
from voulezvous.acquisition.models import CandidateAsset, DiscoveryRun
from voulezvous.config import settings

logger = structlog.get_logger()

PLATFORM_CONFIG = {
    "xvideos": {
        "adapter_cls": XvideosAdapter,
        "profile": "xvideos_session",
        "email_env": "xvideos_email",
        "pass_env": "xvideos_password",
        "domain": "xvideos.com",
    },
    "pornhub": {
        "adapter_cls": PornhubAdapter,
        "profile": "pornhub_session",
        "email_env": "pornhub_email",
        "pass_env": "pornhub_password",
        "domain": "pornhub.com",
    },
    "gayboyfriendtv": {
        "adapter_cls": GayboyfriendtvAdapter,
        "profile": "gayboyfriendtv_session",
        "email_env": "gayboyfriendtv_email",
        "pass_env": "gayboyfriendtv_password",
        "domain": "gayboyfriendtv.com",
    },
    "fabhuse": {
        "adapter_cls": FabhuseAdapter,
        "profile": "fabhuse_session",
        "email_env": "fabhuse_email",
        "pass_env": "fabhuse_password",
        "domain": "fabhuse.com",
    },
}


async def run_user_discovery(
    db: AsyncSession,
    platform: str,
    username: str,
    max_videos: int = 20,
    run_date: date | None = None,
) -> DiscoveryRun:
    """Scrape a creator's profile and register new candidates."""
    run_date = run_date or date.today()
    cfg = PLATFORM_CONFIG.get(platform)
    if not cfg:
        raise ValueError(f"Unknown platform: {platform}. Valid: {list(PLATFORM_CONFIG)}")

    adapter = cfg["adapter_cls"]()
    profile = cfg["profile"]
    email = getattr(settings, cfg["email_env"], "")
    password = getattr(settings, cfg["pass_env"], "")
    domain = cfg["domain"]

    candidates_found = 0
    candidates_added = 0
    errors = []

    runtime = BrowserRuntime()
    try:
        await runtime.launch(profile_name=profile)

        # Login if credentials are configured (session persisted across runs)
        if email and password:
            login_result = await runtime.login(
                login_url=adapter.LOGIN_URL,
                email=email,
                password=password,
                email_selector=adapter.LOGIN_EMAIL_SEL,
                pass_selector=adapter.LOGIN_PASS_SEL,
                submit_selector=adapter.LOGIN_SUBMIT_SEL,
                success_check=adapter.LOGIN_SUCCESS_SEL,
            )
            if not login_result.get("success") and not login_result.get("already_logged_in"):
                logger.warning(
                    "adult_login_failed",
                    platform=platform,
                    error=login_result.get("error"),
                )

        # Navigate to user profile
        profile_url = adapter.build_user_url(username)
        logger.info("adult_discovery_start", platform=platform, user=username, url=profile_url)
        await runtime.navigate(profile_url)
        await asyncio.sleep(3)

        # Extract video links from profile
        links = await runtime.extract_links(
            selector=adapter.result_selector,
            max_results=max_videos,
        )

        if not links:
            # Fallback: try generic <a> tags with video-related hrefs
            all_links = await runtime.extract_links(
                selector="a[href*='/video'], a[href*='/watch'], a[href*='/v/']",
                max_results=max_videos,
            )
            links = all_links

        logger.info("adult_discovery_links", platform=platform, count=len(links))

        for link in links[:max_videos]:
            href = link.get("href", "")
            title = link.get("text", "") or link.get("title", "") or f"{platform} video"

            if not href or len(href) < 10:
                continue

            # Skip non-video pages
            skip_patterns = [
                "/search", "/tag", "/category", "/channel", "/profile",
                "/login", "/register", "/premium", "/upload",
            ]
            if any(p in href.lower() for p in skip_patterns):
                continue

            candidates_found += 1

            # Navigate to video page to get full metadata + download URL
            await runtime.navigate(href)
            await asyncio.sleep(2)

            media_info = await runtime.extract_media_info()
            duration_sec = None
            if media_info.get("og_duration"):
                try:
                    duration_sec = int(media_info["og_duration"])
                except ValueError:
                    pass
            if not duration_sec and media_info.get("videos"):
                for v in media_info["videos"]:
                    if v.get("duration"):
                        try:
                            duration_sec = int(float(v["duration"]))
                            break
                        except (ValueError, TypeError):
                            pass

            # Full page title is more reliable than link text
            page_title = media_info.get("title") or title
            # Sanitise: strip site suffix (e.g. "Video title - XVIDEOS.COM")
            for suffix in [" - XVIDEOS.COM", " - Pornhub.com", " | xvideos.com"]:
                page_title = page_title.replace(suffix, "").strip()

            # Try to get download URL via button click or media interception
            intercepted = await runtime.intercept_media_requests()
            download_url: str | None = None

            if intercepted:
                # Prefer .mp4 over .m3u8
                mp4s = [u for u in intercepted if u.endswith(".mp4")]
                download_url = mp4s[0] if mp4s else intercepted[0]
            else:
                download_url = await runtime.click_download_button()

            page_info = {
                "has_download_button": bool(download_url),
                "intercepted_media": bool(intercepted),
            }
            authorized, retrieval_type = adapter.classify_retrieval(download_url, page_info)

            # Build candidate
            candidate = CandidateAsset(
                title=page_title[:500] if page_title else f"{platform} — {username}",
                source_url=href,
                page_url=href,
                duration_sec=duration_sec,
                retrieval_status=(
                    RetrievalStatus.authorized_direct
                    if authorized
                    else RetrievalStatus.requires_verification
                ),
                rights_status=CandidateRightsStatus.pending_review,
                discovery_status=DiscoveryStatus.found,
                tags=[platform, username, "adult"],
                extra_metadata={
                    "platform": platform,
                    "creator": username,
                    "download_url": download_url,
                    "retrieval_type": retrieval_type,
                    "intercepted_urls": intercepted[:5],
                    "og_description": media_info.get("meta_description", "")[:500],
                },
            )
            db.add(candidate)
            candidates_added += 1
            logger.info(
                "adult_candidate_added",
                title=page_title[:60],
                duration=duration_sec,
                authorized=authorized,
            )

        await db.commit()

    except Exception as e:
        logger.error("adult_discovery_error", platform=platform, error=str(e))
        errors.append(str(e))
    finally:
        await runtime.close()

    discovery_run = DiscoveryRun(
        run_date=run_date,
        status="completed" if not errors else "partial",
        output_summary={
            "platform": platform,
            "creator": username,
            "total_found": candidates_found,
            "total_added": candidates_added,
            "errors": errors,
        },
    )
    db.add(discovery_run)
    await db.commit()

    logger.info(
        "adult_discovery_complete",
        platform=platform,
        user=username,
        found=candidates_found,
        added=candidates_added,
    )
    return discovery_run

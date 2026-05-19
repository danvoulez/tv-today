"""Discovery API — trigger and view discovery runs."""

import structlog
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.acquisition.models import DiscoveryRun
from voulezvous.acquisition.schemas import DiscoveryRunOut
from voulezvous.acquisition.workers.discovery import run_discovery, run_discovery_simulated
from voulezvous.acquisition.workers.discovery_adult import run_user_discovery
from voulezvous.config import settings
from voulezvous.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/run", response_model=DiscoveryRunOut, status_code=201)
async def trigger_discovery(
    simulated: bool = Query(False, description="Use simulated discovery (no browser, for testing)"),
    db: AsyncSession = Depends(get_db),
):
    if simulated:
        run = await run_discovery_simulated(db, run_date=date.today())
    else:
        try:
            run = await run_discovery(db, run_date=date.today())
        except Exception as e:
            logger.warning("real_discovery_failed_falling_back", error=str(e))
            run = await run_discovery_simulated(db, run_date=date.today())
    return run


@router.get("/runs", response_model=list[DiscoveryRunOut])
async def list_discovery_runs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiscoveryRun).order_by(DiscoveryRun.created_at.desc()).limit(20)
    )
    return result.scalars().all()


# ── Adult platform endpoints ──────────────────────────────────────────────────

class PlatformLoginRequest(BaseModel):
    platform: Literal["xvideos", "pornhub", "gayboyfriendtv", "fabhuse"]


class PlatformLoginResponse(BaseModel):
    platform: str
    success: bool
    message: str


@router.post("/login", response_model=PlatformLoginResponse, tags=["adult"])
async def platform_login(req: PlatformLoginRequest):
    """Login to an adult platform and persist the session.

    Call once per platform. Session is saved to /spool/browser_profiles/{platform}_session
    and reused on all subsequent discovery runs. Credentials are read from .env
    """
    from voulezvous.acquisition.browser.adapters import (
        XvideosAdapter, PornhubAdapter, GayboyfriendtvAdapter, FabhuseAdapter,
    )
    from voulezvous.acquisition.browser.runtime import BrowserRuntime

    platform_map = {
        "xvideos": (
            XvideosAdapter(),
            settings.xvideos_email, settings.xvideos_password,
            "xvideos_session",
        ),
        "pornhub": (
            PornhubAdapter(),
            settings.pornhub_email, settings.pornhub_password,
            "pornhub_session",
        ),
        "gayboyfriendtv": (
            GayboyfriendtvAdapter(),
            settings.gayboyfriendtv_email, settings.gayboyfriendtv_password,
            "gayboyfriendtv_session",
        ),
        "fabhuse": (
            FabhuseAdapter(),
            settings.fabhuse_email, settings.fabhuse_password,
            "fabhuse_session",
        ),
    }

    adapter, email, password, profile = platform_map[req.platform]

    if not email or not password:
        raise HTTPException(
            status_code=400,
            detail=f"Credentials for {req.platform} not set in .env "
                   f"({req.platform.upper()}_EMAIL / {req.platform.upper()}_PASSWORD)",
        )

    runtime = BrowserRuntime()
    try:
        await runtime.launch(profile_name=profile)
        result = await runtime.login(
            login_url=adapter.LOGIN_URL,
            email=email,
            password=password,
            email_selector=adapter.LOGIN_EMAIL_SEL,
            pass_selector=adapter.LOGIN_PASS_SEL,
            submit_selector=adapter.LOGIN_SUBMIT_SEL,
            success_check=adapter.LOGIN_SUCCESS_SEL,
        )
    finally:
        await runtime.close()

    if result.get("success"):
        return PlatformLoginResponse(
            platform=req.platform,
            success=True,
            message=f"Logged in to {req.platform}. Session saved to {profile}.",
        )
    else:
        raise HTTPException(
            status_code=401,
            detail=f"Login failed for {req.platform}: {result.get('error', 'unknown')}",
        )


@router.post("/run-user", response_model=DiscoveryRunOut, status_code=201, tags=["adult"])
async def trigger_user_discovery(
    platform: str = Query(..., description="xvideos | pornhub | gayboyfriendtv | fabhuse"),
    username: str = Query(default="", description="Creator username to scrape (empty = use ADULT_FOLLOW_USER from .env)"),
    max_videos: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Scrape videos from a specific creator/user on an adult platform."""
    target_user = username or settings.adult_follow_user
    if not target_user:
        raise HTTPException(status_code=400, detail="Provide username or set ADULT_FOLLOW_USER in .env")

    run = await run_user_discovery(
        db,
        platform=platform,
        username=target_user,
        max_videos=max_videos,
        run_date=date.today(),
    )
    return run

"""Discovery API — trigger and view discovery runs."""

import structlog
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.acquisition.browser.adapters import get_adapter_for_domain
from voulezvous.acquisition.browser.runtime import BrowserRuntime
from voulezvous.acquisition.models import DiscoveryRun, DomainPolicy
from voulezvous.acquisition.schemas import DiscoveryRunOut
from voulezvous.acquisition.workers.discovery import run_discovery, run_discovery_simulated
from voulezvous.acquisition.workers.discovery_adult import run_user_discovery
from voulezvous.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/discovery", tags=["discovery"])

# existing endpoints omitted for brevity
@router.post('/run', response_model=DiscoveryRunOut, status_code=201)
async def trigger_discovery(simulated: bool = Query(False), db: AsyncSession = Depends(get_db)):
    return await (run_discovery_simulated(db, run_date=date.today()) if simulated else run_discovery(db, run_date=date.today()))

@router.get('/runs', response_model=list[DiscoveryRunOut])
async def list_discovery_runs(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(DiscoveryRun).order_by(DiscoveryRun.created_at.desc()).limit(20))).scalars().all()

class PlatformLoginRequest(BaseModel):
    domain: str

class PlatformLoginResponse(BaseModel):
    domain: str
    success: bool
    message: str

@router.post('/login', response_model=PlatformLoginResponse, tags=['adult'])
async def platform_login(req: PlatformLoginRequest, db: AsyncSession = Depends(get_db)):
    policy = (await db.execute(select(DomainPolicy).where(DomainPolicy.domain == req.domain, DomainPolicy.is_enabled.is_(True)))).scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail='domain not found')
    if not policy.requires_login:
        return PlatformLoginResponse(domain=req.domain, success=True, message='login not required')
    if not policy.credential_email or not policy.credential_password:
        raise HTTPException(status_code=400, detail='credentials missing for domain')
    adapter = await get_adapter_for_domain(req.domain, db)
    runtime = BrowserRuntime()
    try:
        await runtime.launch(profile_name=f"{req.domain.replace('.', '_')}_session")
        result = await runtime.login(login_url=adapter.login_url, email=policy.credential_email, password=policy.credential_password, email_selector=adapter.login_email_selector, pass_selector=adapter.login_password_selector, submit_selector=adapter.login_submit_selector, success_check=adapter.login_success_selector)
    finally:
        await runtime.close()
    if not result.get('success') and not result.get('already_logged_in'):
        raise HTTPException(status_code=401, detail=f"Login failed: {result.get('error', 'unknown')}")
    return PlatformLoginResponse(domain=req.domain, success=True, message='session saved')

@router.post('/run-user', response_model=DiscoveryRunOut, status_code=201, tags=['adult'])
async def trigger_user_discovery(domain: str = Query(...), username: str = Query(...), max_videos: int = Query(default=20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    return await run_user_discovery(db, domain=domain, username=username, max_videos=max_videos, run_date=date.today())

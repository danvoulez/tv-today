from datetime import date, datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voulezvous.acquisition.models import CandidateAsset, DomainPolicy, SearchKeyword
from voulezvous.acquisition.workers.discovery import run_discovery
from voulezvous.acquisition.workers.discovery_adult import run_user_discovery
from voulezvous.models.enums import RightsStatus
from voulezvous.models.tables import LibraryAsset, StreamControl
from voulezvous.services.stream_control import get_or_create_stream_control
from voulezvous.services.planner import generate_plan
from voulezvous.services.cleanup import cleanup_orphan_downloads

class ToolError(Exception): ...

async def tool_generate_plan(db: AsyncSession, hours: int = 24) -> dict:
    p = await generate_plan(db, date.today(), hours, True); return {"plan_id": str(p.id)}
async def tool_run_discovery(db: AsyncSession) -> dict:
    r = await run_discovery(db, date.today()); return {"run_id": str(r.id), "summary": r.output_summary}
async def tool_run_user_discovery(db: AsyncSession, domain: str, username: str, max_videos: int = 20) -> dict:
    r = await run_user_discovery(db, domain=domain, username=username, max_videos=max_videos, run_date=date.today()); return {"run_id": str(r.id)}
async def tool_promote_candidate(db: AsyncSession, candidate_id: UUID) -> dict:
    c=(await db.execute(select(CandidateAsset).where(CandidateAsset.id==candidate_id))).scalar_one_or_none();
    if not c: raise ToolError('candidate not found'); c.rights_status='approved_for_stream'; await db.commit(); return {"candidate_id":str(c.id)}
async def tool_block_candidate(db: AsyncSession, candidate_id: UUID, reason: str) -> dict: return {"ok": True}
async def tool_block_asset(db: AsyncSession, asset_id: UUID, reason: str) -> dict:
    a=await db.get(LibraryAsset, asset_id); 
    if not a: raise ToolError('asset not found'); a.rights_status=RightsStatus.blocked; a.approval_notes=reason; await db.commit(); return {"asset_id":str(asset_id)}
async def tool_add_keyword(db: AsyncSession, text: str, weight: float, category: str, include: bool) -> dict:
    k=SearchKeyword(keyword=text, weight=weight, category=category, include=include, active=True); db.add(k); await db.commit(); return {"keyword_id":str(k.id)}
async def tool_pause_keyword(db: AsyncSession, keyword_id: UUID) -> dict: return {"ok": True}
async def tool_boost_keyword(db: AsyncSession, keyword_id: UUID, factor: float) -> dict: return {"ok": True}
async def tool_add_domain(db: AsyncSession, payload: dict) -> dict: p=DomainPolicy(**payload); db.add(p); await db.commit(); return {"domain_id":str(p.id)}
async def tool_update_domain(db: AsyncSession, domain_id: UUID, patch: dict) -> dict: return {"ok": True}
async def tool_disable_domain(db: AsyncSession, domain_id: UUID) -> dict: return {"ok": True}
async def tool_start_stream(db: AsyncSession) -> dict:
    sc = await get_or_create_stream_control(db)
    sc.desired_running = True
    sc.status = 'running'
    sc.heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}
async def tool_narrate(db: AsyncSession, run_id: UUID, text: str) -> dict: return {"ok":True}
async def tool_restart_streamer(db: AsyncSession, reason: str) -> dict:
    sc = await get_or_create_stream_control(db)
    sc.desired_running = False
    sc.status = 'restart_requested'
    sc.heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    sc.desired_running = True
    sc.status = 'running'
    sc.heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "reason": reason}

async def tool_run_cleanup(db: AsyncSession) -> dict:
    return await cleanup_orphan_downloads(db)
TOOLS={"generate_plan":tool_generate_plan,"run_discovery":tool_run_discovery,"run_user_discovery":tool_run_user_discovery,"promote_candidate":tool_promote_candidate,"block_candidate":tool_block_candidate,"block_asset":tool_block_asset,"add_keyword":tool_add_keyword,"pause_keyword":tool_pause_keyword,"boost_keyword":tool_boost_keyword,"add_domain":tool_add_domain,"update_domain":tool_update_domain,"disable_domain":tool_disable_domain,"start_stream":tool_start_stream,"narrate":tool_narrate,"restart_streamer":tool_restart_streamer,"run_cleanup":tool_run_cleanup}

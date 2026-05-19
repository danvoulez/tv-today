from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from voulezvous.models.enums import RightsStatus, PlanStatus
from voulezvous.models.tables import DirectorAction, DirectorRun, LibraryAsset, StreamControl, StreamPlan, StreamPlanItem
from voulezvous.acquisition.models import CandidateAsset, DiscoveryRun, DomainPolicy, SearchKeyword

async def compact_state(db: AsyncSession) -> dict:
    sc = (await db.execute(select(StreamControl).where(StreamControl.key=='main'))).scalar_one_or_none()
    approved=(await db.execute(select(func.count()).select_from(LibraryAsset).where(LibraryAsset.rights_status==RightsStatus.approved_for_stream))).scalar() or 0
    pending=(await db.execute(select(func.count()).select_from(LibraryAsset).where(LibraryAsset.rights_status==RightsStatus.pending_review))).scalar() or 0
    blocked=(await db.execute(select(func.count()).select_from(LibraryAsset).where(LibraryAsset.rights_status==RightsStatus.blocked))).scalar() or 0
    avg=(await db.execute(select(func.avg(LibraryAsset.health_score)))).scalar() or 0
    appr_unprom=(await db.execute(select(func.count()).select_from(CandidateAsset).where(CandidateAsset.rights_status=='approved_for_stream', CandidateAsset.library_asset_id.is_(None)))).scalar() or 0
    dlast=(await db.execute(select(DiscoveryRun).order_by(DiscoveryRun.created_at.desc()).limit(1))).scalar_one_or_none()
    sites=(await db.execute(select(DomainPolicy).order_by(DomainPolicy.domain))).scalars().all()
    kws=(await db.execute(select(SearchKeyword).where(SearchKeyword.active.is_(True)).limit(25))).scalars().all()
    actions=(await db.execute(select(DirectorAction).order_by(DirectorAction.created_at.desc()).limit(10))).scalars().all()
    queued=(await db.execute(select(func.coalesce(func.sum(StreamPlanItem.target_duration_sec),0)).join(StreamPlan, StreamPlanItem.stream_plan_id==StreamPlan.id).where(StreamPlan.status.in_([PlanStatus.preparing,PlanStatus.ready,PlanStatus.streaming])))).scalar() or 0
    return {"now": datetime.now(timezone.utc).isoformat(), "stream":{"running": bool(sc and sc.desired_running), "status": sc.status if sc else 'off', "current_item_title": None, "queued_hours": round(float(queued)/3600,2)}, "library":{"videos_approved":approved,"videos_pending":pending,"videos_blocked":blocked,"avg_health_score":float(avg or 0)}, "candidates":{"approved_unpromoted":appr_unprom,"pending_review":0}, "discovery":{"last_run_at": dlast.created_at.isoformat() if dlast else None, "last_run_found": (dlast.output_summary or {}).get('total_found',0) if dlast else 0}, "sites":[{"domain":s.domain,"enabled":s.is_enabled,"is_adult":s.is_adult,"has_session":bool(s.session_profile_name)} for s in sites], "keywords":[{"id":str(k.id),"text":k.keyword,"weight":float(k.weight),"include":k.include,"active":k.active,"recent_hits":0} for k in kws], "last_actions":[{"verb":a.verb,"why":a.why,"status":a.status,"at":a.created_at.isoformat()} for a in actions]}

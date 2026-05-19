from datetime import datetime, timezone
import shutil

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.config import settings
from voulezvous.database import get_db
from voulezvous.models.enums import PlanStatus, PrepStatus
from voulezvous.models.tables import (
    DirectorRun,
    LibraryAsset,
    StreamControl,
    StreamPlan,
    StreamPlanItem,
)
from voulezvous.services.director_state import compact_state

router = APIRouter(prefix='/obs', tags=['observability'])


async def _is_ollama_reachable() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(f"{settings.local_llm_url.rstrip('/')}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def _is_tunnel_reachable() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get('https://tv.logline.world/health')
            return resp.status_code < 500
    except Exception:
        return False


@router.get('/snapshot')
async def snapshot(db: AsyncSession = Depends(get_db)):
    st = await compact_state(db)

    stream_control = await db.get(StreamControl, 'main')

    active_plan = (
        await db.execute(
            select(StreamPlan)
            .where(StreamPlan.status.in_([PlanStatus.preparing, PlanStatus.ready, PlanStatus.streaming]))
            .order_by(StreamPlan.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    current_item = {'title': st['stream']['current_item_title'], 'started_at': None, 'duration_sec': None}
    if stream_control and stream_control.current_item_id:
        row = (
            await db.execute(
                select(StreamPlanItem, LibraryAsset)
                .join(LibraryAsset, StreamPlanItem.video_asset_id == LibraryAsset.id)
                .where(StreamPlanItem.id == stream_control.current_item_id)
                .limit(1)
            )
        ).first()
        if row:
            item, asset = row
            current_item = {
                'title': asset.title,
                'started_at': item.actual_start_at.isoformat() if item.actual_start_at else None,
                'duration_sec': item.target_duration_sec,
            }

    next_items = []
    plan_items_ready = 0
    plan_items_queued = 0
    if active_plan:
        items = (
            await db.execute(
                select(StreamPlanItem, LibraryAsset)
                .join(LibraryAsset, StreamPlanItem.video_asset_id == LibraryAsset.id)
                .where(StreamPlanItem.stream_plan_id == active_plan.id)
                .order_by(StreamPlanItem.sequence_index)
                .limit(5)
            )
        ).all()
        next_items = [
            {
                'title': asset.title,
                'prep_status': item.prep_status.value if hasattr(item.prep_status, 'value') else str(item.prep_status),
            }
            for item, asset in items
        ]
        plan_items_ready = (
            await db.execute(
                select(func.count()).select_from(StreamPlanItem).where(
                    StreamPlanItem.stream_plan_id == active_plan.id,
                    StreamPlanItem.prep_status == PrepStatus.ready,
                )
            )
        ).scalar() or 0
        plan_items_queued = (
            await db.execute(
                select(func.count()).select_from(StreamPlanItem).where(
                    StreamPlanItem.stream_plan_id == active_plan.id,
                    StreamPlanItem.prep_status == PrepStatus.queued,
                )
            )
        ).scalar() or 0

    last_director_run = (
        await db.execute(select(DirectorRun).order_by(DirectorRun.started_at.desc()).limit(1))
    ).scalar_one_or_none()

    disk = shutil.disk_usage(settings.spool_root)
    storage_total_gb = round(disk.total / (1024**3), 2)
    storage_used_gb = round((disk.total - disk.free) / (1024**3), 2)

    ollama_reachable = await _is_ollama_reachable()
    tunnel_reachable = await _is_tunnel_reachable()

    return {
        'signal': {
            'status': st['stream']['status'],
            'running': st['stream']['running'],
            'current_item': current_item,
            'next_5': next_items,
            'heartbeat_at': stream_control.heartbeat_at.isoformat() if stream_control and stream_control.heartbeat_at else None,
        },
        'pipeline': {
            'queued_hours': st['stream']['queued_hours'],
            'storage_used_gb': storage_used_gb,
            'storage_total_gb': storage_total_gb,
            'plan_id': str(active_plan.id) if active_plan else None,
            'plan_status': active_plan.status.value if active_plan else None,
            'plan_items_ready': plan_items_ready,
            'plan_items_queued': plan_items_queued,
        },
        'director': {
            'last_run_at': last_director_run.started_at.isoformat() if last_director_run else None,
            'next_run_eta_sec': 300,
            'recent_actions': st['last_actions'][:30],
        },
        'health': {
            'containers': {'api': 'up', 'db': 'up', 'prep-worker': 'up', 'streamer': 'up', 'director': 'up'},
            'ollama_reachable': ollama_reachable,
            'tunnel_reachable': tunnel_reachable,
            'last_discovery_at': st['discovery']['last_run_at'],
            'generated_at': datetime.now(timezone.utc).isoformat(),
        },
    }

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from voulezvous.config import settings
from voulezvous.database import async_session
from voulezvous.models.enums import (
    EventType,
    PlanStatus,
    PrepStatus,
    StreamItemStatus,
)
from voulezvous.models.tables import LibraryAsset, StreamEvent, StreamPlan, StreamPlanItem
from voulezvous.services.ffmpeg import stream_to_target
from voulezvous.services.stream_control import (
    get_or_create_stream_control,
    stream_should_run,
    update_stream_runtime,
)

logger = structlog.get_logger()


class StreamerState:
    """Local process observation only.

    Cross-container desired state lives in stream_control, not in this object.
    """

    def __init__(self) -> None:
        self.running: bool = False
        self.current_item_id: uuid.UUID | None = None


streamer_state = StreamerState()


async def run_streamer() -> None:
    """Long-running streamer worker.

    The process stays alive and follows the database-backed desired state. This
    makes API /stream/start and /stream/stop visible across Docker containers.
    """
    logger.info("streamer_worker_started", target=settings.stream_target)

    async with async_session() as db:
        await get_or_create_stream_control(db)

    while True:
        async with async_session() as db:
            should_run = await stream_should_run(db)
            if not should_run:
                streamer_state.running = False
                streamer_state.current_item_id = None
                await update_stream_runtime(db, status="idle", current_item_id=None)
                await asyncio.sleep(2)
                continue

            if not streamer_state.running:
                streamer_state.running = True
                await update_stream_runtime(db, status="running", current_item_id=None)
                await _log_event(db, EventType.stream_started)
                logger.info("streamer_started", target=settings.stream_target)

            item = await _claim_next_ready_item(db)
            if item is None:
                await update_stream_runtime(db, status="fallback", current_item_id=None)
                await _play_fallback(db)
                await asyncio.sleep(5)
                continue

            streamer_state.current_item_id = item.id
            await update_stream_runtime(db, status="streaming", current_item_id=item.id)
            await _play_item(db, item)
            streamer_state.current_item_id = None


async def _claim_next_ready_item(db: AsyncSession) -> StreamPlanItem | None:
    """Atomically claim the next item for this streamer process.

    Postgres honors SKIP LOCKED. SQLite ignores row locking in tests, but the
    production path no longer relies on select-then-update without a lock.
    """
    q = (
        select(StreamPlanItem)
        .join(StreamPlan)
        .where(StreamPlan.status.in_([PlanStatus.preparing, PlanStatus.ready, PlanStatus.streaming]))
        .where(StreamPlanItem.prep_status == PrepStatus.ready)
        .where(StreamPlanItem.stream_status == StreamItemStatus.queued)
        .options(selectinload(StreamPlanItem.video_asset))
        .order_by(StreamPlanItem.planned_start_at, StreamPlanItem.sequence_index)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    result = await db.execute(q)
    item = result.scalar_one_or_none()
    if item is None:
        return None

    item.stream_status = StreamItemStatus.streaming
    item.actual_start_at = datetime.now(timezone.utc)
    plan = await db.get(StreamPlan, item.stream_plan_id)
    if plan and plan.status in (PlanStatus.preparing, PlanStatus.ready):
        plan.status = PlanStatus.streaming
    await db.commit()
    await _log_event(db, EventType.item_started, plan_item_id=item.id, asset_id=item.video_asset_id)
    return item


async def _next_ready_item(db: AsyncSession) -> StreamPlanItem | None:
    """Backward-compatible alias for older tests/imports."""
    return await _claim_next_ready_item(db)


async def _play_item(db: AsyncSession, item: StreamPlanItem) -> None:
    prepared_path = Path(item.prepared_file_path) if item.prepared_file_path else None
    if not prepared_path or not prepared_path.exists():
        logger.warning("prepared_file_missing", item_id=str(item.id))
        item.stream_status = StreamItemStatus.skipped
        item.error_log = "Prepared file missing"
        item.actual_end_at = datetime.now(timezone.utc)
        await db.commit()
        await _log_event(db, EventType.item_failed, plan_item_id=item.id)
        await _record_play(db, item, status="skipped", error="Prepared file missing")
        return

    started_at = datetime.now(timezone.utc)
    try:
        rc, stderr = await stream_to_target(prepared_path, settings.stream_target)
        if rc != 0:
            raise RuntimeError(f"Stream failed rc={rc}: {stderr[-300:]}")

        item.stream_status = StreamItemStatus.completed
        item.actual_end_at = datetime.now(timezone.utc)
        await db.commit()
        await _log_event(
            db, EventType.item_completed, plan_item_id=item.id, asset_id=item.video_asset_id
        )

        actual_sec = int((item.actual_end_at - started_at).total_seconds())
        await _record_play(db, item, status="ok", actual_sec=actual_sec)

        if item.delete_after_stream:
            await _cleanup_item(db, item)

    except Exception as e:
        logger.error("stream_item_error", item_id=str(item.id), error=str(e))
        item.stream_status = StreamItemStatus.failed
        item.error_log = str(e)
        item.actual_end_at = datetime.now(timezone.utc)
        await db.commit()
        await _log_event(db, EventType.item_failed, plan_item_id=item.id)
        actual_sec = int((item.actual_end_at - started_at).total_seconds())
        await _record_play(db, item, status="failed", actual_sec=actual_sec, error=str(e))


async def _record_play(
    db: AsyncSession,
    item: StreamPlanItem,
    status: str,
    actual_sec: int = 0,
    error: str | None = None,
) -> None:
    """Atualiza a ficha do asset com o resultado deste play."""
    video = await db.get(LibraryAsset, item.video_asset_id)
    if not video:
        return

    planned_sec = item.target_duration_sec or 0
    now = datetime.now(timezone.utc)

    # Determina se completou satisfatoriamente (>80% da duração planejada)
    completed_ok = status == "ok" and (
        planned_sec == 0 or actual_sec >= planned_sec * 0.8
    )

    # Entrada no play_log
    entry: dict = {
        "played_at": now.isoformat(),
        "status": status,
        "planned_sec": planned_sec,
        "actual_sec": actual_sec,
        # Ghost: viewer_count não disponível sem integração RTMP analytics
    }
    if error:
        entry["error"] = error[:300]

    # Acumula — JSONB é imutável, precisa construir nova lista
    current_log: list = list(video.play_log) if isinstance(video.play_log, list) else []
    current_log.append(entry)

    # Recalcula health_score: proporção de plays "ok" nos últimos 20
    window = current_log[-20:]
    ok_count = sum(1 for e in window if e.get("status") == "ok")
    new_health = round(ok_count / len(window), 3)

    video.times_streamed += 1
    video.last_streamed_at = now
    video.last_play_status = status
    video.error_count = video.error_count + (1 if status in ("failed", "skipped") else 0)
    video.health_score = new_health
    video.play_log = current_log

    await db.commit()
    logger.info(
        "asset_ficha_updated",
        asset_id=str(video.id),
        status=status,
        health_score=new_health,
        times_streamed=video.times_streamed,
    )


async def _play_fallback(db: AsyncSession) -> None:
    fb = settings.fallback_video_path
    if not fb.exists():
        logger.warning("fallback_missing", path=str(fb))
        await asyncio.sleep(10)
        return

    await _log_event(db, EventType.fallback_started)
    logger.info("playing_fallback", path=str(fb))
    await stream_to_target(fb, settings.stream_target)
    await _log_event(db, EventType.fallback_stopped)


async def _cleanup_item(db: AsyncSession, item: StreamPlanItem) -> None:
    paths_to_delete: list[Path] = []
    if item.prepared_file_path:
        paths_to_delete.append(Path(item.prepared_file_path))

    for p in paths_to_delete:
        try:
            if p.exists():
                p.unlink()
                logger.info("cleanup_deleted", path=str(p))
                await _log_event(
                    db,
                    EventType.cleanup_deleted,
                    plan_item_id=item.id,
                    asset_id=item.video_asset_id,
                )
        except Exception as e:
            logger.error("cleanup_failed", path=str(p), error=str(e))
            await _log_event(
                db,
                EventType.cleanup_failed,
                plan_item_id=item.id,
                asset_id=item.video_asset_id,
                payload={"error": str(e)},
            )

    await _cleanup_download_if_unreferenced(db, item)


async def _cleanup_download_if_unreferenced(db: AsyncSession, item: StreamPlanItem) -> None:
    """Delete downloaded source bytes when no queued/ready/streaming item still needs them."""
    asset = await db.get(LibraryAsset, item.video_asset_id)
    if not asset or not asset.current_local_path:
        return

    p = Path(asset.current_local_path)
    try:
        p.relative_to(settings.spool_downloads)
    except ValueError:
        logger.info("cleanup_download_skip_outside_spool", path=str(p))
        return

    active_count = (await db.execute(
        select(func.count(StreamPlanItem.id)).where(
            StreamPlanItem.id != item.id,
            StreamPlanItem.video_asset_id == item.video_asset_id,
            StreamPlanItem.stream_status.in_([
                StreamItemStatus.queued,
                StreamItemStatus.streaming,
            ]),
            StreamPlanItem.prep_status.in_([
                PrepStatus.queued,
                PrepStatus.preparing,
                PrepStatus.ready,
            ]),
        )
    )).scalar_one()

    if active_count:
        return

    try:
        if p.exists():
            p.unlink()
            logger.info("cleanup_download_deleted", path=str(p), asset_id=str(asset.id))
            await _log_event(
                db,
                EventType.cleanup_deleted,
                plan_item_id=item.id,
                asset_id=item.video_asset_id,
                payload={"path": str(p), "kind": "download"},
            )
        asset.current_local_path = None
        asset.current_local_size_bytes = None
        asset.checksum = None
        await db.commit()
    except Exception as e:
        logger.error("cleanup_download_failed", path=str(p), error=str(e))
        await _log_event(
            db,
            EventType.cleanup_failed,
            plan_item_id=item.id,
            asset_id=item.video_asset_id,
            payload={"error": str(e), "path": str(p), "kind": "download"},
        )


async def _log_event(
    db: AsyncSession,
    event_type: EventType,
    plan_id: uuid.UUID | None = None,
    plan_item_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    payload: dict | None = None,
) -> None:
    ev = StreamEvent(
        event_type=event_type,
        plan_id=plan_id,
        plan_item_id=plan_item_id,
        asset_id=asset_id,
        occurred_at=datetime.now(timezone.utc),
        payload=payload or {},
    )
    db.add(ev)
    await db.commit()

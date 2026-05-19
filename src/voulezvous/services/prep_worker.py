import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from voulezvous.config import settings
from voulezvous.models.enums import (
    AssetStatus,
    JobStatus,
    JobType,
    PlanStatus,
    PrepStatus,
    RightsStatus,
)
from voulezvous.models.tables import LibraryAsset, PrepJob, StreamPlan, StreamPlanItem
from voulezvous.services.ffmpeg import mix_audio, normalize_video

logger = structlog.get_logger()

DOWNLOAD_CHUNK_SIZE = 1024 * 1024


async def run_prep_cycle(db: AsyncSession) -> int:
    settings.ensure_spool_dirs()

    processed = 0
    touched_plan_ids = set()

    while True:
        item = await _claim_next_prep_item(db)
        if item is None:
            break
        touched_plan_ids.add(item.stream_plan_id)
        try:
            await prepare_item(db, item)
            processed += 1
        except Exception as e:
            logger.error("prep_item_failed", item_id=str(item.id), error=str(e))
            item.prep_status = PrepStatus.failed
            item.error_log = str(e)
            await db.commit()

    for plan_id in touched_plan_ids:
        q_check = select(StreamPlanItem).where(StreamPlanItem.stream_plan_id == plan_id)
        result = await db.execute(q_check)
        all_items = list(result.scalars().all())
        if all_items and all(i.prep_status == PrepStatus.ready for i in all_items):
            await db.execute(
                update(StreamPlan).where(StreamPlan.id == plan_id).values(status=PlanStatus.ready)
            )
            await db.commit()

    return processed


async def _claim_next_prep_item(db: AsyncSession) -> StreamPlanItem | None:
    """Atomically claim one queued prep item for this worker.

    Postgres honors SKIP LOCKED so parallel workers do not prepare the same row.
    SQLite ignores the lock during tests, but the production query is lock-aware.
    """
    q = (
        select(StreamPlanItem)
        .join(StreamPlan)
        .where(StreamPlan.status.in_([PlanStatus.approved, PlanStatus.preparing]))
        .where(StreamPlanItem.prep_status == PrepStatus.queued)
        .options(
            selectinload(StreamPlanItem.video_asset),
            selectinload(StreamPlanItem.music_asset),
        )
        .order_by(StreamPlanItem.sequence_index)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    result = await db.execute(q)
    item = result.scalar_one_or_none()
    if item is None:
        return None

    item.prep_status = PrepStatus.preparing
    plan = await db.get(StreamPlan, item.stream_plan_id)
    if plan and plan.status == PlanStatus.approved:
        plan.status = PlanStatus.preparing
    await db.commit()

    result = await db.execute(
        select(StreamPlanItem)
        .where(StreamPlanItem.id == item.id)
        .options(
            selectinload(StreamPlanItem.video_asset),
            selectinload(StreamPlanItem.music_asset),
        )
    )
    return result.scalar_one()


async def prepare_item(db: AsyncSession, item: StreamPlanItem) -> None:
    video_asset = item.video_asset
    if not video_asset:
        raise ValueError("No video asset linked")

    if video_asset.rights_status != RightsStatus.approved_for_stream:
        raise ValueError(
            f"Asset {video_asset.id} rights_status={video_asset.rights_status}, "
            "must be approved_for_stream"
        )

    item.prep_status = PrepStatus.preparing
    await db.commit()

    download_path = await _download_asset(db, video_asset)

    normalized_path = settings.spool_prepared / f"{item.id}_norm.mp4"
    job_norm = PrepJob(
        plan_item_id=item.id, job_type=JobType.normalize, status=JobStatus.running,
        started_at=datetime.now(timezone.utc),
    )
    db.add(job_norm)
    await db.flush()

    try:
        await normalize_video(download_path, normalized_path)
        job_norm.status = JobStatus.done
        job_norm.finished_at = datetime.now(timezone.utc)
    except Exception as e:
        job_norm.status = JobStatus.error
        job_norm.error_message = str(e)
        job_norm.finished_at = datetime.now(timezone.utc)
        await db.commit()
        raise

    final_path = normalized_path
    if item.mix_enabled and item.music_asset:
        music_asset = item.music_asset
        if music_asset.rights_status != RightsStatus.approved_for_stream:
            raise ValueError(
                f"Music asset {music_asset.id} rights_status={music_asset.rights_status}"
            )
        music_path = await _download_asset(db, music_asset)
        mixed_path = settings.spool_prepared / f"{item.id}_mixed.mp4"

        job_mix = PrepJob(
            plan_item_id=item.id, job_type=JobType.mix, status=JobStatus.running,
            started_at=datetime.now(timezone.utc),
        )
        db.add(job_mix)
        await db.flush()

        try:
            await mix_audio(
                normalized_path, music_path, mixed_path,
                float(item.video_audio_gain), float(item.music_audio_gain),
            )
            job_mix.status = JobStatus.done
            job_mix.finished_at = datetime.now(timezone.utc)
            final_path = mixed_path
        except Exception as e:
            job_mix.status = JobStatus.error
            job_mix.error_message = str(e)
            job_mix.finished_at = datetime.now(timezone.utc)
            await db.commit()
            raise

    file_size = final_path.stat().st_size if final_path.exists() else 0
    item.prep_status = PrepStatus.ready
    item.prepared_file_path = str(final_path)
    item.prepared_file_size_bytes = file_size
    await db.commit()

    logger.info("item_prepared", item_id=str(item.id), path=str(final_path), size=file_size)


async def _download_asset(db: AsyncSession, asset: LibraryAsset) -> Path:
    if asset.current_local_path:
        p = Path(asset.current_local_path)
        if p.exists():
            return p

    settings.ensure_spool_dirs()
    dest = settings.spool_downloads / f"{asset.id}{_ext(asset)}"

    if asset.source_type.value == "direct_url" and asset.source_url:
        checksum, size = await _stream_http_to_file(asset.source_url, dest)
    elif asset.source_type.value == "uploaded_file" and asset.local_source_path:
        src = Path(asset.local_source_path)
        if not src.exists():
            raise FileNotFoundError(f"Local source not found: {src}")
        checksum, size = await _copy_file_streaming(src, dest)
    else:
        raise ValueError(f"Cannot resolve source for asset {asset.id}")

    asset.current_local_path = str(dest)
    asset.current_local_size_bytes = size
    asset.checksum = checksum
    asset.last_downloaded_at = datetime.now(timezone.utc)
    asset.status = AssetStatus.downloaded
    await db.commit()

    return dest


async def _stream_http_to_file(url: str, dest: Path) -> tuple[str, int]:
    tmp = dest.with_name(dest.name + ".part")
    if tmp.exists():
        tmp.unlink()

    digest = hashlib.sha256()
    size = 0
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as f:
                    async for chunk in resp.aiter_bytes(DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            continue
                        f.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
        tmp.replace(dest)
        return digest.hexdigest(), size
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


async def _copy_file_streaming(src: Path, dest: Path) -> tuple[str, int]:
    tmp = dest.with_name(dest.name + ".part")
    if tmp.exists():
        tmp.unlink()

    digest = hashlib.sha256()
    size = 0
    try:
        with src.open("rb") as r, tmp.open("wb") as w:
            while True:
                chunk = r.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                w.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        tmp.replace(dest)
        return digest.hexdigest(), size
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def _ext(asset: LibraryAsset) -> str:
    if asset.source_url:
        url = asset.source_url.split("?")[0]
        if "." in url.split("/")[-1]:
            return "." + url.split("/")[-1].rsplit(".", 1)[-1]
    return ".mp4"

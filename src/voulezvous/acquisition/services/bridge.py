"""Bridge: acquisition subsystem → existing streaming MVP.

Promotes CandidateAssets into LibraryAssets and emits
LineupRuns into StreamPlans that the prep worker can discover.
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from voulezvous.acquisition.enums import (
    CandidateRightsStatus,
    LineupStatus,
    RetrievalStatus,
    SlotType,
)
from voulezvous.acquisition.models import CandidateAsset, LineupRun
from voulezvous.models.enums import (
    AssetKind,
    AssetStatus,
    PlanStatus,
    RightsStatus,
    SourceType,
)
from voulezvous.models.tables import LibraryAsset, StreamPlan, StreamPlanItem

logger = structlog.get_logger()


async def promote_candidate_to_library_asset(
    db: AsyncSession,
    candidate_id: uuid.UUID,
) -> LibraryAsset:
    """Promote an approved CandidateAsset into a LibraryAsset.

    Rules:
    - Candidate must exist.
    - rights_status must be approved_for_stream.
    - retrieval_status must be authorized_direct or authorized_official.
    - source_url must be present.
    - Idempotent: if library_asset_id already set, return existing.
    - Also deduplicates by source_url.
    """
    candidate = (await db.execute(
        select(CandidateAsset).where(CandidateAsset.id == candidate_id)
    )).scalar_one_or_none()

    if not candidate:
        raise ValueError(f"CandidateAsset {candidate_id} not found")

    if candidate.rights_status != CandidateRightsStatus.approved_for_stream:
        raise ValueError(
            f"CandidateAsset {candidate_id} rights_status is "
            f"{candidate.rights_status.value}, expected approved_for_stream"
        )

    if candidate.retrieval_status not in (
        RetrievalStatus.authorized_direct,
        RetrievalStatus.authorized_official,
    ):
        raise ValueError(
            f"CandidateAsset {candidate_id} retrieval_status is "
            f"{candidate.retrieval_status.value}, expected authorized_direct "
            f"or authorized_official"
        )

    if not candidate.source_url:
        raise ValueError(
            f"CandidateAsset {candidate_id} has no source_url"
        )

    # Idempotent: already promoted
    if candidate.library_asset_id:
        existing = (await db.execute(
            select(LibraryAsset).where(
                LibraryAsset.id == candidate.library_asset_id
            )
        )).scalar_one_or_none()
        if existing:
            logger.info(
                "candidate_already_promoted",
                candidate_id=str(candidate_id),
                library_asset_id=str(existing.id),
            )
            return existing

    # Deduplicate by source_url
    existing_by_url = (await db.execute(
        select(LibraryAsset).where(
            LibraryAsset.source_url == candidate.source_url
        )
    )).scalar_one_or_none()
    if existing_by_url:
        candidate.library_asset_id = existing_by_url.id
        await db.flush()
        logger.info(
            "candidate_promoted_dedup",
            candidate_id=str(candidate_id),
            library_asset_id=str(existing_by_url.id),
        )
        return existing_by_url

    tags = candidate.tags if isinstance(candidate.tags, list) else []

    asset = LibraryAsset(
        kind=AssetKind.video,
        title=candidate.title,
        source_type=SourceType.direct_url,
        source_url=candidate.source_url,
        source_name=candidate.page_url or candidate.source_url,
        duration_sec=candidate.duration_sec,
        tags=tags,
        notes=(
            f"Promoted from CandidateAsset {candidate.id}. "
            f"Page: {candidate.page_url or 'N/A'}"
        ),
        rights_status=RightsStatus.approved_for_stream,
        status=AssetStatus.approved,
    )

    try:
        async with db.begin_nested():
            db.add(asset)
            await db.flush()
    except IntegrityError:
        existing_after_race = (await db.execute(
            select(LibraryAsset).where(LibraryAsset.source_url == candidate.source_url)
        )).scalar_one_or_none()
        if existing_after_race is None:
            raise
        candidate.library_asset_id = existing_after_race.id
        await db.flush()
        logger.info(
            "candidate_promoted_dedup_after_integrity_error",
            candidate_id=str(candidate_id),
            library_asset_id=str(existing_after_race.id),
        )
        return existing_after_race

    candidate.library_asset_id = asset.id
    await db.flush()

    logger.info(
        "candidate_promoted",
        candidate_id=str(candidate_id),
        library_asset_id=str(asset.id),
    )
    return asset


async def emit_lineup_to_stream_plan(
    db: AsyncSession,
    lineup_id: uuid.UUID,
    target_start_at: datetime | None = None,
) -> StreamPlan:
    """Emit a LineupRun into a StreamPlan consumable by the prep worker.

    Rules:
    - LineupRun must exist with items.
    - Idempotent: if stream_plan_id already set, return existing.
    - main items are promoted and emitted.
    - buffer/fallback_reserve items are skipped (no fake content).
    - music_overlay items are skipped.
    """
    lineup = (await db.execute(
        select(LineupRun).where(LineupRun.id == lineup_id)
        .options(selectinload(LineupRun.items))
    )).scalar_one_or_none()

    if not lineup:
        raise ValueError(f"LineupRun {lineup_id} not found")

    if not lineup.items:
        raise ValueError(f"LineupRun {lineup_id} has no items")

    # Idempotent: already emitted
    if lineup.stream_plan_id:
        existing = (await db.execute(
            select(StreamPlan).where(
                StreamPlan.id == lineup.stream_plan_id
            ).options(selectinload(StreamPlan.items))
        )).scalar_one_or_none()
        if existing:
            logger.info(
                "lineup_already_emitted",
                lineup_id=str(lineup_id),
                stream_plan_id=str(existing.id),
            )
            return existing

    # Compute start/end
    plan_date = lineup.lineup_date
    if target_start_at is None:
        target_start_at = datetime(
            plan_date.year, plan_date.month, plan_date.day,
            tzinfo=timezone.utc,
        )

    # Promote and collect emittable items
    emitted_items: list[dict] = []
    skipped_count = 0
    cursor_at = target_start_at

    sorted_items = sorted(lineup.items, key=lambda i: i.sequence_index)

    for item in sorted_items:
        # Skip non-main items
        if item.slot_type in (
            SlotType.buffer,
            SlotType.fallback_reserve,
            SlotType.music_overlay,
        ):
            skipped_count += 1
            continue

        # Promote candidate
        try:
            library_asset = await promote_candidate_to_library_asset(
                db, item.candidate_asset_id
            )
        except ValueError as e:
            logger.warning(
                "lineup_item_skip_promote_failed",
                lineup_item_id=str(item.id),
                error=str(e),
            )
            skipped_count += 1
            continue

        # Compute duration
        duration_sec = None
        if item.target_start_at and item.target_end_at:
            duration_sec = int(
                (item.target_end_at - item.target_start_at).total_seconds()
            )
        if not duration_sec and library_asset.duration_sec:
            duration_sec = library_asset.duration_sec

        item_start = cursor_at
        if duration_sec:
            from datetime import timedelta
            item_end = cursor_at + timedelta(seconds=duration_sec)
        else:
            item_end = None

        emitted_items.append({
            "library_asset": library_asset,
            "lineup_item": item,
            "duration_sec": duration_sec,
            "start_at": item_start,
            "end_at": item_end,
        })

        if item_end:
            cursor_at = item_end

    if not emitted_items:
        raise ValueError(
            f"LineupRun {lineup_id}: no promotable items "
            f"(all {len(sorted_items)} items skipped)"
        )

    # Create StreamPlan
    plan = StreamPlan(
        plan_date=plan_date,
        status=PlanStatus.draft,
        target_start_at=target_start_at,
        target_end_at=cursor_at,
        notes=f"Emitted from acquisition LineupRun {lineup.id}",
    )
    db.add(plan)
    await db.flush()

    # Create StreamPlanItems
    for seq_idx, entry in enumerate(emitted_items):
        spi = StreamPlanItem(
            stream_plan_id=plan.id,
            sequence_index=seq_idx,
            video_asset_id=entry["library_asset"].id,
            planned_start_at=entry["start_at"],
            planned_end_at=entry["end_at"],
            target_duration_sec=entry["duration_sec"],
            mix_enabled=bool(entry["lineup_item"].music_asset_ref),
            delete_after_stream=True,
        )
        db.add(spi)

    await db.flush()

    # Mark lineup as emitted
    lineup.stream_plan_id = plan.id
    lineup.status = LineupStatus.emitted
    await db.commit()

    # Reload with items
    result = (await db.execute(
        select(StreamPlan).where(StreamPlan.id == plan.id)
        .options(selectinload(StreamPlan.items))
    )).scalar_one()

    logger.info(
        "lineup_emitted_to_stream_plan",
        lineup_id=str(lineup_id),
        stream_plan_id=str(plan.id),
        emitted_count=len(emitted_items),
        skipped_count=skipped_count,
    )
    return result

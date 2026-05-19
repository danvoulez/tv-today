import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles

# SQLite doesn't have JSONB; acquisition models are imported below.
if not hasattr(JSONB, "_sqlite_compiler_registered"):
    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):
        return "JSON"

    JSONB._sqlite_compiler_registered = True  # type: ignore[attr-defined]

from voulezvous.acquisition.enums import (  # noqa: E402
    CandidateRightsStatus,
    DiscoveryStatus,
    RetrievalStatus,
    SlotType,
)
from voulezvous.acquisition.models import CandidateAsset, LineupItem  # noqa: E402
from voulezvous.acquisition.workers.curator import generate_lineup  # noqa: E402
from voulezvous.acquisition.workers.json_utils import loads_llm_json  # noqa: E402
from voulezvous.models.enums import (  # noqa: E402
    AssetKind,
    AssetStatus,
    PlanStatus,
    PrepStatus,
    RightsStatus,
    SourceType,
    StreamItemStatus,
)
from voulezvous.models.tables import LibraryAsset, StreamPlan, StreamPlanItem  # noqa: E402
from voulezvous.services.streamer import _claim_next_ready_item  # noqa: E402
from voulezvous.services.stream_control import (  # noqa: E402
    request_stream_start,
    request_stream_stop,
    stream_status_payload,
)


@pytest.mark.asyncio
async def test_stream_control_is_database_backed(db: AsyncSession):
    await request_stream_start(db)
    status = await stream_status_payload(db)
    assert status["desired_running"] is True
    assert status["status"] == "start_requested"

    await request_stream_stop(db)
    status = await stream_status_payload(db)
    assert status["desired_running"] is False
    assert status["status"] == "stop_requested"


@pytest.mark.asyncio
async def test_streamer_can_claim_ready_item_from_preparing_plan(db: AsyncSession):
    asset = LibraryAsset(
        kind=AssetKind.video,
        title="Prepared Just In Time",
        source_type=SourceType.direct_url,
        source_url="https://example.com/video.mp4",
        duration_sec=10,
        rights_status=RightsStatus.approved_for_stream,
        status=AssetStatus.registered,
    )
    now = datetime.now(timezone.utc)
    plan = StreamPlan(
        plan_date=date(2026, 5, 19),
        status=PlanStatus.preparing,
        target_start_at=now,
        target_end_at=now,
    )
    db.add_all([asset, plan])
    await db.flush()

    item = StreamPlanItem(
        stream_plan_id=plan.id,
        video_asset_id=asset.id,
        sequence_index=0,
        planned_start_at=now,
        planned_end_at=now,
        target_duration_sec=10,
        prep_status=PrepStatus.ready,
        stream_status=StreamItemStatus.queued,
        prepared_file_path="/spool/prepared/test.mp4",
    )
    db.add(item)
    await db.commit()

    claimed = await _claim_next_ready_item(db)

    assert claimed is not None
    assert claimed.id == item.id
    assert claimed.stream_status == StreamItemStatus.streaming
    assert (await db.get(StreamPlan, plan.id)).status == PlanStatus.streaming


def test_loads_llm_json_accepts_fenced_and_prefaced_json():
    assert loads_llm_json('```json\n{"ok": true}\n```') == {"ok": True}
    assert loads_llm_json('Here is your JSON: [{"type": "flag_monotony"}]') == [
        {"type": "flag_monotony"}
    ]


@pytest.mark.asyncio
async def test_lineup_fills_target_with_explicit_repeat_overflow(db: AsyncSession):
    for i in range(5):
        db.add(
            CandidateAsset(
                id=uuid.uuid4(),
                title=f"Approved Video {i}",
                source_url=f"https://example.com/video-{i}.mp4",
                duration_sec=600,
                quality_signals={},
                tags=["test"],
                playback_verified=True,
                rights_status=CandidateRightsStatus.approved_for_stream,
                retrieval_status=RetrievalStatus.authorized_direct,
                discovery_status=DiscoveryStatus.accepted,
            )
        )
    await db.commit()

    lineup = await generate_lineup(db, date(2026, 5, 19), target_hours=24, mix_music=False)

    items = (
        await db.execute(
            select(LineupItem)
            .where(LineupItem.lineup_run_id == lineup.id)
            .order_by(LineupItem.sequence_index)
        )
    ).scalars().all()
    main_duration = sum(
        int((item.target_end_at - item.target_start_at).total_seconds())
        for item in items
        if item.slot_type in {SlotType.main, SlotType.buffer}
    )

    assert main_duration == 24 * 3600
    assert lineup.context_summary["target_filled"] is True
    assert lineup.context_summary["overflow_repeats_used"] is True

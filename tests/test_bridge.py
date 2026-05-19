"""Tests for the acquisition → streaming MVP bridge.

Covers:
1. Approved authorized CandidateAsset promotes to LibraryAsset.
2. Promotion is idempotent and does not duplicate LibraryAsset.
3. Pending/rejected/metadata-only CandidateAsset cannot be promoted.
4. LineupRun with approved candidate emits StreamPlan.
5. Emitted StreamPlan contains StreamPlanItem rows visible through existing model.
6. Buffer placeholder items are skipped.
7. Re-emitting same lineup does not create duplicate StreamPlan.
"""

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from voulezvous.acquisition.enums import (
    CandidateRightsStatus,
    DiscoveryStatus,
    LineupStatus,
    RetrievalStatus,
    SlotType,
)
from voulezvous.acquisition.models import CandidateAsset, LineupItem, LineupRun
from voulezvous.acquisition.services.bridge import (
    emit_lineup_to_stream_plan,
    promote_candidate_to_library_asset,
)
from voulezvous.models.base import Base
from voulezvous.models.enums import AssetKind, AssetStatus, PlanStatus, RightsStatus
from voulezvous.models.tables import LibraryAsset, StreamPlan, StreamPlanItem

# SQLite doesn't have JSONB — compile it as JSON for tests.
# Must be registered before create_all.
if not hasattr(JSONB, "_sqlite_compiler_registered"):
    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):
        return "JSON"
    JSONB._sqlite_compiler_registered = True  # type: ignore[attr-defined]

TEST_DB_URL = "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _make_approved_candidate(
    title: str = "Test Video",
    source_url: str = "https://archive.org/download/test/video.mp4",
    duration_sec: int = 1800,
    rights_status: CandidateRightsStatus = CandidateRightsStatus.approved_for_stream,
    retrieval_status: RetrievalStatus = RetrievalStatus.authorized_direct,
) -> CandidateAsset:
    return CandidateAsset(
        id=uuid.uuid4(),
        title=title,
        source_url=source_url,
        page_url="https://archive.org/details/test",
        duration_sec=duration_sec,
        quality_signals={"resolution": "1080p"},
        tags=["ambient", "public_domain"],
        playback_verified=True,
        rights_status=rights_status,
        retrieval_status=retrieval_status,
        discovery_status=DiscoveryStatus.accepted,
    )


# ---- Test 1: Approved authorized CandidateAsset promotes to LibraryAsset ----

@pytest.mark.asyncio
async def test_promote_approved_candidate(db: AsyncSession):
    candidate = _make_approved_candidate()
    db.add(candidate)
    await db.flush()

    asset = await promote_candidate_to_library_asset(db, candidate.id)

    assert asset.id is not None
    assert asset.kind == AssetKind.video
    assert asset.title == "Test Video"
    assert asset.source_url == "https://archive.org/download/test/video.mp4"
    assert asset.duration_sec == 1800
    assert asset.rights_status == RightsStatus.approved_for_stream
    assert asset.status == AssetStatus.approved
    assert str(candidate.id) in asset.notes
    assert isinstance(asset.tags, list)

    # Verify candidate now links to library asset
    await db.refresh(candidate)
    assert candidate.library_asset_id == asset.id


# ---- Test 2: Promotion is idempotent ----

@pytest.mark.asyncio
async def test_promote_idempotent(db: AsyncSession):
    candidate = _make_approved_candidate()
    db.add(candidate)
    await db.flush()

    asset1 = await promote_candidate_to_library_asset(db, candidate.id)
    asset2 = await promote_candidate_to_library_asset(db, candidate.id)

    assert asset1.id == asset2.id

    # Verify only 1 LibraryAsset exists
    count = len(
        (await db.execute(select(LibraryAsset))).scalars().all()
    )
    assert count == 1


# ---- Test 3: Pending/rejected/metadata-only cannot be promoted ----

@pytest.mark.asyncio
async def test_promote_rejected_pending_metadata_only(db: AsyncSession):
    # pending_review
    c1 = _make_approved_candidate(
        title="Pending",
        source_url="https://example.com/pending.mp4",
        rights_status=CandidateRightsStatus.pending_review,
    )
    db.add(c1)
    await db.flush()

    with pytest.raises(ValueError, match="approved_for_stream"):
        await promote_candidate_to_library_asset(db, c1.id)

    # blocked rights
    c2 = _make_approved_candidate(
        title="Blocked",
        source_url="https://example.com/blocked.mp4",
        rights_status=CandidateRightsStatus.blocked,
    )
    db.add(c2)
    await db.flush()

    with pytest.raises(ValueError, match="approved_for_stream"):
        await promote_candidate_to_library_asset(db, c2.id)

    # metadata_only retrieval
    c3 = _make_approved_candidate(
        title="MetadataOnly",
        source_url="https://example.com/meta.mp4",
        retrieval_status=RetrievalStatus.metadata_only,
    )
    db.add(c3)
    await db.flush()

    with pytest.raises(ValueError, match="authorized_direct"):
        await promote_candidate_to_library_asset(db, c3.id)

    # no source_url
    c4 = _make_approved_candidate(
        title="NoURL",
        source_url=None,
    )
    db.add(c4)
    await db.flush()

    with pytest.raises(ValueError, match="no source_url"):
        await promote_candidate_to_library_asset(db, c4.id)

    # Verify no LibraryAssets were created
    count = len(
        (await db.execute(select(LibraryAsset))).scalars().all()
    )
    assert count == 0


# ---- Test 4: LineupRun with approved candidate emits StreamPlan ----

@pytest.mark.asyncio
async def test_emit_lineup_to_stream_plan(db: AsyncSession):
    candidate = _make_approved_candidate()
    db.add(candidate)
    await db.flush()

    lineup = LineupRun(
        id=uuid.uuid4(),
        lineup_date=date(2026, 5, 19),
        status=LineupStatus.draft,
        context_summary={"total_items": 1},
    )
    db.add(lineup)
    await db.flush()

    item = LineupItem(
        id=uuid.uuid4(),
        lineup_run_id=lineup.id,
        sequence_index=0,
        candidate_asset_id=candidate.id,
        slot_type=SlotType.main,
        target_start_at=datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc),
        target_end_at=datetime(2026, 5, 19, 0, 30, tzinfo=timezone.utc),
    )
    db.add(item)
    await db.flush()

    plan = await emit_lineup_to_stream_plan(db, lineup.id)

    assert plan.id is not None
    assert plan.plan_date == date(2026, 5, 19)
    assert plan.status == PlanStatus.draft
    assert str(lineup.id) in plan.notes
    assert len(plan.items) == 1

    spi = plan.items[0]
    assert spi.sequence_index == 0
    assert spi.target_duration_sec == 1800  # 30 min
    assert spi.mix_enabled is False
    assert spi.delete_after_stream is True

    # Verify lineup is marked emitted
    await db.refresh(lineup)
    assert lineup.stream_plan_id == plan.id
    assert lineup.status == LineupStatus.emitted


# ---- Test 5: Emitted StreamPlan visible through existing model ----

@pytest.mark.asyncio
async def test_emitted_plan_visible_to_prep_model(db: AsyncSession):
    candidate = _make_approved_candidate(
        title="Prep Visible",
        source_url="https://archive.org/download/prep/visible.mp4",
    )
    db.add(candidate)
    await db.flush()

    lineup = LineupRun(
        id=uuid.uuid4(),
        lineup_date=date(2026, 5, 20),
        status=LineupStatus.draft,
        context_summary={},
    )
    db.add(lineup)
    await db.flush()

    item = LineupItem(
        id=uuid.uuid4(),
        lineup_run_id=lineup.id,
        sequence_index=0,
        candidate_asset_id=candidate.id,
        slot_type=SlotType.main,
    )
    db.add(item)
    await db.flush()

    await emit_lineup_to_stream_plan(db, lineup.id)

    # Query StreamPlanItems through existing model path (no acquisition imports)
    plan_items = (await db.execute(
        select(StreamPlanItem)
        .join(StreamPlan)
        .where(StreamPlan.plan_date == date(2026, 5, 20))
    )).scalars().all()

    assert len(plan_items) == 1
    spi = plan_items[0]

    # Verify the video_asset_id points to a real LibraryAsset
    asset = (await db.execute(
        select(LibraryAsset).where(LibraryAsset.id == spi.video_asset_id)
    )).scalar_one()
    assert asset.title == "Prep Visible"
    assert asset.status == AssetStatus.approved


# ---- Test 6: Buffer items are skipped ----

@pytest.mark.asyncio
async def test_buffer_items_skipped(db: AsyncSession):
    c_main = _make_approved_candidate(
        title="Main Content",
        source_url="https://archive.org/download/main/content.mp4",
    )
    c_buffer = _make_approved_candidate(
        title="Buffer Filler",
        source_url="https://archive.org/download/buffer/filler.mp4",
    )
    db.add(c_main)
    db.add(c_buffer)
    await db.flush()

    lineup = LineupRun(
        id=uuid.uuid4(),
        lineup_date=date(2026, 5, 21),
        status=LineupStatus.draft,
        context_summary={},
    )
    db.add(lineup)
    await db.flush()

    main_item = LineupItem(
        id=uuid.uuid4(),
        lineup_run_id=lineup.id,
        sequence_index=0,
        candidate_asset_id=c_main.id,
        slot_type=SlotType.main,
    )
    buffer_item = LineupItem(
        id=uuid.uuid4(),
        lineup_run_id=lineup.id,
        sequence_index=1,
        candidate_asset_id=c_buffer.id,
        slot_type=SlotType.buffer,
    )
    fallback_item = LineupItem(
        id=uuid.uuid4(),
        lineup_run_id=lineup.id,
        sequence_index=2,
        candidate_asset_id=c_main.id,
        slot_type=SlotType.fallback_reserve,
    )
    db.add_all([main_item, buffer_item, fallback_item])
    await db.flush()

    plan = await emit_lineup_to_stream_plan(db, lineup.id)

    # Only the main item should be emitted
    assert len(plan.items) == 1
    assert plan.items[0].sequence_index == 0

    # Buffer candidate should NOT have been promoted
    await db.refresh(c_buffer)
    assert c_buffer.library_asset_id is None


# ---- Test 7: Re-emitting same lineup does not create duplicate StreamPlan ----

@pytest.mark.asyncio
async def test_emit_idempotent(db: AsyncSession):
    candidate = _make_approved_candidate(
        title="Idempotent Test",
        source_url="https://archive.org/download/idem/test.mp4",
    )
    db.add(candidate)
    await db.flush()

    lineup = LineupRun(
        id=uuid.uuid4(),
        lineup_date=date(2026, 5, 22),
        status=LineupStatus.draft,
        context_summary={},
    )
    db.add(lineup)
    await db.flush()

    item = LineupItem(
        id=uuid.uuid4(),
        lineup_run_id=lineup.id,
        sequence_index=0,
        candidate_asset_id=candidate.id,
        slot_type=SlotType.main,
    )
    db.add(item)
    await db.flush()

    plan1 = await emit_lineup_to_stream_plan(db, lineup.id)
    plan2 = await emit_lineup_to_stream_plan(db, lineup.id)

    assert plan1.id == plan2.id

    # Verify only 1 StreamPlan exists
    plans = (await db.execute(select(StreamPlan))).scalars().all()
    assert len(plans) == 1

    # Verify only 1 LibraryAsset exists
    assets = (await db.execute(select(LibraryAsset))).scalars().all()
    assert len(assets) == 1

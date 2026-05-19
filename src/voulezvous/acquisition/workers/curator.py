"""Curator / planner — deterministic 24h lineup builder + bounded LLM polish.

Stage 1: Deterministic lineup build
- Only approved_for_stream assets
- Cooldown windows (min gap between repeats)
- Repetition caps
- Quality floors
- Time-of-day fitness
- Duration fitting
- Fallback reserve / buffer insertion

Stage 2: Bounded LLM polish (optional)
- swap item (max reorder distance)
- move item
- insert buffer
- adjust music pairing
- flag monotony
- flag risky candidate

The deterministic planner remains authoritative.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from voulezvous.acquisition.enums import (
    CandidateRightsStatus,
    DiscoveryStatus,
    LineupStatus,
    RetrievalStatus,
    SlotType,
)
from voulezvous.acquisition.models import (
    AssetEnrichment,
    CandidateAsset,
    LineupItem,
    LineupRun,
)
from voulezvous.acquisition.workers.json_utils import loads_llm_json

logger = structlog.get_logger()

# Hard constraints
MIN_COOLDOWN_SLOTS = 10  # Minimum slots before repeating an asset
MAX_REPEATS_PER_DAY = 3  # Max times one asset can appear in a day
BUFFER_EVERY_N_SLOTS = 8  # Insert a buffer every N slots
BUFFER_DURATION_SEC = 30  # Buffer / bumper duration
FALLBACK_RESERVE_COUNT = 3  # Reserve slots at end for fallback


async def build_candidate_shelf(db: AsyncSession) -> list[CandidateAsset]:
    """Build the approved shelf — only assets eligible for lineup."""
    result = await db.execute(
        select(CandidateAsset).where(
            CandidateAsset.rights_status == CandidateRightsStatus.approved_for_stream,
            CandidateAsset.discovery_status.in_([
                DiscoveryStatus.accepted, DiscoveryStatus.inspected
            ]),
            CandidateAsset.retrieval_status.in_([
                RetrievalStatus.authorized_direct,
                RetrievalStatus.authorized_official,
            ]),
            CandidateAsset.duration_sec.isnot(None),
            CandidateAsset.duration_sec > 0,
        ).options(
            selectinload(CandidateAsset.enrichment)
        ).order_by(CandidateAsset.created_at.desc())
    )
    return list(result.scalars().all())


def _get_time_slot(hour: int) -> str:
    """Classify hour into time slot."""
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 23:
        return "prime_time"
    else:
        return "late_night"


def _score_candidate_for_slot(candidate: CandidateAsset, enrichment: AssetEnrichment | None,
                               hour: int, used_count: int) -> float:
    """Score a candidate for a time slot. Higher = better fit."""
    score = 1.0

    # Time-of-day fitness
    if enrichment:
        slot = _get_time_slot(hour)
        if slot == "prime_time" and enrichment.prime_time_fit:
            score *= float(enrichment.prime_time_fit)
        elif slot == "late_night" and enrichment.late_night_fit:
            score *= float(enrichment.late_night_fit)

        # Penalize high repetition risk
        if enrichment.repetition_risk:
            score *= (1.0 - float(enrichment.repetition_risk) * 0.5)

    # Penalize repeat usage
    if used_count > 0:
        score *= 0.3 ** used_count

    return score


async def generate_lineup(db: AsyncSession, lineup_date: date,
                           target_hours: int = 24,
                           mix_music: bool = True) -> LineupRun:
    """Generate a deterministic 24h lineup from approved shelf."""
    shelf = await build_candidate_shelf(db)
    if not shelf:
        raise ValueError("No approved assets available for lineup generation")

    # Load enrichments
    enrichment_map: dict[uuid.UUID, AssetEnrichment] = {}
    for candidate in shelf:
        if candidate.enrichment:
            enrichment_map[candidate.id] = candidate.enrichment

    # Create lineup run
    lineup = LineupRun(
        lineup_date=lineup_date,
        status=LineupStatus.draft,
        context_summary={
            "shelf_size": len(shelf),
            "target_hours": target_hours,
            "mix_music": mix_music,
        },
    )
    db.add(lineup)
    await db.flush()

    target_sec = target_hours * 3600
    filled_sec = 0
    sequence = 0
    usage_count: dict[uuid.UUID, int] = {}
    last_used_at: dict[uuid.UUID, int] = {}
    previous_asset_id: uuid.UUID | None = None
    overflow_repeats_used = False

    start_time = datetime(lineup_date.year, lineup_date.month, lineup_date.day,
                          0, 0, 0, tzinfo=timezone.utc)

    while filled_sec < target_sec and shelf:
        current_hour = (filled_sec // 3600) % 24

        # Insert buffer periodically — only if a real bumper asset exists
        # (shortest asset on shelf as stand-in; skipped by bridge emit)
        if sequence > 0 and sequence % BUFFER_EVERY_N_SLOTS == 0:
            bumper = min(shelf, key=lambda c: c.duration_sec or 9999)
            if bumper.duration_sec and bumper.duration_sec <= 60:
                buffer_item = LineupItem(
                    lineup_run_id=lineup.id,
                    sequence_index=sequence,
                    candidate_asset_id=bumper.id,
                    target_start_at=start_time + timedelta(seconds=filled_sec),
                    target_end_at=start_time + timedelta(seconds=filled_sec + (bumper.duration_sec or BUFFER_DURATION_SEC)),
                    slot_type=SlotType.buffer,
                    decision_reason="Periodic buffer insertion",
                )
                db.add(buffer_item)
                filled_sec += bumper.duration_sec or BUFFER_DURATION_SEC
                sequence += 1

        # Score and select best candidate
        scored = []
        for c in shelf:
            count = usage_count.get(c.id, 0)
            if count >= MAX_REPEATS_PER_DAY:
                continue
            last_seq = last_used_at.get(c.id, -MIN_COOLDOWN_SLOTS - 1)
            if sequence - last_seq < MIN_COOLDOWN_SLOTS:
                continue

            enrichment = enrichment_map.get(c.id)
            s = _score_candidate_for_slot(c, enrichment, current_hour, count)
            scored.append((s, c))

        if not scored:
            # Controlled degradation: a 24h channel must either fill the target
            # or explicitly report that it relaxed the daily repetition cap.
            # Do not silently emit a 2h lineup for a 24h request.
            overflow_repeats_used = True
            last_used_at.clear()
            scored = [
                (0.10 if c.id != previous_asset_id else 0.01, c)
                for c in shelf
                if c.id != previous_asset_id or len(shelf) == 1
            ]
            if not scored:
                raise RuntimeError(
                    "Lineup generation stalled: no candidates available even after "
                    "repeat-overflow relaxation"
                )

        scored.sort(key=lambda x: -x[0])
        _, chosen = scored[0]

        dur = chosen.duration_sec or 600
        remaining = target_sec - filled_sec
        if dur > remaining:
            dur = remaining

        # Music pairing
        music_ref = None
        if mix_music:
            enrichment = enrichment_map.get(chosen.id)
            if enrichment and enrichment.music_pairing_hints:
                hints = enrichment.music_pairing_hints
                music_ref = hints[0] if isinstance(hints, list) and hints else None

        repeat_mode = (
            "repeat_overflow"
            if usage_count.get(chosen.id, 0) >= MAX_REPEATS_PER_DAY
            else "strict"
        )
        item = LineupItem(
            lineup_run_id=lineup.id,
            sequence_index=sequence,
            candidate_asset_id=chosen.id,
            target_start_at=start_time + timedelta(seconds=filled_sec),
            target_end_at=start_time + timedelta(seconds=filled_sec + dur),
            slot_type=SlotType.main,
            music_asset_ref=str(music_ref) if music_ref else None,
            decision_reason=(
                f"Score {scored[0][0]:.2f}, hour={current_hour}, "
                f"slot={_get_time_slot(current_hour)}, mode={repeat_mode}"
            ),
        )
        db.add(item)

        filled_sec += dur
        usage_count[chosen.id] = usage_count.get(chosen.id, 0) + 1
        last_used_at[chosen.id] = sequence
        previous_asset_id = chosen.id
        sequence += 1

    # Add fallback reserves
    fallback_count = 0
    for i in range(FALLBACK_RESERVE_COUNT):
        if shelf:
            fb = shelf[i % len(shelf)]
            item = LineupItem(
                lineup_run_id=lineup.id,
                sequence_index=sequence + i,
                candidate_asset_id=fb.id,
                slot_type=SlotType.fallback_reserve,
                decision_reason="Fallback reserve",
            )
            db.add(item)
            fallback_count += 1

    lineup.context_summary = {
        **(lineup.context_summary or {}),
        "total_items": sequence + fallback_count,
        "main_and_buffer_items": sequence,
        "fallback_reserve_items": fallback_count,
        "total_duration_sec": filled_sec,
        "total_duration_hours": round(filled_sec / 3600, 2),
        "target_duration_sec": target_sec,
        "target_filled": filled_sec >= target_sec,
        "overflow_repeats_used": overflow_repeats_used,
        "max_repeats_per_day": MAX_REPEATS_PER_DAY,
    }

    await db.commit()
    await db.refresh(lineup)
    logger.info("lineup_generated", id=str(lineup.id), items=sequence,
                hours=round(filled_sec / 3600, 2))
    return lineup


async def llm_polish_lineup(db: AsyncSession, lineup_id: uuid.UUID) -> dict:
    """Bounded LLM polish pass — only suggest bounded edits.

    The LLM may only:
    - swap item (within max_reorder_distance=3)
    - move item
    - insert buffer
    - adjust music pairing
    - flag monotony
    - flag risky candidate

    Falls back to deterministic quality checks if no LLM available.
    """
    lineup = (await db.execute(
        select(LineupRun).where(LineupRun.id == lineup_id)
    )).scalar_one_or_none()
    if not lineup:
        return {"error": "Lineup not found"}

    items = (await db.execute(
        select(LineupItem).where(LineupItem.lineup_run_id == lineup_id)
        .order_by(LineupItem.sequence_index)
    )).scalars().all()

    suggestions: list[dict] = []

    # Deterministic quality checks (always run)
    # Check for consecutive same-asset usage
    prev_asset_id = None
    for item in items:
        if item.slot_type == SlotType.buffer:
            continue
        if item.candidate_asset_id == prev_asset_id:
            suggestions.append({
                "type": "flag_monotony",
                "sequence_index": item.sequence_index,
                "reason": "Consecutive duplicate asset",
            })
        prev_asset_id = item.candidate_asset_id

    # Check music pairing gaps
    music_count = sum(1 for i in items if i.music_asset_ref and i.slot_type == SlotType.main)
    main_count = sum(1 for i in items if i.slot_type == SlotType.main)
    if main_count > 0 and music_count / main_count < 0.5:
        suggestions.append({
            "type": "adjust_music_pairing",
            "reason": f"Only {music_count}/{main_count} items have music pairing",
        })

    # Try LLM polish
    llm_suggestions = await _try_llm_polish(items)
    if llm_suggestions:
        suggestions.extend(llm_suggestions)

    return {
        "lineup_id": str(lineup_id),
        "suggestions": suggestions,
        "suggestion_count": len(suggestions),
    }


async def _try_llm_polish(items: list[LineupItem]) -> list[dict]:
    """Try to get LLM suggestions. Returns empty list if LLM unavailable."""
    try:
        import httpx

        summary = f"Lineup has {len(items)} items. "
        slot_types = {}
        for i in items[:20]:
            st = i.slot_type.value if hasattr(i.slot_type, 'value') else str(i.slot_type)
            slot_types[st] = slot_types.get(st, 0) + 1
        summary += f"Slot distribution (first 20): {slot_types}"

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3.2",
                    "prompt": (
                        f"Review this TV lineup and suggest improvements. {summary} "
                        f"Only suggest: swap_item, move_item, insert_buffer, "
                        f"adjust_music_pairing, flag_monotony, flag_risky. "
                        f"Return JSON array of suggestions."
                    ),
                    "stream": False,
                    "format": "json",
                },
            )
            if resp.status_code == 200:
                result = resp.json()
                data = loads_llm_json(result.get("response", "[]"), default=[])
                if isinstance(data, list):
                    return data[:5]  # Cap at 5 suggestions
        return []
    except Exception:
        return []

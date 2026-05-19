"""Bridge API — promote candidates and emit lineups to streaming MVP."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.acquisition.models import LineupItem
from voulezvous.acquisition.services.bridge import (
    emit_lineup_to_stream_plan,
    promote_candidate_to_library_asset,
)
from voulezvous.database import get_db

router = APIRouter(prefix="/acq", tags=["acquisition-bridge"])


class PromoteResponse(BaseModel):
    candidate_id: uuid.UUID
    library_asset_id: uuid.UUID
    title: str
    source_url: str | None


class EmitRequest(BaseModel):
    target_start_at: datetime | None = None


class EmitResponse(BaseModel):
    lineup_id: uuid.UUID
    stream_plan_id: uuid.UUID
    emitted_item_count: int
    skipped_item_count: int


@router.post(
    "/candidates/{candidate_id}/promote",
    response_model=PromoteResponse,
    status_code=200,
)
async def promote_candidate(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        asset = await promote_candidate_to_library_asset(db, candidate_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return PromoteResponse(
        candidate_id=candidate_id,
        library_asset_id=asset.id,
        title=asset.title,
        source_url=asset.source_url,
    )


@router.post(
    "/lineup/{lineup_id}/emit-stream-plan",
    response_model=EmitResponse,
    status_code=201,
)
async def emit_stream_plan(
    lineup_id: uuid.UUID,
    body: EmitRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    target_start = body.target_start_at if body else None
    try:
        plan = await emit_lineup_to_stream_plan(
            db, lineup_id, target_start_at=target_start
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    total_emitted = len(plan.items)
    lineup_item_count = (await db.execute(
        sa_select(sa_func.count()).select_from(LineupItem).where(
            LineupItem.lineup_run_id == lineup_id
        )
    )).scalar_one()
    skipped = lineup_item_count - total_emitted

    return EmitResponse(
        lineup_id=lineup_id,
        stream_plan_id=plan.id,
        emitted_item_count=total_emitted,
        skipped_item_count=skipped,
    )

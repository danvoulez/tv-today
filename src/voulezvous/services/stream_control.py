"""Distributed stream control backed by the database.

The API container and streamer container do not share Python memory. This
module stores the desired runtime state in Postgres so both processes observe
the same control plane.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.models.tables import StreamControl

STREAM_CONTROL_KEY = "main"


async def get_or_create_stream_control(db: AsyncSession) -> StreamControl:
    control = await db.get(StreamControl, STREAM_CONTROL_KEY)
    if control is None:
        control = StreamControl(
            key=STREAM_CONTROL_KEY,
            desired_running=False,
            status="idle",
        )
        db.add(control)
        await db.commit()
        await db.refresh(control)
    return control


async def request_stream_start(db: AsyncSession) -> StreamControl:
    control = await get_or_create_stream_control(db)
    control.desired_running = True
    control.status = "start_requested"
    control.heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(control)
    return control


async def request_stream_stop(db: AsyncSession) -> StreamControl:
    control = await get_or_create_stream_control(db)
    control.desired_running = False
    control.status = "stop_requested"
    control.current_item_id = None
    control.heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(control)
    return control


async def update_stream_runtime(
    db: AsyncSession,
    *,
    status: str,
    current_item_id: uuid.UUID | None = None,
    desired_running: bool | None = None,
) -> StreamControl:
    control = await get_or_create_stream_control(db)
    if desired_running is not None:
        control.desired_running = desired_running
    control.status = status
    control.current_item_id = current_item_id
    control.heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(control)
    return control


async def stream_should_run(db: AsyncSession) -> bool:
    control = await get_or_create_stream_control(db)
    return control.desired_running


async def stream_status_payload(db: AsyncSession) -> dict:
    control = await get_or_create_stream_control(db)
    return {
        "desired_running": control.desired_running,
        "running": control.desired_running
        and control.status in {"running", "streaming", "fallback"},
        "status": control.status,
        "current_item_id": str(control.current_item_id) if control.current_item_id else None,
        "heartbeat_at": control.heartbeat_at.isoformat() if control.heartbeat_at else None,
    }

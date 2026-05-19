import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from voulezvous.models.enums import (
    AssetKind,
    AssetStatus,
    EventType,
    PrepStatus,
    RightsStatus,
    SourceType,
    StreamItemStatus,
)

# --- Assets ---

class AssetCreate(BaseModel):
    kind: AssetKind
    title: str
    source_type: SourceType
    source_url: str | None = None
    local_source_path: str | None = None
    source_name: str | None = None
    duration_sec: int | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class AssetUpdate(BaseModel):
    title: str | None = None
    rights_status: RightsStatus | None = None
    status: AssetStatus | None = None
    approval_notes: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    source_url: str | None = None
    local_source_path: str | None = None
    duration_sec: int | None = None


class AssetOut(BaseModel):
    id: uuid.UUID
    kind: AssetKind
    title: str
    source_type: SourceType
    source_url: str | None
    local_source_path: str | None
    source_name: str | None
    duration_sec: int | None
    tags: list
    notes: str | None
    rights_status: RightsStatus
    approval_notes: str | None
    status: AssetStatus
    last_downloaded_at: datetime | None
    last_streamed_at: datetime | None
    times_streamed: int
    # Ficha de performance — acumulada a cada play
    health_score: float = 1.0
    error_count: int = 0
    last_play_status: str | None = None
    play_log: list = Field(default_factory=list)
    current_local_path: str | None
    current_local_size_bytes: int | None
    checksum: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Plans ---

class PlanGenerateRequest(BaseModel):
    plan_date: date
    hours: int = 24
    mix_music: bool = False


class PlanItemOut(BaseModel):
    id: uuid.UUID
    sequence_index: int
    video_asset_id: uuid.UUID
    music_asset_id: uuid.UUID | None
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    target_duration_sec: int | None
    mix_enabled: bool
    video_audio_gain: Decimal
    music_audio_gain: Decimal
    delete_after_stream: bool
    prep_status: PrepStatus
    stream_status: StreamItemStatus
    prepared_file_path: str | None
    actual_start_at: datetime | None
    actual_end_at: datetime | None
    error_log: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlanOut(BaseModel):
    id: uuid.UUID
    plan_date: date
    status: str
    target_start_at: datetime
    target_end_at: datetime
    notes: str | None
    items: list[PlanItemOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Reports ---

class ReportOut(BaseModel):
    id: uuid.UUID
    report_date: date
    status: str
    summary: dict
    markdown_text: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Events ---

class EventOut(BaseModel):
    id: uuid.UUID
    event_type: EventType
    plan_id: uuid.UUID | None
    plan_item_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    occurred_at: datetime
    payload: dict

    model_config = {"from_attributes": True}


# --- Health ---

class HealthOut(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"

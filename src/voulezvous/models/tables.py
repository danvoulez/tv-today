import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from voulezvous.models.base import Base, TimestampMixin, UUIDPrimaryKey
from voulezvous.models.enums import (
    AssetKind,
    AssetStatus,
    EventType,
    JobStatus,
    JobType,
    PlanStatus,
    PrepStatus,
    ReportStatus,
    RightsStatus,
    SourceType,
    StreamItemStatus,
)


class LibraryAsset(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "library_assets"
    __table_args__ = (UniqueConstraint("source_url", name="uq_library_assets_source_url"),)

    kind: Mapped[AssetKind] = mapped_column(
        Enum(AssetKind, native_enum=False), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    local_source_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[dict] = mapped_column(JSONB, server_default="[]", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    rights_status: Mapped[RightsStatus] = mapped_column(
        Enum(RightsStatus, native_enum=False),
        default=RightsStatus.pending_review,
        nullable=False,
    )
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, native_enum=False),
        default=AssetStatus.registered,
        nullable=False,
    )

    last_downloaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_streamed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    times_streamed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 0.0 = sempre falha, 1.0 = sempre completa sem erros. Recalculado após cada play.
    health_score: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0, nullable=False)

    # Último resultado: "ok" | "failed" | "skipped" | "partial"
    last_play_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Histórico de plays — cada entrada: {played_at, status, planned_sec, actual_sec, error}
    # Ghost: viewer_count ausente — requer integração com API RTMP (YouTube/Twitch)
    play_log: Mapped[list] = mapped_column(JSONB, server_default="[]", nullable=False)

    current_local_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    current_local_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)


class StreamPlan(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "stream_plans"

    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(
        Enum(PlanStatus, native_enum=False),
        default=PlanStatus.draft,
        nullable=False,
    )
    target_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    items: Mapped[list["StreamPlanItem"]] = relationship(
        back_populates="plan",
        order_by="StreamPlanItem.sequence_index",
        cascade="all, delete-orphan",
    )


class StreamPlanItem(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "stream_plan_items"

    stream_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stream_plans.id"), nullable=False
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    video_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("library_assets.id"), nullable=False
    )
    music_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("library_assets.id"), nullable=True
    )

    planned_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planned_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    target_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    mix_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    video_audio_gain: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("0.50"), nullable=False
    )
    music_audio_gain: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("0.50"), nullable=False
    )
    delete_after_stream: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    prep_status: Mapped[PrepStatus] = mapped_column(
        Enum(PrepStatus, native_enum=False),
        default=PrepStatus.queued,
        nullable=False,
    )
    stream_status: Mapped[StreamItemStatus] = mapped_column(
        Enum(StreamItemStatus, native_enum=False),
        default=StreamItemStatus.queued,
        nullable=False,
    )

    prepared_file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    prepared_file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    actual_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped["StreamPlan"] = relationship(back_populates="items")
    video_asset: Mapped["LibraryAsset"] = relationship(foreign_keys=[video_asset_id])
    music_asset: Mapped["LibraryAsset | None"] = relationship(
        foreign_keys=[music_asset_id]
    )


class PrepJob(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "prep_jobs"

    plan_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stream_plan_items.id"), nullable=False
    )
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, native_enum=False), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False),
        default=JobStatus.pending,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default="{}", nullable=False
    )

    plan_item: Mapped["StreamPlanItem"] = relationship()


class StreamEvent(Base, UUIDPrimaryKey):
    __tablename__ = "stream_events"

    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, native_enum=False), nullable=False
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stream_plans.id"), nullable=True
    )
    plan_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stream_plan_items.id"), nullable=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("library_assets.id"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)


class StreamControl(Base, TimestampMixin):
    __tablename__ = "stream_control"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    desired_running: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="idle", nullable=False)
    current_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stream_plan_items.id"), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DailyReport(Base, UUIDPrimaryKey):
    __tablename__ = "daily_reports"

    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, native_enum=False), nullable=False
    )
    summary: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    markdown_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("report_date", name="uq_daily_reports_date"),)

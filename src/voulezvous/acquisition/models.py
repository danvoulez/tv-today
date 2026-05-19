"""Acquisition subsystem database models — 10 tables."""

import uuid
from datetime import date, datetime

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from voulezvous.models.base import Base, TimestampMixin, UUIDPrimaryKey

from .enums import (
    AdapterType,
    CandidateRightsStatus,
    DiscoveryRunStatus,
    DiscoveryStatus,
    KeywordSource,
    LineupStatus,
    MediaIRStatus,
    RetrievalStatus,
    SearchMode,
    SlotType,
)


class DomainPolicy(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "domain_policies"

    domain: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    session_profile_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    search_mode: Mapped[SearchMode] = mapped_column(
        Enum(SearchMode, native_enum=False), default=SearchMode.keyword_search, nullable=False
    )
    allowed_actions: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    retrieval_modes: Mapped[dict] = mapped_column(JSONB, server_default="[]", nullable=False)
    requires_playback_verification: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    quality_floor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    max_pages_per_run: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SearchKeyword(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "search_keywords"

    keyword: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    weight: Mapped[float] = mapped_column(Numeric(5, 2), default=1.0, nullable=False)
    include: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[KeywordSource] = mapped_column(
        Enum(KeywordSource, native_enum=False),
        default=KeywordSource.operator,
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DiscoveryRun(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "discovery_runs"

    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[DiscoveryRunStatus] = mapped_column(
        Enum(DiscoveryRunStatus, native_enum=False),
        default=DiscoveryRunStatus.pending,
        nullable=False,
    )
    input_summary: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    output_summary: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)

    candidates: Mapped[list["CandidateAsset"]] = relationship(
        back_populates="discovery_run",
        cascade="all, delete-orphan",
    )


class CandidateAsset(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "candidate_assets"

    discovery_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_runs.id"), nullable=True
    )
    domain_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domain_policies.id"), nullable=True
    )
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    page_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_signals: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    tags: Mapped[dict] = mapped_column(JSONB, server_default="[]", nullable=False)
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default="{}", nullable=False
    )
    playback_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retrieval_status: Mapped[RetrievalStatus] = mapped_column(
        Enum(RetrievalStatus, native_enum=False),
        default=RetrievalStatus.none,
        nullable=False,
    )
    retrieval_adapter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("retrieval_adapters.id"), nullable=True
    )
    rights_status: Mapped[CandidateRightsStatus] = mapped_column(
        Enum(CandidateRightsStatus, native_enum=False),
        default=CandidateRightsStatus.pending_review,
        nullable=False,
    )
    discovery_status: Mapped[DiscoveryStatus] = mapped_column(
        Enum(DiscoveryStatus, native_enum=False),
        default=DiscoveryStatus.found,
        nullable=False,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    library_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("library_assets.id"), nullable=True
    )

    discovery_run: Mapped["DiscoveryRun | None"] = relationship(back_populates="candidates")
    retrieval_adapter: Mapped["RetrievalAdapter | None"] = relationship(
        foreign_keys=[retrieval_adapter_id],
    )
    enrichment: Mapped["AssetEnrichment | None"] = relationship(
        back_populates="candidate_asset", uselist=False
    )


class RetrievalAdapter(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "retrieval_adapters"

    candidate_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_assets.id"), nullable=False
    )
    adapter_type: Mapped[AdapterType] = mapped_column(
        Enum(AdapterType, native_enum=False), nullable=False
    )
    adapter_spec: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidate_asset: Mapped["CandidateAsset"] = relationship(
        foreign_keys=[candidate_asset_id],
        overlaps="retrieval_adapter",
    )


class AssetEnrichment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "asset_enrichments"

    candidate_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_assets.id"), nullable=False, unique=True
    )
    mood_tags: Mapped[dict] = mapped_column(JSONB, server_default="[]", nullable=False)
    theme_tags: Mapped[dict] = mapped_column(JSONB, server_default="[]", nullable=False)
    energy_score: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    pacing_score: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    repetition_risk: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    music_pairing_hints: Mapped[dict] = mapped_column(JSONB, server_default="[]", nullable=False)
    prime_time_fit: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    late_night_fit: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    llm_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    candidate_asset: Mapped["CandidateAsset"] = relationship(back_populates="enrichment")


class LineupRun(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "lineup_runs"

    lineup_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[LineupStatus] = mapped_column(
        Enum(LineupStatus, native_enum=False),
        default=LineupStatus.draft,
        nullable=False,
    )
    context_summary: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    stream_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stream_plans.id"), nullable=True
    )

    items: Mapped[list["LineupItem"]] = relationship(
        back_populates="lineup_run",
        order_by="LineupItem.sequence_index",
        cascade="all, delete-orphan",
    )


class LineupItem(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "lineup_items"

    lineup_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lineup_runs.id"), nullable=False
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_assets.id"), nullable=False
    )
    target_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    target_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    slot_type: Mapped[SlotType] = mapped_column(
        Enum(SlotType, native_enum=False), default=SlotType.main, nullable=False
    )
    music_asset_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    lineup_run: Mapped["LineupRun"] = relationship(back_populates="items")
    candidate_asset: Mapped["CandidateAsset"] = relationship()


class MediaIRJob(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "media_ir_jobs"

    lineup_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lineup_items.id"), nullable=False
    )
    status: Mapped[MediaIRStatus] = mapped_column(
        Enum(MediaIRStatus, native_enum=False),
        default=MediaIRStatus.queued,
        nullable=False,
    )
    ir_json: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    compiler_version: Mapped[str] = mapped_column(
        String(50), default="1.0.0", nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    lineup_item: Mapped["LineupItem"] = relationship()


class AutonomyReport(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "autonomy_reports"

    report_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    summary: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    markdown_text: Mapped[str | None] = mapped_column(Text, nullable=True)

"""Pydantic schemas for acquisition API."""
import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field
from .enums import CandidateRightsStatus, DiscoveryRunStatus, DiscoveryStatus, KeywordSource, LineupStatus, MediaIRStatus, RetrievalStatus, SearchMode, SlotType

class DomainPolicyCreate(BaseModel):
    domain: str
    is_enabled: bool = True
    session_profile_name: str | None = None
    search_mode: SearchMode = SearchMode.keyword_search
    allowed_actions: dict = Field(default_factory=dict)
    retrieval_modes: list = Field(default_factory=list)
    requires_playback_verification: bool = True
    quality_floor: str | None = None
    max_pages_per_run: int = 5
    notes: str | None = None
    search_url_template: str | None = None
    user_url_template: str | None = None
    result_selector: str | None = None
    title_selector: str | None = None
    login_url: str | None = None
    login_email_selector: str | None = None
    login_password_selector: str | None = Field(default=None, repr=False)
    login_submit_selector: str | None = None
    login_success_selector: str | None = None
    credential_email: str | None = None
    credential_password: str | None = Field(default=None, repr=False)
    accepted_extensions: list[str] = Field(default_factory=lambda: ["mp4", "webm", "m3u8", "mpd"])
    is_adult: bool = False
    requires_login: bool = False
    needs_media_interception: bool = False
    title_suffix_strips: list[str] = Field(default_factory=list)

class DomainPolicyUpdate(BaseModel):
    is_enabled: bool | None = None
    session_profile_name: str | None = None
    search_mode: SearchMode | None = None
    allowed_actions: dict | None = None
    retrieval_modes: list | None = None
    requires_playback_verification: bool | None = None
    quality_floor: str | None = None
    max_pages_per_run: int | None = None
    notes: str | None = None
    search_url_template: str | None = None
    user_url_template: str | None = None
    result_selector: str | None = None
    title_selector: str | None = None
    login_url: str | None = None
    login_email_selector: str | None = None
    login_password_selector: str | None = Field(default=None, repr=False)
    login_submit_selector: str | None = None
    login_success_selector: str | None = None
    credential_email: str | None = None
    credential_password: str | None = Field(default=None, repr=False)
    accepted_extensions: list[str] | None = None
    is_adult: bool | None = None
    requires_login: bool | None = None
    needs_media_interception: bool | None = None
    title_suffix_strips: list[str] | None = None

class DomainPolicyOut(DomainPolicyCreate):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class KeywordCreate(BaseModel):
    keyword: str
    category: str | None = None
    weight: float = 1.0
    include: bool = True
    source: KeywordSource = KeywordSource.operator
    active: bool = True
class KeywordUpdate(BaseModel):
    keyword: str | None = None
    category: str | None = None
    weight: float | None = None
    include: bool | None = None
    active: bool | None = None
class KeywordOut(BaseModel):
    id: uuid.UUID; keyword: str; category: str | None; weight: float; include: bool; source: KeywordSource; active: bool; created_at: datetime; updated_at: datetime
    model_config = {"from_attributes": True}
class DiscoveryRunOut(BaseModel):
    id: uuid.UUID; run_date: date; status: DiscoveryRunStatus; input_summary: dict; output_summary: dict; created_at: datetime; updated_at: datetime
    model_config = {"from_attributes": True}
class CandidateUpdate(BaseModel):
    rights_status: CandidateRightsStatus | None = None
    discovery_status: DiscoveryStatus | None = None
    rejection_reason: str | None = None
class CandidateOut(BaseModel):
    id: uuid.UUID; domain_policy_id: uuid.UUID | None; source_url: str | None; page_url: str | None; title: str; duration_sec: int | None; quality_signals: dict; tags: list | dict; metadata: dict = Field(validation_alias="extra_metadata"); playback_verified: bool; retrieval_status: RetrievalStatus; rights_status: CandidateRightsStatus; discovery_status: DiscoveryStatus; rejection_reason: str | None; created_at: datetime; updated_at: datetime
    model_config = {"from_attributes": True, "populate_by_name": True}
class LineupItemOut(BaseModel):
    id: uuid.UUID; sequence_index: int; candidate_asset_id: uuid.UUID; target_start_at: datetime | None; target_end_at: datetime | None; slot_type: SlotType; music_asset_ref: str | None; decision_reason: str | None
    model_config = {"from_attributes": True}
class LineupOut(BaseModel):
    id: uuid.UUID; lineup_date: date; status: LineupStatus; context_summary: dict; items: list[LineupItemOut] = []; created_at: datetime; updated_at: datetime
    model_config = {"from_attributes": True}
class LineupGenerateRequest(BaseModel):
    lineup_date: date; target_hours: int = 24; mix_music: bool = True
class MediaIRJobOut(BaseModel):
    id: uuid.UUID; lineup_item_id: uuid.UUID; status: MediaIRStatus; ir_json: dict; compiler_version: str; error_message: str | None; created_at: datetime; updated_at: datetime
    model_config = {"from_attributes": True}
class AutonomyReportOut(BaseModel):
    id: uuid.UUID; report_date: date; summary: dict; markdown_text: str | None; created_at: datetime
    model_config = {"from_attributes": True}

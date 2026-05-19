from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/voulezvous"
    database_url_sync: str = "postgresql://postgres:postgres@db:5432/voulezvous"

    spool_root: Path = Path("/spool")

    stream_target: str = "null"
    fallback_video: str = "fallback.mp4"

    prep_lookahead_hours: int = 6
    delete_after_stream: bool = True

    admin_token: str = ""

    ffmpeg_path: str = "ffmpeg"

    house_video_codec: str = "libx264"
    house_audio_codec: str = "aac"
    house_resolution: str = "1920x1080"
    house_frame_rate: int = 30
    house_audio_sample_rate: int = 48000

    # HLS settings
    hls_segment_duration: int = 6
    hls_playlist_size: int = 10

    # Cloudflare R2 settings
    cloudflare_account_id: str = ""
    cloudflare_r2_bucket: str = "voulezvous-hls"
    cloudflare_r2_access_key: str = ""
    cloudflare_r2_secret_key: str = ""
    cloudflare_r2_public_url: str = ""

    log_level: str = "INFO"

    # ── Local LLM (Ollama) ────────────────────────────────────────────────────
    local_llm_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2"

    # ── Adult platform credentials (stored only in .env, never in git) ────────
    xvideos_email: str = ""
    xvideos_password: str = ""
    pornhub_email: str = ""
    pornhub_password: str = ""
    gayboyfriendtv_email: str = ""
    gayboyfriendtv_password: str = ""
    fabhuse_email: str = ""
    fabhuse_password: str = ""

    # Username/channel to follow when no keyword search is configured
    adult_follow_user: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def spool_downloads(self) -> Path:
        return self.spool_root / "downloads"

    @property
    def spool_prepared(self) -> Path:
        return self.spool_root / "prepared"

    @property
    def spool_fallback(self) -> Path:
        return self.spool_root / "fallback"

    @property
    def spool_tmp(self) -> Path:
        return self.spool_root / "tmp"

    @property
    def spool_reports(self) -> Path:
        return self.spool_root / "reports"

    @property
    def spool_hls(self) -> Path:
        return self.spool_root / "hls"

    @property
    def fallback_video_path(self) -> Path:
        return self.spool_fallback / self.fallback_video

    @property
    def r2_enabled(self) -> bool:
        return bool(
            self.cloudflare_account_id
            and self.cloudflare_r2_access_key
            and self.cloudflare_r2_secret_key
        )

    def ensure_spool_dirs(self) -> None:
        for d in [
            self.spool_downloads,
            self.spool_prepared,
            self.spool_fallback,
            self.spool_tmp,
            self.spool_reports,
            self.spool_hls,
        ]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()

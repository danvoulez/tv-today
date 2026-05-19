"""Domain adapters — structured rules for known site patterns.

Each adapter provides deterministic extraction before any LLM is consulted.
"""

import re
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()


@dataclass
class CandidateResult:
    title: str = ""
    page_url: str = ""
    source_url: str | None = None
    duration_sec: int | None = None
    quality_signals: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    has_authorized_retrieval: bool = False
    retrieval_type: str | None = None


class BaseDomainAdapter:
    """Base adapter with generic extraction rules."""

    domain_pattern: str = "*"
    search_url_template: str | None = None
    result_selector: str = "a[href]"
    title_selector: str = "h1, h2, .title"
    video_selector: str = "video, iframe"

    def matches(self, domain: str) -> bool:
        if self.domain_pattern == "*":
            return True
        return domain.endswith(self.domain_pattern) or domain == self.domain_pattern

    def build_search_url(self, domain: str, query: str) -> str | None:
        if self.search_url_template:
            return self.search_url_template.format(domain=domain, query=query)
        return f"https://{domain}/search?q={query}"

    def parse_duration(self, text: str) -> int | None:
        """Parse duration from text like '1:30:00' or '5:23' or '300s'."""
        if not text:
            return None
        # HH:MM:SS or MM:SS
        m = re.match(r"(\d+):(\d+):(\d+)", text)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        m = re.match(r"(\d+):(\d+)", text)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        m = re.match(r"(\d+)\s*s", text)
        if m:
            return int(m.group(1))
        try:
            return int(float(text))
        except (ValueError, TypeError):
            return None

    def classify_retrieval(self, url: str | None, page_info: dict) -> tuple[bool, str | None]:
        """Determine if URL represents an authorized retrieval path."""
        if not url:
            return False, None
        # Only allow clearly direct media URLs
        if any(url.lower().endswith(ext) for ext in [".mp4", ".webm", ".m3u8", ".mpd"]):
            return True, "direct_url"
        return False, None


class InternetArchiveAdapter(BaseDomainAdapter):
    """Adapter for archive.org — public domain content."""

    domain_pattern = "archive.org"
    search_url_template = "https://archive.org/search?query={query}&mediatype=movies"
    result_selector = ".result-item a, .item-ttl a"
    title_selector = ".item-title, h1"

    def build_search_url(self, domain: str, query: str) -> str:
        return f"https://archive.org/search?query={query}&mediatype=movies"

    def classify_retrieval(self, url: str | None, page_info: dict) -> tuple[bool, str | None]:
        if not url:
            return False, None
        # Only authorize URLs on archive.org itself
        if "archive.org" not in url:
            return False, None
        if "archive.org/download/" in url:
            return True, "official_download"
        if url.endswith((".mp4", ".ogv", ".webm")):
            return True, "direct_url"
        return False, None


class PexelsAdapter(BaseDomainAdapter):
    """Adapter for pexels.com — free stock video via official API.

    Requires PEXELS_API_KEY env var. Without it, discovery is skipped
    and the domain policy should be disabled.
    """

    domain_pattern = "pexels.com"
    result_selector = "article a, .MediaCard a"

    def build_search_url(self, domain: str, query: str) -> str | None:
        import os
        api_key = os.environ.get("PEXELS_API_KEY", "")
        if not api_key:
            logger.warning("pexels_api_key_missing", msg="Set PEXELS_API_KEY to enable Pexels discovery")
            return None
        return f"https://api.pexels.com/videos/search?query={query}&per_page=15"

    def classify_retrieval(self, url: str | None, page_info: dict) -> tuple[bool, str | None]:
        if not url:
            return False, None
        if any(url.lower().endswith(ext) for ext in [".mp4", ".webm"]):
            return True, "direct_url"
        return False, None


class VimeoAdapter(BaseDomainAdapter):
    """Adapter for vimeo.com — official embeds and metadata."""

    domain_pattern = "vimeo.com"
    search_url_template = "https://vimeo.com/search?q={query}"
    result_selector = ".iris_video-vital a, a[href*='/video/'], a[href*='vimeo.com/']"

    def classify_retrieval(self, url: str | None, page_info: dict) -> tuple[bool, str | None]:
        # Vimeo does not offer direct downloads for most content
        # Only metadata_only unless there's an official download button
        if page_info.get("has_download_button"):
            return True, "official_download"
        return False, None


class XvideosAdapter(BaseDomainAdapter):
    """Adapter for xvideos.com — requires premium account for HD downloads.

    Credentials: XVIDEOS_EMAIL / XVIDEOS_PASSWORD in .env
    Session persisted at: /spool/browser_profiles/xvideos_session
    """

    domain_pattern = "xvideos.com"
    result_selector = ".thumb-block a.thumb, #videosSearchResult .thumb-block a"
    title_selector = ".title a, h2.page-title"

    LOGIN_URL = "https://www.xvideos.com/account/login"
    LOGIN_EMAIL_SEL = "input[name='username'], input[type='email']"
    LOGIN_PASS_SEL = "input[type='password']"
    LOGIN_SUBMIT_SEL = "button[type='submit'], input[type='submit']"
    LOGIN_SUCCESS_SEL = "a.login-link.logged, .logged-menu, .user-menu"

    def build_search_url(self, domain: str, query: str) -> str:
        return f"https://www.xvideos.com/?k={query.replace(' ', '+')}&sort=date"

    def build_user_url(self, username: str) -> str:
        return f"https://www.xvideos.com/profiles/{username}"

    def classify_retrieval(self, url: str | None, page_info: dict) -> tuple[bool, str | None]:
        if not url:
            return False, None
        if page_info.get("has_download_button") or page_info.get("intercepted_media"):
            return True, "official_download"
        if any(url.lower().endswith(ext) for ext in (".mp4", ".flv")):
            return True, "direct_url"
        return False, None


class PornhubAdapter(BaseDomainAdapter):
    """Adapter for pornhub.com — requires premium for HD downloads.

    Credentials: PORNHUB_EMAIL / PORNHUB_PASSWORD in .env
    Session persisted at: /spool/browser_profiles/pornhub_session
    """

    domain_pattern = "pornhub.com"
    result_selector = ".pcVideoListItem a.videoPreviewBg, li.videoblock a.img"
    title_selector = "h1.title, .video-title h1"

    LOGIN_URL = "https://www.pornhub.com/login"
    LOGIN_EMAIL_SEL = "input#username, input[name='username']"
    LOGIN_PASS_SEL = "input#password, input[type='password']"
    LOGIN_SUBMIT_SEL = "button#login, button.loginButton, button[type='submit']"
    LOGIN_SUCCESS_SEL = ".usernameLink, .username, a[href*='users/']"

    def build_search_url(self, domain: str, query: str) -> str:
        return f"https://www.pornhub.com/video/search?search={query.replace(' ', '+')}"

    def build_user_url(self, username: str) -> str:
        # Try both model and users paths
        return f"https://www.pornhub.com/model/{username}"

    def classify_retrieval(self, url: str | None, page_info: dict) -> tuple[bool, str | None]:
        if not url:
            return False, None
        if page_info.get("has_download_button") or page_info.get("intercepted_media"):
            return True, "official_download"
        if any(url.lower().endswith(ext) for ext in (".mp4",)):
            return True, "direct_url"
        return False, None


class GayboyfriendtvAdapter(BaseDomainAdapter):
    """Adapter for gayboyfriendtv.com — tube site, no login required for listing.

    Credentials optional: GAYBOYFRIENDTV_EMAIL / GAYBOYFRIENDTV_PASSWORD
    Session persisted at: /spool/browser_profiles/gayboyfriendtv_session
    """

    domain_pattern = "gayboyfriendtv.com"
    result_selector = ".thumb a, .video-item a, .item a"
    title_selector = "h1, .video-title, .title"

    LOGIN_URL = "https://www.gayboyfriendtv.com/login/"
    LOGIN_EMAIL_SEL = "input[name='username'], input[type='email']"
    LOGIN_PASS_SEL = "input[type='password']"
    LOGIN_SUBMIT_SEL = "button[type='submit'], input[type='submit']"
    LOGIN_SUCCESS_SEL = ".user-panel, .logged, a[href*='profile']"

    def build_search_url(self, domain: str, query: str) -> str:
        return f"https://www.gayboyfriendtv.com/search/{query.replace(' ', '-')}/"

    def build_user_url(self, username: str) -> str:
        return f"https://www.gayboyfriendtv.com/channel/{username}/"

    def classify_retrieval(self, url: str | None, page_info: dict) -> tuple[bool, str | None]:
        if not url:
            return False, None
        if page_info.get("intercepted_media"):
            return True, "official_download"
        if any(url.lower().endswith(ext) for ext in (".mp4", ".m3u8")):
            return True, "direct_url"
        return False, None


class FabhuseAdapter(BaseDomainAdapter):
    """Adapter for fabhuse.com — tube site.

    Credentials optional: FABHUSE_EMAIL / FABHUSE_PASSWORD
    Session persisted at: /spool/browser_profiles/fabhuse_session
    """

    domain_pattern = "fabhuse.com"
    result_selector = ".thumb a, .video-block a, .item a"
    title_selector = "h1, .video-title, .title"

    LOGIN_URL = "https://fabhuse.com/login/"
    LOGIN_EMAIL_SEL = "input[name='username'], input[name='email'], input[type='email']"
    LOGIN_PASS_SEL = "input[type='password']"
    LOGIN_SUBMIT_SEL = "button[type='submit'], input[type='submit']"
    LOGIN_SUCCESS_SEL = ".user-info, .logged-in, a[href*='profile']"

    def build_search_url(self, domain: str, query: str) -> str:
        return f"https://fabhuse.com/search/?q={query.replace(' ', '+')}"

    def build_user_url(self, username: str) -> str:
        return f"https://fabhuse.com/user/{username}/"

    def classify_retrieval(self, url: str | None, page_info: dict) -> tuple[bool, str | None]:
        if not url:
            return False, None
        if page_info.get("intercepted_media"):
            return True, "official_download"
        if any(url.lower().endswith(ext) for ext in (".mp4", ".m3u8")):
            return True, "direct_url"
        return False, None


class GenericVideoAdapter(BaseDomainAdapter):
    """Generic adapter for any approved domain."""

    domain_pattern = "*"

    def classify_retrieval(self, url: str | None, page_info: dict) -> tuple[bool, str | None]:
        if not url:
            return False, None
        if any(url.lower().endswith(ext) for ext in [".mp4", ".webm", ".m3u8"]):
            return True, "direct_url"
        return False, None


# Registry of adapters, checked in order
ADAPTER_REGISTRY: list[BaseDomainAdapter] = [
    InternetArchiveAdapter(),
    PexelsAdapter(),
    XvideosAdapter(),
    PornhubAdapter(),
    GayboyfriendtvAdapter(),
    FabhuseAdapter(),
    VimeoAdapter(),
    GenericVideoAdapter(),
]


def get_adapter_for_domain(domain: str) -> BaseDomainAdapter:
    """Get the best adapter for a given domain."""
    for adapter in ADAPTER_REGISTRY:
        if adapter.matches(domain) and adapter.domain_pattern != "*":
            return adapter
    return GenericVideoAdapter()

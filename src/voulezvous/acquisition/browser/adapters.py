from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.acquisition.models import DomainPolicy


class DBAdapter:
    """Adapter que lê toda configuração de uma row de domain_policies."""

    def __init__(self, policy: DomainPolicy):
        self.policy = policy

    def build_search_url(self, query: str) -> str | None:
        if not self.policy.search_url_template:
            return None
        return self.policy.search_url_template.format(
            domain=self.policy.domain,
            query=query.replace(" ", "+"),
        )

    def build_user_url(self, username: str) -> str | None:
        if not self.policy.user_url_template:
            return None
        return self.policy.user_url_template.format(
            domain=self.policy.domain,
            username=username,
        )

    def classify_retrieval(self, url, page_info) -> tuple[bool, str | None]:
        if self.policy.needs_media_interception and page_info.get("intercepted_media"):
            return True, "authorized_direct"
        if self.policy.requires_login and page_info.get("has_download_button"):
            return True, "official_download"
        if url:
            ext = urlparse(url).path.rsplit(".", 1)[-1].lower() if "." in urlparse(url).path else ""
            if ext and ext in (self.policy.accepted_extensions or []):
                return True, "direct_url"
        return False, None

    @property
    def result_selector(self): return self.policy.result_selector or "a[href]"
    @property
    def title_selector(self): return self.policy.title_selector or "h1, h2, .title"
    @property
    def login_url(self): return self.policy.login_url
    @property
    def login_email_selector(self): return self.policy.login_email_selector or "input[type='email'], input[name='username']"
    @property
    def login_password_selector(self): return self.policy.login_password_selector or "input[type='password']"
    @property
    def login_submit_selector(self): return self.policy.login_submit_selector or "button[type='submit']"
    @property
    def login_success_selector(self): return self.policy.login_success_selector or ".logged,.user-menu"


async def get_adapter_for_domain(domain: str, db: AsyncSession) -> DBAdapter | None:
    policy = (await db.execute(select(DomainPolicy).where(DomainPolicy.domain == domain))).scalar_one_or_none()
    if not policy:
        return None
    return DBAdapter(policy)

import asyncio
from datetime import date

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.acquisition.browser.adapters import get_adapter_for_domain
from voulezvous.acquisition.browser.runtime import BrowserRuntime
from voulezvous.acquisition.enums import CandidateRightsStatus, DiscoveryRunStatus, DiscoveryStatus, RetrievalStatus
from voulezvous.acquisition.models import CandidateAsset, DiscoveryRun, DomainPolicy

logger = structlog.get_logger()


async def run_user_discovery(db: AsyncSession, domain: str, username: str, max_videos: int = 20, run_date=None):
    run_date = run_date or date.today()
    policy = (await db.execute(select(DomainPolicy).where(DomainPolicy.domain == domain, DomainPolicy.is_enabled.is_(True)))).scalar_one_or_none()
    if not policy:
        raise ValueError(f"Domain policy not found/enabled: {domain}")
    adapter = await get_adapter_for_domain(domain, db)
    if not adapter:
        raise ValueError(f"Adapter not available for domain: {domain}")

    runtime = BrowserRuntime()
    found = 0
    added = 0
    errors = []
    profile = f"{domain.replace('.', '_')}_session"
    try:
        await runtime.launch(profile_name=profile)
        if policy.requires_login and policy.credential_email and policy.credential_password and adapter.login_url:
            await runtime.login(
                login_url=adapter.login_url,
                email=policy.credential_email,
                password=policy.credential_password,
                email_selector=adapter.login_email_selector,
                pass_selector=adapter.login_password_selector,
                submit_selector=adapter.login_submit_selector,
                success_check=adapter.login_success_selector,
            )
        user_url = adapter.build_user_url(username)
        if not user_url:
            raise ValueError("user_url_template missing")
        await runtime.navigate(user_url)
        await asyncio.sleep(2)
        links = await runtime.extract_links(selector=adapter.result_selector, max_results=max_videos)
        for link in links[:max_videos]:
            href = link.get('href')
            if not href:
                continue
            found += 1
            await runtime.navigate(href)
            media_info = await runtime.extract_media_info()
            intercepted = await runtime.intercept_media_requests()
            download_url = (intercepted[0] if intercepted else await runtime.click_download_button())
            ok, _ = adapter.classify_retrieval(download_url, {"has_download_button": bool(download_url), "intercepted_media": bool(intercepted)})
            c = CandidateAsset(title=(media_info.get('title') or link.get('text') or href)[:500], source_url=download_url or href, page_url=href, retrieval_status=RetrievalStatus.authorized_direct if ok else RetrievalStatus.metadata_only, rights_status=CandidateRightsStatus.pending_review, discovery_status=DiscoveryStatus.found, tags=[domain, username], extra_metadata=media_info)
            db.add(c); added += 1
        await db.commit()
    except Exception as e:
        errors.append(str(e))
    finally:
        await runtime.close()

    run = DiscoveryRun(run_date=run_date, status=DiscoveryRunStatus.completed, output_summary={"domain": domain, "creator": username, "total_found": found, "total_added": added, "errors": errors})
    db.add(run)
    await db.commit()
    return run

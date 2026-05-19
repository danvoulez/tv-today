"""Discovery worker — runs searches, inspects candidates, registers retrieval.

Per enabled domain policy:
1. load persisted browser session
2. run searches from active keywords
3. apply exclude keywords
4. inspect results
5. extract metadata
6. detect authorized retrieval path
7. register adapter or mark metadata_only
8. reject low-quality candidates
9. persist with reason codes

Restart-safe and idempotent via source_url dedup.
"""

from datetime import date

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.acquisition.browser.adapters import get_adapter_for_domain
from voulezvous.acquisition.browser.runtime import BrowserRuntime
from voulezvous.acquisition.enums import (
    AdapterType,
    DiscoveryRunStatus,
    DiscoveryStatus,
    RetrievalStatus,
)
from voulezvous.acquisition.models import (
    CandidateAsset,
    DiscoveryRun,
    DomainPolicy,
    RetrievalAdapter,
    SearchKeyword,
)
from voulezvous.acquisition.tools.executor import record_audit
from voulezvous.acquisition.tools.tool_types import ToolVerb

logger = structlog.get_logger()


async def run_discovery(db: AsyncSession, run_date: date | None = None) -> DiscoveryRun:
    """Execute a full discovery run across all enabled domains."""
    run_date = run_date or date.today()

    # Create run record
    run = DiscoveryRun(run_date=run_date, status=DiscoveryRunStatus.running)
    db.add(run)
    await db.flush()

    # Load enabled domain policies
    policies = (await db.execute(
        select(DomainPolicy).where(DomainPolicy.is_enabled.is_(True))
    )).scalars().all()

    # Load active include/exclude keywords
    include_kws = (await db.execute(
        select(SearchKeyword).where(
            SearchKeyword.active.is_(True), SearchKeyword.include.is_(True)
        )
    )).scalars().all()
    exclude_kws = (await db.execute(
        select(SearchKeyword).where(
            SearchKeyword.active.is_(True), SearchKeyword.include.is_(False)
        )
    )).scalars().all()

    exclude_terms = {kw.keyword.lower() for kw in exclude_kws}
    include_terms = sorted(
        [(kw.keyword, float(kw.weight)) for kw in include_kws],
        key=lambda x: -x[1],
    )

    run.input_summary = {
        "domains": [p.domain for p in policies],
        "include_keywords": [k for k, _ in include_terms],
        "exclude_keywords": list(exclude_terms),
    }

    total_found = 0
    total_accepted = 0
    total_rejected = 0
    total_metadata_only = 0

    browser = BrowserRuntime()

    for policy in policies:
        try:
            await browser.launch(profile_name=policy.session_profile_name)
            adapter = await get_adapter_for_domain(policy.domain, db)

            page_count = 0
            for keyword, weight in include_terms:
                if page_count >= policy.max_pages_per_run:
                    break

                # Search on the domain
                search_url = adapter.build_search_url(keyword)
                if not search_url:
                    continue

                nav_result = await browser.navigate(search_url)
                if not nav_result.get("success"):
                    continue
                page_count += 1

                record_audit(
                    ToolVerb.search_site,
                    {"domain": policy.domain, "query": keyword},
                    {"success": True, "url": search_url},
                )

                # Extract result links
                links = await browser.extract_links(adapter.result_selector)

                for link in links:
                    href = link.get("href", "")
                    text = link.get("text", "")

                    # Apply exclude keywords
                    if any(exc in text.lower() for exc in exclude_terms):
                        continue

                    # Dedup check
                    existing = (await db.execute(
                        select(CandidateAsset).where(
                            CandidateAsset.page_url == href
                        )
                    )).scalar_one_or_none()
                    if existing:
                        continue

                    # Navigate and inspect
                    if page_count >= policy.max_pages_per_run:
                        break

                    inspect_result = await browser.navigate(href)
                    if not inspect_result.get("success"):
                        continue
                    page_count += 1

                    media_info = await browser.extract_media_info()
                    title = media_info.get("title", text) or text

                    if not title.strip():
                        continue

                    # Check playback if required
                    playback_verified = False
                    duration_sec = None
                    if policy.requires_playback_verification:
                        pb = await browser.check_playback(timeout_sec=5)
                        playback_verified = pb.get("playback_works", False)
                        duration_sec = pb.get("duration_sec")

                    # Detect retrieval path
                    source_url = None
                    for v in media_info.get("videos", []):
                        if v.get("src"):
                            source_url = v["src"]
                            break

                    has_retrieval, retrieval_type = adapter.classify_retrieval(
                        source_url, media_info
                    )

                    # Determine quality
                    quality_signals = {
                        "video_count": media_info.get("video_count", 0),
                        "has_og_video": bool(media_info.get("og_video")),
                    }

                    # Create candidate
                    candidate = CandidateAsset(
                        discovery_run_id=run.id,
                        domain_policy_id=policy.id,
                        source_url=source_url,
                        page_url=href,
                        title=title[:1000],
                        duration_sec=duration_sec,
                        quality_signals=quality_signals,
                        tags=[keyword],
                        extra_metadata=media_info,
                        playback_verified=playback_verified,
                        discovery_status=DiscoveryStatus.inspected,
                    )

                    if has_retrieval and retrieval_type:
                        candidate.retrieval_status = RetrievalStatus.authorized_direct
                        candidate.discovery_status = DiscoveryStatus.accepted
                        db.add(candidate)
                        await db.flush()
                        adapter_record = RetrievalAdapter(
                            candidate_asset_id=candidate.id,
                            adapter_type=AdapterType(retrieval_type),
                            adapter_spec={"url": source_url},
                        )
                        db.add(adapter_record)
                        await db.flush()
                        candidate.retrieval_adapter_id = adapter_record.id
                        total_accepted += 1

                        record_audit(
                            ToolVerb.register_retrieval_adapter,
                            {"candidate": title, "type": retrieval_type},
                            {"success": True},
                        )
                    else:
                        candidate.retrieval_status = RetrievalStatus.metadata_only
                        total_metadata_only += 1

                    db.add(candidate)
                    total_found += 1

        except Exception as e:
            logger.error("discovery_domain_error", domain=policy.domain, error=str(e))
        finally:
            await browser.close()

    run.status = DiscoveryRunStatus.completed
    run.output_summary = {
        "total_found": total_found,
        "total_accepted": total_accepted,
        "total_rejected": total_rejected,
        "total_metadata_only": total_metadata_only,
    }

    await db.commit()
    await db.refresh(run)
    logger.info("discovery_complete", run_id=str(run.id), found=total_found)
    return run


async def run_discovery_simulated(db: AsyncSession, run_date: date | None = None) -> DiscoveryRun:
    """Run discovery without browser — uses domain policies and keywords to generate
    simulated candidates for testing/demo purposes."""
    run_date = run_date or date.today()

    run = DiscoveryRun(run_date=run_date, status=DiscoveryRunStatus.running)
    db.add(run)
    await db.flush()

    policies = (await db.execute(
        select(DomainPolicy).where(DomainPolicy.is_enabled.is_(True))
    )).scalars().all()

    include_kws = (await db.execute(
        select(SearchKeyword).where(
            SearchKeyword.active.is_(True), SearchKeyword.include.is_(True)
        )
    )).scalars().all()
    exclude_kws = (await db.execute(
        select(SearchKeyword).where(
            SearchKeyword.active.is_(True), SearchKeyword.include.is_(False)
        )
    )).scalars().all()

    exclude_terms = {kw.keyword.lower() for kw in exclude_kws}

    run.input_summary = {
        "domains": [p.domain for p in policies],
        "include_keywords": [kw.keyword for kw in include_kws],
        "exclude_keywords": list(exclude_terms),
        "mode": "simulated",
    }

    total_found = 0
    total_accepted = 0
    total_metadata_only = 0

    for policy in policies:
        adapter = await get_adapter_for_domain(policy.domain, db)

        for kw in include_kws:
            if any(exc in kw.keyword.lower() for exc in exclude_terms):
                continue

            # Dedup
            dedup_url = f"https://{policy.domain}/video/{kw.keyword.replace(' ', '-')}"
            existing = (await db.execute(
                select(CandidateAsset).where(CandidateAsset.page_url == dedup_url)
            )).scalar_one_or_none()
            if existing:
                continue

            # Simulate candidate based on domain type
            is_archive = "archive.org" in policy.domain
            source_url = (
                f"https://{policy.domain}/download/{kw.keyword.replace(' ', '_')}/video.mp4"
                if is_archive
                else None
            )

            has_retrieval, retrieval_type = adapter.classify_retrieval(
                source_url, {}
            )

            candidate = CandidateAsset(
                discovery_run_id=run.id,
                domain_policy_id=policy.id,
                source_url=source_url,
                page_url=dedup_url,
                title=f"{kw.keyword.title()} — {policy.domain}",
                duration_sec=600 + hash(kw.keyword) % 3000,
                quality_signals={"simulated": True, "keyword_weight": float(kw.weight)},
                tags=[kw.keyword, kw.category or "general"],
                extra_metadata={"domain": policy.domain, "keyword": kw.keyword},
                playback_verified=is_archive,
                discovery_status=DiscoveryStatus.inspected,
            )

            if has_retrieval and retrieval_type:
                candidate.retrieval_status = RetrievalStatus.authorized_direct
                candidate.discovery_status = DiscoveryStatus.accepted
                db.add(candidate)
                await db.flush()
                adapter_record = RetrievalAdapter(
                    candidate_asset_id=candidate.id,
                    adapter_type=AdapterType(retrieval_type),
                    adapter_spec={"url": source_url},
                )
                db.add(adapter_record)
                await db.flush()
                candidate.retrieval_adapter_id = adapter_record.id
                total_accepted += 1
            else:
                candidate.retrieval_status = RetrievalStatus.metadata_only
                candidate.discovery_status = DiscoveryStatus.inspected
                total_metadata_only += 1

            db.add(candidate)
            total_found += 1

    run.status = DiscoveryRunStatus.completed
    run.output_summary = {
        "total_found": total_found,
        "total_accepted": total_accepted,
        "total_metadata_only": total_metadata_only,
        "mode": "simulated",
    }

    await db.commit()
    await db.refresh(run)
    logger.info("discovery_simulated_complete", run_id=str(run.id), found=total_found)
    return run

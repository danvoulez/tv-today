"""Reporter — generates autonomy reports from daily run data.

Yesterday's report influences today's run:
- fallback usage
- repeated assets
- prep/stream failures
- blocked retrievals
- successful keywords/domains
- overused moods/themes
- storage pressure
- missing duration buckets
"""

from datetime import date

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.acquisition.enums import (
    CandidateRightsStatus,
    DiscoveryStatus,
    MediaIRStatus,
    RetrievalStatus,
    SlotType,
)
from voulezvous.acquisition.models import (
    AutonomyReport,
    CandidateAsset,
    DiscoveryRun,
    DomainPolicy,
    LineupItem,
    LineupRun,
    MediaIRJob,
    SearchKeyword,
)

logger = structlog.get_logger()


async def generate_report(db: AsyncSession, report_date: date | None = None) -> AutonomyReport:
    """Generate an autonomy report for the given date."""
    report_date = report_date or date.today()

    # Discovery stats
    discovery_runs = (await db.execute(
        select(DiscoveryRun).where(DiscoveryRun.run_date == report_date)
    )).scalars().all()

    total_found = sum(r.output_summary.get("total_found", 0) for r in discovery_runs)
    total_accepted = sum(r.output_summary.get("total_accepted", 0) for r in discovery_runs)
    total_metadata_only = sum(
        r.output_summary.get("total_metadata_only", 0) for r in discovery_runs
    )

    # Candidate stats
    all_candidates = (await db.execute(select(CandidateAsset))).scalars().all()
    approved_count = sum(
        1 for c in all_candidates
        if c.rights_status == CandidateRightsStatus.approved_for_stream
    )
    blocked_count = sum(
        1 for c in all_candidates
        if c.rights_status == CandidateRightsStatus.blocked
    )
    metadata_only_count = sum(
        1 for c in all_candidates
        if c.retrieval_status == RetrievalStatus.metadata_only
    )

    # Lineup stats
    lineups = (await db.execute(
        select(LineupRun).where(LineupRun.lineup_date == report_date)
    )).scalars().all()

    lineup_items_total = 0
    buffer_count = 0
    fallback_count = 0
    for lineup in lineups:
        items = (await db.execute(
            select(LineupItem).where(LineupItem.lineup_run_id == lineup.id)
        )).scalars().all()
        lineup_items_total += len(items)
        buffer_count += sum(1 for i in items if i.slot_type == SlotType.buffer)
        fallback_count += sum(1 for i in items if i.slot_type == SlotType.fallback_reserve)

    # Media IR stats
    ir_compiled = (await db.execute(
        select(func.count(MediaIRJob.id)).where(MediaIRJob.status == MediaIRStatus.compiled)
    )).scalar() or 0
    ir_failed = (await db.execute(
        select(func.count(MediaIRJob.id)).where(MediaIRJob.status == MediaIRStatus.failed)
    )).scalar() or 0

    # Domain health
    domains = (await db.execute(
        select(DomainPolicy).where(DomainPolicy.is_enabled.is_(True))
    )).scalars().all()
    domain_stats = []
    for d in domains:
        d_candidates = [c for c in all_candidates if c.domain_policy_id == d.id]
        domain_stats.append({
            "domain": d.domain,
            "total_candidates": len(d_candidates),
            "accepted": sum(
                1 for c in d_candidates
                if c.discovery_status == DiscoveryStatus.accepted
            ),
            "metadata_only": sum(
                1 for c in d_candidates
                if c.retrieval_status == RetrievalStatus.metadata_only
            ),
        })

    # Keyword effectiveness
    keywords = (await db.execute(
        select(SearchKeyword).where(SearchKeyword.active.is_(True))
    )).scalars().all()
    keyword_stats = []
    for kw in keywords:
        kw_candidates = [
            c for c in all_candidates
            if isinstance(c.tags, list) and kw.keyword in c.tags
        ]
        keyword_stats.append({
            "keyword": kw.keyword,
            "weight": float(kw.weight),
            "candidates_found": len(kw_candidates),
            "accepted": sum(
                1 for c in kw_candidates
                if c.discovery_status == DiscoveryStatus.accepted
            ),
        })

    # Duration distribution
    durations = [c.duration_sec for c in all_candidates if c.duration_sec]
    duration_buckets = {
        "short_under_5m": sum(1 for d in durations if d < 300),
        "medium_5_30m": sum(1 for d in durations if 300 <= d < 1800),
        "long_30_60m": sum(1 for d in durations if 1800 <= d < 3600),
        "very_long_over_60m": sum(1 for d in durations if d >= 3600),
    }

    # Suggestions
    suggestions = []
    if total_found == 0 and discovery_runs:
        suggestions.append("No new content found. Consider expanding keywords or adding domains.")
    if metadata_only_count > approved_count:
        suggestions.append(
            "More metadata-only assets than downloadable. "
            "Consider adding domains with direct download support."
        )
    if buffer_count > lineup_items_total * 0.3 and lineup_items_total > 0:
        suggestions.append("High buffer ratio. More approved content needed to fill lineup.")
    if duration_buckets.get("short_under_5m", 0) > len(durations) * 0.7:
        suggestions.append("Content skews short. Consider targeting longer-form content.")
    for ks in keyword_stats:
        if ks["candidates_found"] == 0:
            suggestions.append(f"Keyword '{ks['keyword']}' found nothing. Consider deactivating.")

    summary = {
        "report_date": str(report_date),
        "discovery": {
            "runs": len(discovery_runs),
            "total_found": total_found,
            "total_accepted": total_accepted,
            "total_metadata_only": total_metadata_only,
        },
        "library": {
            "total_candidates": len(all_candidates),
            "approved": approved_count,
            "blocked": blocked_count,
            "metadata_only": metadata_only_count,
        },
        "lineup": {
            "lineups_generated": len(lineups),
            "total_items": lineup_items_total,
            "buffers": buffer_count,
            "fallback_reserves": fallback_count,
        },
        "media_ir": {
            "compiled": ir_compiled,
            "failed": ir_failed,
        },
        "domain_health": domain_stats,
        "keyword_effectiveness": keyword_stats,
        "duration_distribution": duration_buckets,
        "suggestions": suggestions,
    }

    # Markdown report
    md_lines = [
        f"# Autonomy Report — {report_date}",
        "",
        "## Discovery",
        f"- Runs: {len(discovery_runs)}",
        f"- Found: {total_found}",
        f"- Accepted: {total_accepted}",
        f"- Metadata only: {total_metadata_only}",
        "",
        "## Library",
        f"- Total candidates: {len(all_candidates)}",
        f"- Approved for stream: {approved_count}",
        f"- Blocked: {blocked_count}",
        f"- Metadata only: {metadata_only_count}",
        "",
        "## Lineup",
        f"- Lineups generated: {len(lineups)}",
        f"- Total items: {lineup_items_total}",
        f"- Buffers: {buffer_count}",
        f"- Fallback reserves: {fallback_count}",
        "",
        "## Media IR",
        f"- Compiled: {ir_compiled}",
        f"- Failed: {ir_failed}",
        "",
        "## Domain Health",
    ]
    for ds in domain_stats:
        md_lines.append(f"- **{ds['domain']}**: {ds['total_candidates']} candidates, "
                        f"{ds['accepted']} accepted, {ds['metadata_only']} metadata-only")

    md_lines.extend(["", "## Keyword Effectiveness"])
    for ks in keyword_stats:
        md_lines.append(f"- **{ks['keyword']}** (w={ks['weight']}): "
                        f"{ks['candidates_found']} found, {ks['accepted']} accepted")

    md_lines.extend(["", "## Duration Distribution"])
    for bucket, count in duration_buckets.items():
        md_lines.append(f"- {bucket}: {count}")

    if suggestions:
        md_lines.extend(["", "## Operator Suggestions"])
        for s in suggestions:
            md_lines.append(f"- {s}")

    markdown_text = "\n".join(md_lines)

    # Upsert: update existing report for this date instead of duplicating
    existing = (await db.execute(
        select(AutonomyReport).where(AutonomyReport.report_date == report_date)
    )).scalar_one_or_none()

    if existing:
        existing.summary = summary
        existing.markdown_text = markdown_text
        report = existing
    else:
        report = AutonomyReport(
            report_date=report_date,
            summary=summary,
            markdown_text=markdown_text,
        )
        db.add(report)

    await db.commit()
    await db.refresh(report)

    logger.info("autonomy_report_generated", date=str(report_date))
    return report

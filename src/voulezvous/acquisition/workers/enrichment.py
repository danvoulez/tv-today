"""Enrichment worker — generates soft metadata for accepted candidates.

Uses local LLM inference for bounded enrichment tasks.
Falls back to deterministic heuristics when no local model is available.
"""

import hashlib

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.acquisition.enums import DiscoveryStatus
from voulezvous.acquisition.models import AssetEnrichment, CandidateAsset
from voulezvous.acquisition.tools.executor import record_audit
from voulezvous.acquisition.tools.tool_types import ToolVerb
from voulezvous.acquisition.workers.json_utils import loads_llm_json

logger = structlog.get_logger()


# Deterministic enrichment heuristics — used when no local LLM is available
MOOD_KEYWORDS = {
    "chill": ["ambient", "relax", "calm", "peaceful", "lo-fi", "lofi"],
    "energetic": ["dance", "party", "upbeat", "fast", "action", "intense"],
    "dramatic": ["cinematic", "epic", "drama", "tension", "suspense"],
    "melancholy": ["sad", "slow", "emotional", "nostalgic", "moody"],
    "uplifting": ["happy", "joy", "bright", "positive", "inspiring"],
}

THEME_KEYWORDS = {
    "nature": ["nature", "ocean", "mountain", "forest", "landscape", "earth", "wildlife"],
    "urban": ["city", "street", "urban", "downtown", "architecture"],
    "abstract": ["abstract", "visual", "art", "experimental", "generative"],
    "music": ["music", "concert", "dj", "set", "mix", "beat", "electronic"],
    "documentary": ["documentary", "doc", "history", "science", "culture"],
    "travel": ["travel", "explore", "journey", "adventure", "world"],
}


def _score_from_seed(title: str, salt: str, low: float = 0.2, high: float = 0.9) -> float:
    """Generate a deterministic score from title hash."""
    h = int(hashlib.md5(f"{title}{salt}".encode()).hexdigest()[:8], 16)
    return round(low + (h % 100) / 100 * (high - low), 2)


def _match_keywords(text: str, keyword_map: dict[str, list[str]]) -> list[str]:
    """Match text against keyword categories."""
    text_lower = text.lower()
    matched = []
    for category, keywords in keyword_map.items():
        if any(kw in text_lower for kw in keywords):
            matched.append(category)
    return matched or ["general"]


def enrich_deterministic(title: str, tags: list, duration_sec: int | None,
                         metadata: dict) -> dict:
    """Deterministic enrichment — no LLM needed."""
    text = f"{title} {' '.join(str(t) for t in tags)} {metadata.get('description', '')}"

    mood_tags = _match_keywords(text, MOOD_KEYWORDS)
    theme_tags = _match_keywords(text, THEME_KEYWORDS)
    energy = _score_from_seed(title, "energy")
    pacing = _score_from_seed(title, "pacing")

    # Repetition risk based on title uniqueness
    rep_risk = 0.1 if len(title) > 20 else 0.4

    # Duration-based time slot fitness
    dur = duration_sec or 600
    prime_time = 0.8 if 300 <= dur <= 3600 else 0.4
    late_night = 0.8 if dur > 1800 else 0.5

    music_hints = []
    if energy > 0.6:
        music_hints.append("upbeat_electronic")
    elif energy < 0.4:
        music_hints.append("ambient_chill")
    else:
        music_hints.append("neutral_background")

    return {
        "mood_tags": mood_tags,
        "theme_tags": theme_tags,
        "energy_score": energy,
        "pacing_score": pacing,
        "repetition_risk": rep_risk,
        "music_pairing_hints": music_hints,
        "prime_time_fit": prime_time,
        "late_night_fit": late_night,
        "llm_notes": "Enriched via deterministic heuristics (no local LLM available)",
        "model_name": "deterministic_v1",
    }


async def try_enrich_with_llm(title: str, tags: list, duration_sec: int | None,
                               metadata: dict) -> dict | None:
    """Attempt LLM-based enrichment using local inference. Returns None if unavailable."""
    try:
        import httpx

        from voulezvous.config import settings

        llm_url = settings.local_llm_url.rstrip("/")
        model = settings.ollama_model

        async with httpx.AsyncClient(timeout=45) as client:
            prompt = (
                f"Analyze this video content for TV scheduling. "
                f"Title: {title}. Tags: {', '.join(str(t) for t in tags)}. "
                f"Duration: {duration_sec or 'unknown'}s. "
                f"Return JSON with: mood_tags (list), theme_tags (list), "
                f"energy_score (0-1), pacing_score (0-1), repetition_risk (0-1), "
                f"music_pairing_hints (list), prime_time_fit (0-1), late_night_fit (0-1), "
                f"llm_notes (string)."
            )

            resp = await client.post(
                f"{llm_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            if resp.status_code == 200:
                result = resp.json()
                text = result.get("response", "")
                data = loads_llm_json(text)
                if isinstance(data, dict):
                    data["model_name"] = result.get("model", model)
                    return data
                logger.debug("llm_json_parse_failed", response=text[:200])
                return None
    except Exception as e:
        logger.debug("llm_enrichment_unavailable", error=str(e))
        return None


async def run_enrichment(db: AsyncSession) -> dict:
    """Enrich all accepted candidates that don't have enrichment yet."""
    # Find candidates needing enrichment
    result = await db.execute(
        select(CandidateAsset).where(
            CandidateAsset.discovery_status.in_([
                DiscoveryStatus.accepted, DiscoveryStatus.inspected
            ]),
            ~CandidateAsset.id.in_(
                select(AssetEnrichment.candidate_asset_id)
            ),
        )
    )
    candidates = result.scalars().all()

    enriched_count = 0
    llm_count = 0
    heuristic_count = 0

    for candidate in candidates:
        tags = candidate.tags if isinstance(candidate.tags, list) else []

        # Try LLM first, fall back to deterministic
        llm_result = await try_enrich_with_llm(
            candidate.title, tags, candidate.duration_sec, candidate.extra_metadata
        )

        if llm_result:
            data = llm_result
            llm_count += 1
        else:
            data = enrich_deterministic(
                candidate.title, tags, candidate.duration_sec, candidate.extra_metadata
            )
            heuristic_count += 1

        enrichment = AssetEnrichment(
            candidate_asset_id=candidate.id,
            mood_tags=data.get("mood_tags", []),
            theme_tags=data.get("theme_tags", []),
            energy_score=data.get("energy_score"),
            pacing_score=data.get("pacing_score"),
            repetition_risk=data.get("repetition_risk"),
            music_pairing_hints=data.get("music_pairing_hints", []),
            prime_time_fit=data.get("prime_time_fit"),
            late_night_fit=data.get("late_night_fit"),
            llm_notes=data.get("llm_notes", ""),
            model_name=data.get("model_name", "unknown"),
        )
        db.add(enrichment)

        record_audit(
            ToolVerb.enrich_candidate,
            {"candidate_id": str(candidate.id), "title": candidate.title},
            {"model": data.get("model_name", "unknown")},
        )
        enriched_count += 1

    await db.commit()
    logger.info("enrichment_complete", total=enriched_count, llm=llm_count,
                heuristic=heuristic_count)
    return {
        "enriched": enriched_count,
        "llm_enriched": llm_count,
        "heuristic_enriched": heuristic_count,
    }

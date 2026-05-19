import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.models.enums import AssetKind, AssetStatus, RightsStatus, SourceType
from voulezvous.models.tables import LibraryAsset

logger = structlog.get_logger()

DEMO_VIDEOS = [
    {
        "title": "Big Buck Bunny",
        "source_url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/1080/Big_Buck_Bunny_1080_10s_1MB.mp4",
        "duration_sec": 10,
        "tags": ["animation", "demo"],
        "notes": "Blender Foundation — Creative Commons",
    },
    {
        "title": "Sintel Trailer",
        "source_url": "https://test-videos.co.uk/vids/sintel/mp4/h264/1080/Sintel_1080_10s_1MB.mp4",
        "duration_sec": 10,
        "tags": ["animation", "demo"],
        "notes": "Blender Foundation — Creative Commons",
    },
    {
        "title": "Jellyfish Test Clip",
        "source_url": "https://test-videos.co.uk/vids/jellyfish/mp4/h264/1080/Jellyfish_1080_10s_1MB.mp4",
        "duration_sec": 10,
        "tags": ["nature", "demo"],
        "notes": "Test video — public domain",
    },
]

DEMO_MUSIC = [
    {
        "title": "Ambient Background Loop A",
        "source_url": "",
        "duration_sec": 120,
        "tags": ["ambient", "background"],
        "notes": "Placeholder — operator must supply actual file",
    },
    {
        "title": "Lo-Fi Chill Beat B",
        "source_url": "",
        "duration_sec": 180,
        "tags": ["lofi", "background"],
        "notes": "Placeholder — operator must supply actual file",
    },
]


async def seed_demo_data(db: AsyncSession) -> dict:
    created = {"videos": 0, "music": 0}

    for v in DEMO_VIDEOS:
        asset = LibraryAsset(
            kind=AssetKind.video,
            title=v["title"],
            source_type=SourceType.direct_url,
            source_url=v["source_url"],
            duration_sec=v["duration_sec"],
            tags=v["tags"],
            notes=v["notes"],
            rights_status=RightsStatus.approved_for_stream,
            status=AssetStatus.approved,
        )
        db.add(asset)
        created["videos"] += 1

    for m in DEMO_MUSIC:
        asset = LibraryAsset(
            kind=AssetKind.music,
            title=m["title"],
            source_type=SourceType.uploaded_file if not m["source_url"] else SourceType.direct_url,
            source_url=m["source_url"] or None,
            duration_sec=m["duration_sec"],
            tags=m["tags"],
            notes=m["notes"],
            rights_status=RightsStatus.pending_review,
            status=AssetStatus.registered,
        )
        db.add(asset)
        created["music"] += 1

    await db.commit()
    logger.info("seed_complete", created=created)
    return created


from voulezvous.services.ffmpeg import run_ffmpeg
from voulezvous.config import settings

async def ensure_fallback():
    fb=settings.fallback_video_path
    fb.parent.mkdir(parents=True, exist_ok=True)
    if fb.exists(): return
    args=["-f","lavfi","-i","color=c=black:s=1920x1080:d=30","-f","lavfi","-i","sine=f=440:b=4:duration=30","-c:v","libx264","-c:a","aac","-shortest","-y",str(fb)]
    rc,_,err=await run_ffmpeg(args)
    if rc!=0: raise RuntimeError(err[-500:])

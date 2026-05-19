from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voulezvous.config import settings
from voulezvous.models.tables import LibraryAsset

logger = structlog.get_logger()


async def cleanup_orphan_downloads(db: AsyncSession) -> dict:
    downloads_dir = settings.spool_downloads
    downloads_dir.mkdir(parents=True, exist_ok=True)

    referenced = {
        Path(p).resolve()
        for p in (await db.execute(select(LibraryAsset.current_local_path))).scalars().all()
        if p
    }

    deleted = []
    skipped = 0
    for f in downloads_dir.glob("**/*"):
        if not f.is_file():
            continue
        try:
            resolved = f.resolve()
        except FileNotFoundError:
            continue

        if resolved in referenced:
            skipped += 1
            continue

        try:
            f.unlink()
            deleted.append(str(f))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cleanup_delete_failed", path=str(f), error=str(exc))

    return {"deleted": len(deleted), "kept": skipped}

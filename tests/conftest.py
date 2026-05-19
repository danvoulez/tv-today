from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from voulezvous.models.base import Base
from voulezvous.models.tables import (  # noqa: F401
    DailyReport,
    LibraryAsset,
    PrepJob,
    StreamControl,
    StreamEvent,
    StreamPlan,
    StreamPlanItem,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# Patch JSONB columns to use plain JSON for SQLite compatibility
for table in Base.metadata.tables.values():
    for column in table.columns:
        if isinstance(column.type, JSONB):
            column.type = JSON()


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

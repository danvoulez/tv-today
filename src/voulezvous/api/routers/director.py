from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from voulezvous.database import get_db
from voulezvous.models.tables import DirectorAction, DirectorRun
from voulezvous.services.director import director_tick
router=APIRouter(prefix='/director', tags=['director'])
@router.get('/runs')
async def list_runs(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(DirectorRun).order_by(DirectorRun.started_at.desc()).limit(50))).scalars().all()
@router.get('/runs/{run_id}')
async def get_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    run=(await db.execute(select(DirectorRun).where(DirectorRun.id==run_id))).scalar_one()
    actions=(await db.execute(select(DirectorAction).where(DirectorAction.run_id==run_id).order_by(DirectorAction.sequence_index))).scalars().all()
    return {"run": run, "actions": actions}
@router.get('/actions')
async def list_actions(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(DirectorAction).order_by(DirectorAction.created_at.desc()).limit(100))).scalars().all()
@router.post('/tick')
async def tick(db: AsyncSession = Depends(get_db)):
    run=await director_tick(db); return {"run_id":str(run.id), "actions": run.action_count}
